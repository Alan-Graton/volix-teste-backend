"""Testes das REGRAS DE VALIDAÇÃO do CSV (data.validators.validar_linha).

Cada rejeição vira um motivo específico em português — os testes de quarentena
(tests/test_imports_api.py) já garantem que motivos recebidos são persistidos
e expostos na API. Cobertura baseada nos problemas reais do CSV de produção
(números de linha = linha de dados, sem contar o cabeçalho).
"""
import pytest

from data.validators import validar_linha


def linha_valida(**campos) -> dict[str, str]:
    """Linha sintética 100% válida; sobrescreva o que o teste precisa."""
    linha = {
        'sku': 'SKU-7001',
        'ean': '7890001000009',
        'produto': 'Açúcar Refinado 1kg',
        'vendedor': 'Carrefour',
        'uf': 'SP',
        'preco': '4,67',
        'preco_promocional': '',
        'moeda': 'BRL',
        'estoque': '10',
        'coletado_em': '2025-03-10T10:00:00-03:00',
        'embalagem': '1',
        '_extras': '',
    }
    linha.update(campos)
    return linha


def motivos_de(**campos) -> list[str]:
    return validar_linha(linha_valida(**campos))


# --------------------------------------------------------------------------- #
# linha limpa e formatos de preço aceitos
# --------------------------------------------------------------------------- #


def test_linha_correta_nao_tem_motivos():
    assert validar_linha(linha_valida()) == []


@pytest.mark.parametrize(
    'preco',
    ['4,67', '3.169,98', 'R$ 127,50', '1234.56', '1.299.90', '1.299', '6.26', '999,99'],
)
def test_formatos_de_preco_aceitos(preco):
    assert motivos_de(preco=preco) == []


def test_linha_com_promocao_valida_passa():
    assert motivos_de(preco='4,67', preco_promocional='3,99') == []


def test_uf_em_caixa_baixa_e_normalizada_nao_rejeita():
    assert motivos_de(uf='sp') == []


def test_datas_em_varios_formatos_sao_aceitas():
    for data in (
        '2025-03-10T10:00:00-03:00',
        '2025-03-10 12:09:00Z',
        '2025-03-10',
        '04/03/2025 13:41',
        '03/25/2025 09:00',
    ):
        assert motivos_de(coletado_em=data) == [], data


def test_estoque_esgotado_e_vazio_sao_aceitos():
    assert motivos_de(estoque='esgotado') == []
    assert motivos_de(estoque='') == []


def test_ean_vazio_e_opcional():
    assert motivos_de(ean='') == []


@pytest.mark.parametrize('uf', ['AC', 'AM', 'BA', 'DF', 'MG', 'PR', 'RJ', 'RS', 'SC', 'SP', 'TO'])
def test_todas_as_ufs_do_brasil_sao_aceitas(uf):
    assert motivos_de(uf=uf) == []


@pytest.mark.parametrize('vendedor', ['Carrefour', 'CARREFOUR', ' carrefour ', 'casasbahia', 'Casas Bahia', 'Amazon BR', 'Mercado Livre', 'Magazine Luiza'])
def test_vendedores_da_whitelist_sao_aceitos(vendedor):
    assert motivos_de(vendedor=vendedor) == []


# --------------------------------------------------------------------------- #
# preços
# --------------------------------------------------------------------------- #


def test_preco_ausente():
    assert motivos_de(preco='') == ['Preço ausente']


def test_preco_nao_numerico():
    assert motivos_de(preco='Sob consulta') == ["Preço inválido: 'Sob consulta'"]


@pytest.mark.parametrize('preco', ['0,00', '-5,90'])
def test_preco_nao_positivo(preco):
    (motivo,) = motivos_de(preco=preco)
    assert motivo == f'Preço não positivo: {preco}'


@pytest.mark.parametrize('preco', ['0,01', '999.999,99'])
def test_preco_fora_da_faixa_plausivel(preco):
    (motivo,) = motivos_de(preco=preco)
    assert 'Preço fora da faixa plausível' in motivo
    assert preco in motivo


def test_promocao_maior_que_o_preco():
    (motivo,) = motivos_de(preco='10,00', preco_promocional='25,00')
    assert '25,00' in motivo and '10,00' in motivo
    assert 'maior que' in motivo


def test_promocao_nao_numerica():
    assert motivos_de(preco='10,00', preco_promocional='abc') == ["Promoção inválida: 'abc'"]


# --------------------------------------------------------------------------- #
# moeda, estoque, embalagem, UF
# --------------------------------------------------------------------------- #


def test_moeda_diferente_de_brl():
    (motivo,) = motivos_de(moeda='USD')
    assert 'Moeda não suportada' in motivo and 'USD' in motivo


