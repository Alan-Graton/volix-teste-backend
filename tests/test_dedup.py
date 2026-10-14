"""Requisito: importar o mesmo arquivo duas vezes não duplica dados."""
import pytest
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.imports.models import Importacao, ImportacaoLinha
from apps.products.models import Preco, Produto, Vendedor

from .conftest import enviar_csv

pytestmark = pytest.mark.django_db


def _importar(auth_client, conteudo, nome='precos.csv'):
    with TestCase.captureOnCommitCallbacks(execute=True):
        resposta = enviar_csv(auth_client, conteudo, nome=nome)
    assert resposta.status_code == 202
    importacao = Importacao.objects.get(pk=resposta.json()['id'])
    return resposta.json(), importacao


def test_mesmo_arquivo_duas_vezes_nao_duplica(auth_client, tratamento_duble):
    from .conftest import csv_padrao

    conteudo = csv_padrao(4)

    primeira, importacao1 = _importar(auth_client, conteudo)
    assert importacao1.status == Importacao.Status.CONCLUIDA
    assert importacao1.processadas == 4
    precos_apos_1 = Preco.objects.count()
    assert precos_apos_1 == 4

    segunda, importacao2 = _importar(auth_client, conteudo)
    assert segunda['duplicado'] is True
    assert importacao2.pk == importacao1.pk  # reaproveita a mesma importação

    assert Importacao.objects.count() == 1
    assert Preco.objects.count() == 4
    assert ImportacaoLinha.objects.count() == 4


def test_arquivo_identico_apos_falha_permite_nova_tentativa(auth_client, tratamento_duble):
    conteudo_ruim = b'sku;ean;produto\nSKU-9;x;P\n'  # cabeçalho incompleto -> falha

    _, primeira = _importar(auth_client, conteudo_ruim, nome='ruim.csv')
    assert primeira.status == Importacao.Status.FALHOU

    segunda_resposta, segunda = _importar(auth_client, conteudo_ruim, nome='ruim.csv')
    assert segunda_resposta['duplicado'] is False
    assert segunda.pk != primeira.pk
    assert Importacao.objects.count() == 2


def test_linhas_repetidas_no_mesmo_arquivo_nao_duplicam(auth_client, tratamento_duble):
    from .conftest import montar_csv

    linha = {
        'sku': 'SKU-4001',
        'ean': '7890001000009',
        'produto': 'Repetível',
        'vendedor': 'Carrefour',
        'uf': 'SP',
        'preco': '19.90',
        'moeda': 'BRL',
        'estoque': '7',
        'coletado_em': '2025-03-10T10:00:00-03:00',
        'embalagem': '1',
    }
    # mesma linha em duas versões de caixa no vendedor: mesma chave normalizada
    linha_caixa_alta = dict(linha, vendedor='CARREFOUR')

    _, importacao = _importar(auth_client, montar_csv([linha, linha_caixa_alta]))

    assert importacao.status == Importacao.Status.CONCLUIDA
    assert importacao.processadas == 1
    assert importacao.duplicadas_count == 1
    assert Preco.objects.count() == 1

    duplicada = importacao.linhas.get(status=ImportacaoLinha.Status.DUPLICADA)
    assert duplicada.numero_linha == 2
    assert any('já existente' in motivo for motivo in duplicada.motivos)


def test_linha_igual_em_arquivo_diferente_vira_duplicada(auth_client, tratamento_duble):
    from .conftest import csv_padrao, montar_csv

    conteudo1 = csv_padrao(2)
    primeira, importacao1 = _importar(auth_client, conteudo1, nome='a.csv')
    assert importacao1.processadas == 2

    # arquivo diferente (hash muda), mas com a mesma primeira linha + uma nova
    linhas_extras = [
        {
            'sku': 'SKU-5001',
            'ean': '7890001000011',
            'produto': 'Novidade',
            'vendedor': 'Amazon BR',
            'uf': 'RJ',
            'preco': '33.30',
            'moeda': 'BRL',
            'estoque': '2',
            'coletado_em': '2025-03-11T09:00:00-03:00',
            'embalagem': '1',
        }
    ]
    conteudo2 = conteudo1 + montar_csv(linhas_extras).split(b'\n', 1)[1]

    segunda, importacao2 = _importar(auth_client, conteudo2, nome='b.csv')
    assert segunda['duplicado'] is False
    assert importacao2.pk != importacao1.pk

    assert importacao2.processadas == 1  # só a linha nova
    assert importacao2.duplicadas_count == 2  # as duas antigas já existiam
    assert Preco.objects.count() == 3


def test_restricao_unica_de_coleta_no_banco(db):
    from datetime import UTC, datetime

    from apps.imports.models import Importacao

    produto = Produto.objects.create(sku='SKU-6001', nome='P', ean='7890001000021')
    vendedor = Vendedor.objects.create(nome='X', nome_normalizado='x')
    momento = datetime(2025, 3, 10, 10, 0, tzinfo=UTC)
    importacao = Importacao.objects.create()
    Preco.objects.create(
        produto=produto,
        vendedor=vendedor,
        uf='SP',
        preco='10.00',
        coletado_em=momento,
        importacao=importacao,
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        Preco.objects.create(
            produto=produto,
            vendedor=vendedor,
            uf='SP',
            preco='11.00',
            coletado_em=momento,
            importacao=importacao,
        )