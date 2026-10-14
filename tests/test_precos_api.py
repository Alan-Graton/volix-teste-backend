"""GET /api/precos/: lista paginada do preço vigente com filtros."""
from datetime import UTC, datetime, timedelta

import pytest

from apps.products.models import Preco, Produto, Vendedor

pytestmark = pytest.mark.django_db


def _produto(sku='SKU-7001', nome='Produto Teste', ean='7890001000031'):
    return Produto.objects.create(sku=sku, nome=nome, ean=ean)


def _vendedor(nome='Carrefour'):
    chave = nome.lower().replace(' ', '')
    return Vendedor.objects.get_or_create(nome_normalizado=chave, defaults={'nome': nome})[0]


def _preco(produto, vendedor, uf='SP', valor='10.00', momento=None, vigente=True):
    return Preco.objects.create(
        produto=produto,
        vendedor=vendedor,
        uf=uf,
        preco=valor,
        moeda='BRL',
        estoque=5,
        coletado_em=momento or datetime(2025, 3, 10, 10, 0, tzinfo=UTC),
        importacao=_importacao(),
        is_vigente=vigente,
    )


def _importacao():
    from apps.imports.models import Importacao

    return Importacao.objects.create(nome_arquivo_original='base.csv')


def test_lista_apenas_precos_vigentes(auth_client):
    produto = _produto()
    vendedor = _vendedor()
    antigo = _preco(
        produto, vendedor, valor='9.00', momento=datetime(2025, 3, 1, 10, 0, tzinfo=UTC),
        vigente=False,
    )
    novo = _preco(
        produto, vendedor, valor='11.00', momento=datetime(2025, 3, 20, 10, 0, tzinfo=UTC),
        vigente=True,
    )

    resposta = auth_client.get('/api/precos/')
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo['count'] == 1
    item = corpo['results'][0]
    assert item['sku'] == 'SKU-7001'
    assert item['produto'] == 'Produto Teste'
    assert item['ean'] == '7890001000031'
    assert item['vendedor'] == 'Carrefour'
    assert item['uf'] == 'SP'
    assert item['preco'] == '11.00'
    assert item['coletado_em']  # datetime serializado
    assert antigo.pk != novo.pk


def test_filtro_por_sku(auth_client):
    _produto('SKU-7001')
    _produto('SKU-7002')
    vendedor = _vendedor()
    _preco(Produto.objects.get(sku='SKU-7001'), vendedor)
    _preco(Produto.objects.get(sku='SKU-7002'), vendedor)

    resposta = auth_client.get('/api/precos/?sku=sku-7001')  # case-insensitive
    assert resposta.status_code == 200
    assert resposta.json()['count'] == 1
    assert resposta.json()['results'][0]['sku'] == 'SKU-7001'


def test_filtro_por_uf_normaliza_caixa(auth_client):
    produto = _produto()
    vendedor = _vendedor()
    _preco(produto, vendedor, uf='SP')
    _preco(
        produto,
        vendedor,
        uf='RJ',
        momento=datetime(2025, 3, 11, 10, 0, tzinfo=UTC),
    )

    resposta = auth_client.get('/api/precos/?uf=sp')
    assert resposta.status_code == 200
    assert resposta.json()['count'] == 1
    assert resposta.json()['results'][0]['uf'] == 'SP'


def test_filtro_por_uf_invalida_retorna_400(auth_client):
    resposta = auth_client.get('/api/precos/?uf=Brasil')
    assert resposta.status_code == 400
    assert 'uf' in resposta.json()


def test_filtro_por_vendedor_fallback_case_insensitive(auth_client, monkeypatch):
    """Sem normalizador implementado, o filtro cai para iexact (NotImplementedError)."""
    from data.normalizers import normalizar_vendedor  # noqa: F401

    produto = _produto()
    vendedor = Vendedor.objects.create(nome='Casas Bahia', nome_normalizado='casasbahia')
    _preco(produto, vendedor)

    resposta = auth_client.get('/api/precos/?vendedor=casas%20bahia')
    assert resposta.status_code == 200
    assert resposta.json()['count'] == 1


def test_filtro_por_vendedor_usa_chave_normalizada(auth_client, monkeypatch):
    import apps.products.views as views_produtos

    monkeypatch.setattr(
        views_produtos, 'normalizar_vendedor', lambda nome: nome.lower().replace(' ', '')
    )
    produto = _produto()
    vendedor = Vendedor.objects.create(nome='Casas Bahia', nome_normalizado='casasbahia')
    _preco(produto, vendedor)

    # consulta com forma diferente do nome armazenado, igual via chave normalizada
    resposta = auth_client.get('/api/precos/?vendedor=CASASBAHIA')
    assert resposta.status_code == 200
    assert resposta.json()['count'] == 1


def test_paginacao(auth_client):
    produto = _produto()
    vendedor = _vendedor()
    inicio = datetime(2025, 3, 1, 10, 0, tzinfo=UTC)
    for i in range(25):
        _preco(
            produto,
            vendedor,
            uf='SP' if i % 2 == 0 else 'RJ',
            momento=inicio + timedelta(hours=i),
            vigente=True,
        )

    pagina1 = auth_client.get('/api/precos/')
    assert pagina1.status_code == 200
    assert pagina1.json()['count'] == 25
    assert len(pagina1.json()['results']) == 20

    pagina2 = auth_client.get('/api/precos/?page=2')
    assert pagina2.status_code == 200
    assert len(pagina2.json()['results']) == 5


def test_produto_sem_ean_retorna_null(auth_client):
    produto = _produto(ean=None)
    vendedor = _vendedor()
    _preco(produto, vendedor)

    resposta = auth_client.get('/api/precos/')
    assert resposta.status_code == 200
    assert resposta.json()['results'][0]['ean'] is None