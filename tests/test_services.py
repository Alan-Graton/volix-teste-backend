"""Regras de serviço: vigência, resolução de produto/vendedor e EAN divergente."""
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.imports import services
from apps.imports.models import Importacao, ImportacaoLinha
from apps.products.models import Preco, Produto, Vendedor
from data.exceptions import LinhaRejeitada
from data.normalizers import LinhaNormalizada

pytestmark = pytest.mark.django_db


def _linha(**kwargs):
    padrao = dict(
        sku='SKU-9001',
        ean='7890001000051',
        produto_nome='Produto Serviço',
        embalagem=1,
        vendedor_nome='Carrefour',
        vendedor_chave='carrefour',
        uf='SP',
        preco=Decimal('10.00'),
        preco_promocional=None,
        moeda='BRL',
        estoque=5,
        coletado_em=datetime(2025, 3, 10, 10, 0, tzinfo=UTC),
    )
    padrao.update(kwargs)
    return LinhaNormalizada(**padrao)


def _importacao():
    return Importacao.objects.create(nome_arquivo_original='base.csv')


# --------------------------------------------------------------------------- #
# vigência: o preço vigente é o da última coleta
# --------------------------------------------------------------------------- #


def test_coleta_mais_recente_vira_vigente_e_desloca_a_antiga(db):
    importacao = _importacao()
    produto = Produto.objects.create(sku='SKU-9001', nome='P')
    vendedor = Vendedor.objects.create(nome='Carrefour', nome_normalizado='carrefour')

    antigo = Preco.objects.create(
        produto=produto,
        vendedor=vendedor,
        uf='SP',
        preco='9.00',
        coletado_em=datetime(2025, 3, 1, 10, 0, tzinfo=UTC),
        importacao=importacao,
        is_vigente=True,
    )
    novo = Preco.objects.create(
        produto=produto,
        vendedor=vendedor,
        uf='SP',
        preco='10.00',
        coletado_em=datetime(2025, 3, 20, 10, 0, tzinfo=UTC),
        importacao=importacao,
    )

    services._atualizar_vigente(novo)
    antigo.refresh_from_db()
    novo.refresh_from_db()
    assert novo.is_vigente is True
    assert antigo.is_vigente is False


def test_coleta_mais_antiga_nao_desloca_o_vigente(db):
    importacao = _importacao()
    produto = Produto.objects.create(sku='SKU-9001', nome='P')
    vendedor = Vendedor.objects.create(nome='Carrefour', nome_normalizado='carrefour')

    vigente = Preco.objects.create(
        produto=produto,
        vendedor=vendedor,
        uf='SP',
        preco='10.00',
        coletado_em=datetime(2025, 3, 20, 10, 0, tzinfo=UTC),
        importacao=importacao,
        is_vigente=True,
    )
    mais_antigo = Preco.objects.create(
        produto=produto,
        vendedor=vendedor,
        uf='SP',
        preco='8.00',
        coletado_em=datetime(2025, 3, 1, 10, 0, tzinfo=UTC),
        importacao=importacao,
    )

    services._atualizar_vigente(mais_antigo)
    vigente.refresh_from_db()
    mais_antigo.refresh_from_db()
    assert vigente.is_vigente is True
    assert mais_antigo.is_vigente is False


def test_vigencia_e_por_vendedor_e_uf(db):
    """Vendedores/UFs diferentes convivem com vigentes próprios."""
    importacao = _importacao()
    produto = Produto.objects.create(sku='SKU-9001', nome='P')
    vendedor_a = Vendedor.objects.create(nome='A', nome_normalizado='a')
    vendedor_b = Vendedor.objects.create(nome='B', nome_normalizado='b')

    a = Preco.objects.create(
        produto=produto,
        vendedor=vendedor_a,
        uf='SP',
        preco='10.00',
        coletado_em=datetime(2025, 3, 5, 10, 0, tzinfo=UTC),
        importacao=importacao,
        is_vigente=True,
    )
    b = Preco.objects.create(
        produto=produto,
        vendedor=vendedor_b,
        uf='RJ',
        preco='12.00',
        coletado_em=datetime(2025, 3, 4, 10, 0, tzinfo=UTC),
        importacao=importacao,
        is_vigente=True,
    )

    services._atualizar_vigente(b)
    a.refresh_from_db()
    b.refresh_from_db()
    assert a.is_vigente and b.is_vigente
    assert Preco.objects.filter(is_vigente=True).count() == 2


# --------------------------------------------------------------------------- #
# produto: a primeira linha define o cadastro; divergências rejeitam a linha
# --------------------------------------------------------------------------- #


def test_ean_divergente_rejeita_linha(db):
    Produto.objects.create(sku='SKU-9001', nome='Produto Serviço', ean='7890001000051')
    with pytest.raises(LinhaRejeitada) as capturado:
        services._resolver_produto(_linha(ean='789000137019'))
    motivos = capturado.value.motivos
    assert len(motivos) == 1
    assert 'EAN divergente' in motivos[0]
    assert '7890001000051' in motivos[0]
    assert '789000137019' in motivos[0]


