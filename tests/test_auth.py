"""Autenticação: todos os endpoints da API exigem token JWT."""
import pytest

ENDPOINTS_SEM_TOKEN = [
    ('get', '/api/precos/'),
    ('get', '/api/importacoes/'),
    ('get', '/api/importacoes/1/'),
    ('get', '/api/importacoes/1/quarentena/'),
    ('get', '/api/produtos/SKU-1001/referencia/'),
    ('get', '/api/auth/me/'),
]


@pytest.mark.django_db
@pytest.mark.parametrize('metodo,url', ENDPOINTS_SEM_TOKEN)
def test_endpoints_rejeitam_sem_token(api_client, metodo, url):
    resposta = getattr(api_client, metodo)(url)
    assert resposta.status_code == 401, resposta.content


@pytest.mark.django_db
def test_upload_requer_autenticacao(api_client):
    from tests.conftest import enviar_csv

    resposta = enviar_csv(api_client, b'sku;ean\n')
    assert resposta.status_code == 401


@pytest.mark.django_db
def test_fluxo_token_e_usuario_logado(api_client, user):
    resposta = api_client.post(
        '/api/auth/token/',
        {'username': 'pricing', 'password': 'senha-forte-123'},
        format='json',
    )
    assert resposta.status_code == 200
    assert 'access' in resposta.json()

    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {resposta.json()['access']}")
    me = api_client.get('/api/auth/me/')
    assert me.status_code == 200
    assert me.json()['username'] == 'pricing'

    refresh = api_client.post(
        '/api/auth/token/refresh/',
        {'refresh': resposta.json()['refresh']},
        format='json',
    )
    assert refresh.status_code == 200
    assert 'access' in refresh.json()


@pytest.mark.django_db
def test_token_senha_errada(api_client, user):
    resposta = api_client.post(
        '/api/auth/token/',
        {'username': 'pricing', 'password': 'senha-errada'},
        format='json',
    )
    assert resposta.status_code == 401