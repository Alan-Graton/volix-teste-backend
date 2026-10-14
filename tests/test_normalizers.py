"""Testes das REGRAS DE NORMALIZAÇÃO do CSV (data.normalizers).

Cobre ``processar_linha``, ``normalizar_vendedor``, ``titulo`` e
``nomes_coincidem``: formatos pt-BR/en-US, datas conscientes de fuso,
chave de identidade do vendedor e o levantamento de ``LinhaRejeitada``.
"""
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from data.exceptions import LinhaRejeitada
from data.normalizers import (
    LinhaNormalizada,
    nomes_coincidem,
    normalizar_vendedor,
    processar_linha,
    titulo,
)

SP = ZoneInfo('America/Sao_Paulo')


def bruta(**campos) -> dict[str, str]:
    """Linha sintética 100% válida; sobrescreva o que o teste precisa."""
    linha = {
        'sku': 'SKU-7001',
        'ean': '7890001000009',
        'produto': 'Açúcar Refinado 1kg',
        'vendedor': 'Carrefour',
        'uf': 'sp',
        'preco': '4,67',
        'preco_promocional': '',
        'moeda': 'brl',
        'estoque': '10',
        'coletado_em': '2025-03-10T10:00:00-03:00',
        'embalagem': '1',
        '_extras': '',
    }
    linha.update(campos)
    return linha


# --------------------------------------------------------------------------- #
# preços -> Decimal (sem passar por float)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    'texto,esperado',
    [
        ('4,67', Decimal('4.67')),
        ('3.169,98', Decimal('3169.98')),
        ('R$ 127,50', Decimal('127.50')),
        ('R$ 1.739,24', Decimal('1739.24')),
        ('1234.56', Decimal('1234.56')),
        ('1.299.90', Decimal('1299.90')),
        ('1.299', Decimal('1299')),
        ('6.26', Decimal('6.26')),
        ('999,99', Decimal('999.99')),
    ],
)
def test_processar_linha_normaliza_formatos_br(texto, esperado):
    linha = processar_linha(bruta(preco=texto))
    assert linha.preco == esperado
    assert isinstance(linha.preco, Decimal)
    assert linha.preco.as_tuple().exponent in (-1, -2) or linha.preco == linha.preco.to_integral_value()


def test_promocional_convertido_e_ausente_vira_none():
    assert processar_linha(bruta(preco_promocional='2,52')).preco_promocional == Decimal('2.52')
    assert processar_linha(bruta(preco_promocional='')).preco_promocional is None


# --------------------------------------------------------------------------- #
# datas -> datetime consciente de fuso (America/Sao_Paulo)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    'texto,esperado',
    [
        ('2025-03-16T09:44:00-03:00', datetime(2025, 3, 16, 9, 44, tzinfo=SP)),
        ('2025-03-10 12:09:00Z', datetime(2025, 3, 10, 9, 9, tzinfo=SP)),
        ('04/03/2025 13:41', datetime(2025, 3, 4, 13, 41, tzinfo=SP)),
        ('03/25/2025 09:00', datetime(2025, 3, 25, 9, 0, tzinfo=SP)),
        ('2025-03-10', datetime(2025, 3, 10, 0, 0, tzinfo=SP)),
    ],
)
def test_datas_em_todos_os_formatos_viram_sp(texto, esperado):
    linha = processar_linha(bruta(coletado_em=texto))
    assert linha.coletado_em == esperado
    assert linha.coletado_em.utcoffset() == esperado.utcoffset()
    assert linha.coletado_em.tzinfo is not None


def test_data_com_offset_preserva_o_instante():
    """2025-03-16T09:44-03:00 é o mesmo instante independentemente do fuso."""
    linha = processar_linha(bruta(coletado_em='2025-03-16T09:44:00-03:00'))
    assert linha.coletado_em.timestamp() == datetime(2025, 3, 16, 12, 44, tzinfo=ZoneInfo('UTC')).timestamp()


# --------------------------------------------------------------------------- #
# campos normalizados
# --------------------------------------------------------------------------- #


def test_processar_linha_normaliza_uf_e_moeda_e_sku():
    linha = processar_linha(bruta(uf='sp', moeda='brl', sku='  SKU-7001  '))
    assert linha.uf == 'SP'
    assert linha.moeda == 'BRL'
    assert linha.sku == 'SKU-7001'


def test_processar_linha_estoque_esgotado_vira_zero():
    assert processar_linha(bruta(estoque='esgotado')).estoque == 0