def test_produto_criado_na_primeira_linha(db):
    produto = services._resolver_produto(_linha())
    assert produto.sku == 'SKU-9001'
    assert produto.ean == '7890001000051'
    assert produto.embalagem == 1


def test_produto_sem_ean_cadastrado_preenche(db):
    Produto.objects.create(sku='SKU-9001', nome='Produto Serviço', ean=None, embalagem=1)
    produto = services._resolver_produto(_linha())
    assert produto.ean == '7890001000051'
    assert produto.nome == 'Produto Serviço'


def test_produto_com_nome_divergente_rejeita_linha(db):
    Produto.objects.create(
        sku='SKU-9001', nome='Produto Serviço', ean='7890001000051', embalagem=1
    )
    with pytest.raises(LinhaRejeitada) as capturado:
        services._resolver_produto(_linha(produto_nome='Outro Nome Completo'))
    motivos = capturado.value.motivos
    assert len(motivos) == 1
    assert 'Nome divergente' in motivos[0]
    assert 'Outro Nome Completo' in motivos[0]


def test_produto_com_embalagem_divergente_rejeita_linha(db):
    Produto.objects.create(
        sku='SKU-9001', nome='Produto Serviço', ean='7890001000051', embalagem=1
    )
    with pytest.raises(LinhaRejeitada) as capturado:
        services._resolver_produto(_linha(embalagem=12))
    motivos = capturado.value.motivos
    assert len(motivos) == 1
    assert 'Embalagem divergente' in motivos[0]


def test_produto_com_nome_em_caixa_diferente_passa(db):
    """Caixa/espaços não contam como divergência (normalização de nome)."""
    Produto.objects.create(
        sku='SKU-9001', nome='Produto  Serviço', ean='7890001000051', embalagem=1
    )
    produto = services._resolver_produto(_linha(produto_nome='produto serviço'))
    assert produto.pk is not None
    assert produto.nome == 'Produto  Serviço'  # cadastro da primeira linha permanece


def test_produto_existente_com_ean_igual_passa(db):
    Produto.objects.create(
        sku='SKU-9001', nome='Produto Serviço', ean='7890001000051', embalagem=1
    )
    produto = services._resolver_produto(_linha())
    assert produto.pk is not None


# --------------------------------------------------------------------------- #
# vendedor: identidade pela chave normalizada
# --------------------------------------------------------------------------- #


def test_vendedor_mesma_chave_diferente_nome_e_o_mesmo(db):
    primeiro = services._resolver_vendedor(_linha())
    segundo = services._resolver_vendedor(
        _linha(vendedor_nome='CARREFOUR', vendedor_chave='carrefour')
    )
    assert primeiro.pk == segundo.pk
    assert Vendedor.objects.count() == 1


def test_vendedores_chaves_diferentes_sao_diferentes(db):
    services._resolver_vendedor(_linha())
    services._resolver_vendedor(_linha(vendedor_nome='Amazon', vendedor_chave='amazon'))
    assert Vendedor.objects.count() == 2


# --------------------------------------------------------------------------- #
# ponte com o tratamento: LinhaRejeitada -> quarentena (sem exceção vazando)
# --------------------------------------------------------------------------- #


def test_linha_rejeitada_vira_quarentena_sem_quebrar_importacao(auth_client, monkeypatch):
    from django.test import TestCase

    from tests.conftest import enviar_csv

    def sempre_rejeita(bruta):
        raise LinhaRejeitada(['Motivo determinístico'])

    monkeypatch.setattr(services, 'processar_linha', sempre_rejeita)

    conteudo = b'sku;ean;produto;vendedor;uf;preco;preco_promocional;moeda;estoque;coletado_em;embalagem\n'
    conteudo += b'SKU-1;1;P;V;SP;1.00;;BRL;1;2025-03-10T10:00:00-03:00;1\n'
    with TestCase.captureOnCommitCallbacks(execute=True):
        resposta = enviar_csv(auth_client, conteudo)

    importacao = Importacao.objects.get(pk=resposta.json()['id'])
    importacao.refresh_from_db()
    assert importacao.status == Importacao.Status.CONCLUIDA
    assert importacao.quarentena_count == 1
    linha = importacao.linhas.get()
    assert linha.status == ImportacaoLinha.Status.QUARENTENA
    assert linha.motivos == ['Motivo determinístico']


def test_data_naive_e_conscientizada_fuso(db):
    """Rede de segurança: datetime sem tz recebe o fuso configurado."""
    importacao = _importacao()
    produto = Produto.objects.create(sku='SKU-9001', nome='P')
    vendedor = Vendedor.objects.create(nome='Carrefour', nome_normalizado='carrefour')

    linha = _linha(coletado_em=datetime(2025, 3, 10, 10, 0))  # naive
    preco, criado = services._resolver_preco(importacao, produto, vendedor, linha)
    assert criado is True
    assert timezone.is_aware(preco.coletado_em)
    assert preco.coletado_em.utcoffset() == timedelta(hours=-3)  # America/Sao_Paulo