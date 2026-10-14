"""GET /api/produtos/{sku}/referencia/: mediana de mercado + ICMS 18%."""
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from apps.products import services
from apps.products.models import Preco, Produto, Vendedor

pytestmark = pytest.mark.django_db


def _produto(sku='SKU-8001'):
    return Produto.objects.create(sku=sku, nome='Cafeteira', ean='7890001000041')


def _vendedor(nome, chave=None):
    return Vendedor.objects.get_or_create(
        nome_normalizado=chave or nome.lower().replace(' ', ''),
        defaults={'nome': nome},
    )[0]


def _vigente(produto, vendedor, uf, valor, horas=0):
    return Preco.objects.create(
        produto=produto,
        vendedor=vendedor,
        uf=uf,
        preco=Decimal(valor),
        moeda='BRL',
        estoque=1,
        coletado_em=datetime(2025, 3, 10, 10, 0, tzinfo=UTC) + timedelta(hours=horas),
        importacao=_importacao(),
        is_vigente=True,
    )


def _importacao():
    from apps.imports.models import Importacao

    return Importacao.objects.create(nome_arquivo_original='base.csv')


# --------------------------------------------------------------------------- #
# funções puras
# --------------------------------------------------------------------------- #


def test_calcular_preco_referencia_mediana_impar():
    assert services.calcular_preco_referencia(
        [Decimal('30.00'), Decimal('10.00'), Decimal('20.00')]
    ) == Decimal('20.00')


def test_calcular_preco_referencia_mediana_par():
    assert services.calcular_preco_referencia(
        [Decimal('10.00'), Decimal('40.00'), Decimal('20.00'), Decimal('30.00')]
    ) == Decimal('25.00')


def test_calcular_preco_referencia_sem_valores():
    with pytest.raises(ValueError):
        services.calcular_preco_referencia([])


def test_preco_liquido_icms_18_por_cento():
    liquido, icms = services.calcular_preco_liquido_icms(Decimal('20.00'))
    assert liquido == Decimal('16.95')  # 20 / 1.18
    assert icms == Decimal('3.05')
    assert liquido + icms == Decimal('20.00')


def test_arredondamento_meio_para_cima():
    assert services.arredondar_centavos(Decimal('16.945')) == Decimal('16.95')


# --------------------------------------------------------------------------- #
# endpoint
# --------------------------------------------------------------------------- #


def test_referencia_com_tres_vendedores(auth_client):
    produto = _produto()
    _vigente(produto, _vendedor('Carrefour'), 'SP', '30.00', horas=0)
    _vigente(produto, _vendedor('Amazon BR'), 'SP', '10.00', horas=1)
    _vigente(produto, _vendedor('Magazine Luiza'), 'SP', '20.00', horas=2)

    resposta = auth_client.get('/api/produtos/SKU-8001/referencia/')
    assert resposta.status_code == 200
    dados = resposta.json()
    assert dados['sku'] == 'SKU-8001'
    assert dados['produto'] == 'Cafeteira'
    assert dados['moeda'] == 'BRL'
    assert dados['preco_referencia'] == '20.00'
    assert dados['aliquota_icms'] == '0.18'
    assert dados['preco_liquido_icms'] == '16.95'
    assert dados['valor_icms'] == '3.05'
    assert dados['vendedores_considerados'] == 3
    assert dados['uf'] is None
    assert dados['criterio'] == 'mediana dos preços vigentes'


def test_referencia_ignora_precos_nao_vigentes(auth_client):
    produto = _produto()
    _vigente(produto, _vendedor('Carrefour'), 'SP', '20.00')
    Preco.objects.create(
        produto=produto,
        vendedor=_vendedor('Mercado Livre'),
        uf='SP',
        preco=Decimal('999.99'),
        coletado_em=datetime(2025, 1, 1, tzinfo=UTC),
        importacao=_importacao(),
        is_vigente=False,
    )

    resposta = auth_client.get('/api/produtos/SKU-8001/referencia/')
    assert resposta.status_code == 200
    assert resposta.json()['preco_referencia'] == '20.00'
    assert resposta.json()['vendedores_considerados'] == 1


def test_referencia_com_filtro_de_uf(auth_client):
    produto = _produto()
    _vigente(produto, _vendedor('Carrefour'), 'SP', '20.00', horas=0)
    _vigente(produto, _vendedor('Amazon BR'), 'RJ', '40.00', horas=1)

    todas = auth_client.get('/api/produtos/SKU-8001/referencia/')
    assert todas.json()['preco_referencia'] == '30.00'  # mediana de 20 e 40
    assert todas.json()['vendedores_considerados'] == 2

    so_sp = auth_client.get('/api/produtos/SKU-8001/referencia/?uf=sp')
    assert so_sp.status_code == 200
    assert so_sp.json()['preco_referencia'] == '20.00'
    assert so_sp.json()['uf'] == 'SP'
    assert so_sp.json()['vendedores_considerados'] == 1


def test_referencia_uf_invalida_retorna_400(auth_client):
    _produto()
    resposta = auth_client.get('/api/produtos/SKU-8001/referencia/?uf=XYZ')
    assert resposta.status_code == 400
    assert 'uf' in resposta.json()


def test_referencia_sku_case_insensitive(auth_client):
    produto = _produto()
    _vigente(produto, _vendedor('Carrefour'), 'SP', '15.00')

    resposta = auth_client.get('/api/produtos/sku-8001/referencia/')
    assert resposta.status_code == 200
    assert resposta.json()['sku'] == 'SKU-8001'


def test_referencia_produto_inexistente_404(auth_client):
    resposta = auth_client.get('/api/produtos/SKU-4044/referencia/')
    assert resposta.status_code == 404


def test_referencia_sem_preco_vigente_404(auth_client):
    _produto()
    resposta = auth_client.get('/api/produtos/SKU-8001/referencia/')
    assert resposta.status_code == 404


def test_referencia_uf_sem_precos_404(auth_client):
    produto = _produto()
    _vigente(produto, _vendedor('Carrefour'), 'SP', '20.00')

    resposta = auth_client.get('/api/produtos/SKU-8001/referencia/?uf=MG')
    assert resposta.status_code == 404
    assert 'MG' in resposta.json()['detail']