def test_moeda_ausente():
    assert motivos_de(moeda='') == ['Moeda ausente']


def test_estoque_negativo():
    assert motivos_de(estoque='-3') == ['Estoque negativo: -3']


def test_estoque_nao_numerico():
    assert motivos_de(estoque='muitos') == ["Estoque inválido: 'muitos'"]


def test_uf_inexistente():
    assert motivos_de(uf='XX') == ["UF inválida: 'XX'"]


@pytest.mark.parametrize('embalagem', ['abc', '0', '-2'])
def test_embalagem_invalida(embalagem):
    (motivo,) = motivos_de(embalagem=embalagem)
    assert 'Embalagem inválida' in motivo


# --------------------------------------------------------------------------- #
# datas
# --------------------------------------------------------------------------- #


def test_data_ausente():
    assert motivos_de(coletado_em='') == ['Data de coleta ausente']


def test_data_impossivel():
    assert motivos_de(coletado_em='30/02/2025 10:00') == [
        "Data de coleta inválida: '30/02/2025 10:00'"
    ]


def test_data_no_futuro():
    (motivo,) = motivos_de(coletado_em='2031-01-01T00:00:00-03:00')
    assert 'no futuro' in motivo


def test_data_ontem_e_aceita():
    assert motivos_de(coletado_em='2025-03-10') == []


# --------------------------------------------------------------------------- #
# EAN (GTIN-13)
# --------------------------------------------------------------------------- #


def test_ean_com_numero_errado_de_digitos():
    (motivo,) = motivos_de(ean='789000137019')
    assert 'EAN inválido' in motivo and 'GTIN-13' in motivo


def test_ean_com_digito_verificador_errado():
    (motivo,) = motivos_de(ean='7890001370000')
    assert 'dígito verificador' in motivo


def test_ean_em_notacao_cientifica():
    (motivo,) = motivos_de(ean='7,89E+12')
    assert 'EAN inválido' in motivo


# --------------------------------------------------------------------------- #
# segurança: injeção (whitelist de vendedores e fórmulas de planilha)
# --------------------------------------------------------------------------- #


def test_vendedor_fora_da_whitelist():
    (motivo,) = motivos_de(vendedor="x'; DROP TABLE precos;--")
    assert 'Vendedor fora da lista de concorrentes aceitos' in motivo
    assert 'DROP TABLE' in motivo


def test_vendedor_ausente():
    assert motivos_de(vendedor='') == ['Vendedor ausente']


def test_produto_com_inicio_de_formula():
    (motivo,) = motivos_de(produto='=HYPERLINK("http://evil")')
    assert 'fórmula' in motivo


def test_sku_com_inicio_de_formula():
    (motivo,) = motivos_de(sku='=1+1')
    assert 'SKU' in motivo and 'fórmula' in motivo


def test_sku_ausente():
    assert motivos_de(sku='') == ['SKU ausente']


def test_produto_ausente():
    assert motivos_de(produto='') == ['Nome do produto ausente']


def test_coluna_extra_rejeita():
    (motivo,) = motivos_de(_extras='coluna-extra')
    assert 'Coluna extra' in motivo and 'coluna-extra' in motivo


# --------------------------------------------------------------------------- #
# diagnóstico completo: todos os problemas da linha em uma lista só
# --------------------------------------------------------------------------- #


def test_reune_todos_os_motivos_da_linha():
    motivos = validar_linha(
        linha_valida(uf='XX', moeda='USD', preco='', vendedor='', produto='')
    )
    assert any('Preço ausente' in motivo for motivo in motivos)
    assert any('Moeda não suportada' in motivo for motivo in motivos)
    assert any('UF inválida' in motivo for motivo in motivos)
    assert any('Vendedor ausente' in motivo for motivo in motivos)
    assert any('Nome do produto ausente' in motivo for motivo in motivos)
    assert len(motivos) == 5


def test_linha_truncada_gera_varios_motivos():
    truncada = {
        'sku': 'SKU-1001',
        'ean': '7890001370000',
        'produto': 'Linha truncada',
        'vendedor': '',
        'uf': '',
        'preco': '',
        'preco_promocional': '',
        'moeda': '',
        'estoque': '',
        'coletado_em': '',
        'embalagem': '',
        '_extras': '',
    }
    motivos = validar_linha(truncada)
    assert 'Vendedor ausente' in motivos
    assert 'UF ausente' in motivos
    assert 'Moeda ausente' in motivos
    assert 'Preço ausente' in motivos
    assert 'Data de coleta ausente' in motivos
    assert any('dígito verificador' in motivo for motivo in motivos)
    assert len(motivos) == 6


def test_campos_ausentes_do_dict_nao_explodem():
    assert validar_linha({}) != []