def test_processar_linha_estoque_vazio_vira_none():
    assert processar_linha(bruta(estoque='')).estoque is None


def test_processar_linha_embalagem_vazia_vira_padrao():
    assert processar_linha(bruta(embalagem='')).embalagem == 1


def test_processar_linha_ean_vazio_vira_none():
    assert processar_linha(bruta(ean='')).ean is None


def test_processar_linha_produto_com_titulo_padrao():
    linha = processar_linha(bruta(produto='cafeteira elétrica'))
    assert linha.produto_nome == 'Cafeteira Elétrica'


def test_processar_linha_preserva_nome_original_quando_ja_e_titulo():
    linha = processar_linha(bruta())
    assert linha.produto_nome == 'Açúcar Refinado 1kg'


def test_processar_linha_vendedor_com_espacos_extras():
    linha = processar_linha(bruta(vendedor='  Carrefour '))
    assert linha.vendedor_nome == 'Carrefour'
    assert linha.vendedor_chave == 'carrefour'


def test_processar_linha_guarda_dados_originais():
    bruta_linha = bruta()
    linha = processar_linha(bruta_linha)
    assert linha.dados_originais == bruta_linha


def test_processar_linha_retorna_linha_normalizada():
    assert isinstance(processar_linha(bruta()), LinhaNormalizada)


def test_processar_linha_rejeitada_levanta_com_motivos():
    with pytest.raises(LinhaRejeitada) as capturado:
        processar_linha(bruta(preco='Sob consulta', uf='XX'))
    motivos = capturado.value.motivos
    assert len(motivos) == 2
    assert any('Preço inválido' in m for m in motivos)
    assert any('UF inválida' in m for m in motivos)


def test_processar_linha_sem_campos_rejeita():
    with pytest.raises(LinhaRejeitada):
        processar_linha({})


# --------------------------------------------------------------------------- #
# vendedor: chave de identidade (deduplicação + whitelist + filtro da API)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    'nomes,chave_esperada',
    [
        (['Carrefour', 'CARREFOUR', ' carrefour ', 'carrefour'], 'carrefour'),
        (['Casas Bahia', 'casasbahia', ' CASAS BAHIA ', 'casas  bahia'], 'casasbahia'),
        (['Amazon BR', 'amazon br', 'AMAZONBR'], 'amazonbr'),
        (['Mercado Livre', 'mercado livre'], 'mercadolivre'),
        (['Magazine Luiza', 'MAGAZINE LUIZA'], 'magazineluiza'),
        (['Loja São João', 'loja sao joao', 'LOJA SAO JOAO'], 'lojasaojoao'),
    ],
)
def test_normalizar_vendedor_mesma_chave(nomes, chave_esperada):
    chaves = {normalizar_vendedor(nome) for nome in nomes}
    assert chaves == {chave_esperada}


def test_normalizar_vendedor_nao_levanta_em_nome_vazio():
    assert normalizar_vendedor('') == ''


def test_normalizar_vendedor_independente_de_caixa_e_acentos():
    assert normalizar_vendedor('MERCADO LIVRE') == normalizar_vendedor('mercado livre')
    assert normalizar_vendedor('SAO PAULO STORE') == normalizar_vendedor('São Paulo Store')


# --------------------------------------------------------------------------- #
# título do produto e comparação de nomes
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    'entrada,esperado',
    [
        ('cafeteira elétrica', 'Cafeteira Elétrica'),
        ('notebook 15" 8gb', 'Notebook 15" 8gb'),
        ('óleo de soja 900ml', 'Óleo de Soja 900ml'),
        ('sabão em pó 2kg', 'Sabão em Pó 2kg'),
        ('macarrão espaguete 500g', 'Macarrão Espaguete 500g'),
        ('  Leite   Integral 1L ', 'Leite Integral 1L'),
        ('AÇÚCAR REFINADO 1KG', 'AÇÚCAR REFINADO 1KG'),
    ],
)
def test_titulo_padrao_do_produto(entrada, esperado):
    assert titulo(entrada) == esperado


@pytest.mark.parametrize(
    'a,b,esperado',
    [
        ('Produto Serviço', 'produto serviço', True),
        ('Produto  Serviço', 'Produto Serviço', True),
        ('Produto Serviço', 'Outro Produto', False),
        ('Notebook 15" 8GB', 'notebook 15" 8gb', True),
    ],
)
def test_nomes_coincidem(a, b, esperado):
    assert nomes_coincidem(a, b) is esperado
