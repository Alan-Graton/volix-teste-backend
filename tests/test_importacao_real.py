"""CSV real de produção processado com validação/normalização verdadeiras.

Sem dublê: exercita ``data.validators`` + ``data.normalizers`` + serviço de
importação de ponta a ponta. Os números de linha são os de **linha de dados**
(cabeçalho não conta) — a mesma numeração exposta pela API de quarentena.

Contagens esperadas sobre ``dados/precos_concorrentes.csv`` (321 linhas):
288 aproveitadas, 22 em quarentena e 11 duplicadas por chave natural.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from django.test import TestCase

from apps.imports.models import Importacao, ImportacaoLinha
from apps.products.models import Preco, Produto, Vendedor

from .conftest import enviar_csv

pytestmark = pytest.mark.django_db

SP = ZoneInfo('America/Sao_Paulo')

TOTAL_LINHAS = 321
PROCESSADAS = 288

LINHAS_QUARENTENA = frozenset(
    {
        41,  # preço 0,00
        58,  # preço ausente
        59,  # nome divergente (mojibake AÃºcar Cristal 1kg)
        65,  # preço "Sob consulta"
        128,  # EAN com 12 dígitos
        131,  # data impossível 30/02/2025
        162,  # nome divergente (Fone "Pro" no SKU do Notebook)
        163,  # promoção maior que o preço
        174,  # preço 999.999,99 fora da faixa
        181,  # estoque negativo
        190,  # vendedor com SQL injection (fora da whitelist)
        206,  # EAN com dígito verificador errado
        210,  # nome com fórmula =HYPERLINK
        225,  # nome + embalagem divergentes (Caixa c/ 12)
        226,  # preço 0,01 fora da faixa
        237,  # preço -5,90
        241,  # moeda USD
        257,  # data futura 2031
        295,  # UF XX
        306,  # EAN em notação científica
        320,  # linha truncada (só 4 campos)
        321,  # coluna extra
    }
)

LINHAS_DUPLICADAS = frozenset(
    {84, 192, 196, 215, 222, 274, 276, 278, 289, 296, 313}
)


@pytest.fixture
def importacao_real(auth_client, csv_real):
    """Processa o CSV real com o tratamento verdadeiro (sem dublê)."""
    with TestCase.captureOnCommitCallbacks(execute=True):
        resposta = enviar_csv(auth_client, csv_real, nome='precos_concorrentes.csv')
    assert resposta.status_code == 202
    importacao = Importacao.objects.get(pk=resposta.json()['id'])
    importacao.refresh_from_db()
    return importacao


def test_importacao_real_conclui_e_conta_tudo(importacao_real):
    assert importacao_real.status == Importacao.Status.CONCLUIDA
    assert importacao_real.erro == ''
    assert importacao_real.finalizada_em is not None

    assert importacao_real.total_linhas == TOTAL_LINHAS
    assert importacao_real.processadas == PROCESSADAS
    assert importacao_real.quarentena_count == len(LINHAS_QUARENTENA)
    assert importacao_real.duplicadas_count == len(LINHAS_DUPLICADAS)
    assert (
        importacao_real.processadas
        + importacao_real.quarentena_count
        + importacao_real.duplicadas_count
        == TOTAL_LINHAS
    )
    # nenhuma linha descartada em silêncio: uma trilha de auditoria por linha
    assert importacao_real.linhas.count() == TOTAL_LINHAS
    assert importacao_real.precos.count() == PROCESSADAS


def test_quarentena_registra_as_anomalias_com_motivo(importacao_real):
    rejeitadas = importacao_real.linhas.filter(status=ImportacaoLinha.Status.QUARENTENA)
    assert set(rejeitadas.values_list('numero_linha', flat=True)) == LINHAS_QUARENTENA
    assert all(linha.motivos for linha in rejeitadas)
    assert rejeitadas.filter(preco__isnull=False).count() == 0

    motivos = {linha.numero_linha: ' | '.join(linha.motivos) for linha in rejeitadas}
    assert 'Preço não positivo: 0,00' in motivos[41]
    assert 'Preço ausente' in motivos[58]
    assert 'Nome divergente' in motivos[59]
    assert "Preço inválido: 'Sob consulta'" in motivos[65]
    assert 'EAN inválido' in motivos[128]
    assert "Data de coleta inválida: '30/02/2025 10:00'" in motivos[131]
    assert 'Nome divergente' in motivos[162]
    assert 'maior que o preço' in motivos[163]
    assert 'faixa plausível' in motivos[174]
    assert 'Estoque negativo: -3' in motivos[181]
    assert 'DROP TABLE' in motivos[190]
    assert 'dígito verificador' in motivos[206]
    assert 'fórmula' in motivos[210]
    assert 'Embalagem divergente' in motivos[225]
    assert 'faixa plausível' in motivos[226]
    assert 'Preço não positivo: -5,90' in motivos[237]
    assert 'Moeda não suportada' in motivos[241] and 'USD' in motivos[241]
    assert 'no futuro' in motivos[257]
    assert "UF inválida: 'XX'" in motivos[295]
    assert 'EAN inválido' in motivos[306]
    assert 'Vendedor ausente' in motivos[320]
    assert 'Coluna extra' in motivos[321]

    # a linha crua fica preservada para auditoria
    linha_sob_consulta = importacao_real.linhas.get(numero_linha=65)
    assert linha_sob_consulta.dados_originais['preco'] == 'Sob consulta'
    assert importacao_real.linhas.get(numero_linha=321).dados_originais['_extras'] == (
        'coluna-extra'
    )


def test_duplicatas_sao_a_chave_natural_normalizada(importacao_real):
    duplicadas = importacao_real.linhas.filter(status=ImportacaoLinha.Status.DUPLICADA)
    assert set(duplicadas.values_list('numero_linha', flat=True)) == LINHAS_DUPLICADAS
    for linha in duplicadas:
        assert any('já existente' in motivo for motivo in linha.motivos)

    # vendedor '  Carrefour ' e nome em caixa baixa: mesma chave/coleta de antes
    linha_espacos = duplicadas.get(numero_linha=296)
    assert linha_espacos.dados_originais['vendedor'] == '  Carrefour '
    assert linha_espacos.dados_originais['produto'] == 'notebook 15" 8gb'
    # datas no formato com barra também casam com o instante ISO equivalente
    assert duplicadas.get(numero_linha=222).motivos


def test_linhas_aproveitadas_viram_historico_e_vigente(importacao_real):
    assert Preco.objects.count() == PROCESSADAS
    grupos = Preco.objects.values('produto', 'vendedor', 'uf').distinct().count()
    assert Preco.objects.filter(is_vigente=True).count() == grupos

    assert Produto.objects.count() == 15
    assert Vendedor.objects.count() == 5
    assert set(Vendedor.objects.values_list('nome_normalizado', flat=True)) == {
        'amazonbr',
        'carrefour',
        'casasbahia',
        'magazineluiza',
        'mercadolivre',
    }

    # 'esgotado' (linha 47) importado como estoque 0
    linha_47 = importacao_real.linhas.get(numero_linha=47)
    assert linha_47.status == ImportacaoLinha.Status.IMPORTADA
    assert linha_47.preco.estoque == 0

    # data em MM/DD (linha 60) aceita pelo fallback e convertida para SP
    linha_60 = importacao_real.linhas.get(numero_linha=60)
    assert linha_60.status == ImportacaoLinha.Status.IMPORTADA
    assert linha_60.preco.coletado_em == datetime(2025, 3, 25, 9, 0, tzinfo=SP)

    # UF em caixa baixa (linha 317) normalizada
    linha_317 = importacao_real.linhas.get(numero_linha=317)
    assert linha_317.status == ImportacaoLinha.Status.IMPORTADA
    assert linha_317.preco.uf == 'SP'

    # catálogo com nomes em título padrão e EAN mantido quando a linha o omitiu
    assert Produto.objects.get(sku='SKU-1014').nome == 'Cafeteira Elétrica'
    assert Produto.objects.get(sku='SKU-1010').nome == 'Farinha de Trigo 1kg'
    assert Produto.objects.get(sku='SKU-1005').nome == 'Óleo de Soja 900ml'
    assert Produto.objects.get(sku='SKU-1004').ean == '7890001004113'
