"""GET /api/importacoes/{id}/quarentena/: linhas rejeitadas e motivos."""
import pytest

from apps.imports.models import Importacao, ImportacaoLinha

pytestmark = pytest.mark.django_db


def _importacao():
    return Importacao.objects.create(nome_arquivo_original='dia-01.csv')


def _linha(importacao, numero, status, motivos=None, **dados):
    return ImportacaoLinha.objects.create(
        importacao=importacao,
        numero_linha=numero,
        status=status,
        motivos=motivos or [],
        dados_originais=dados or {'sku': f'SKU-{numero}'},
    )


def test_quarentena_lista_motivos_e_dados_originais(auth_client):
    importacao = _importacao()
    _linha(
        importacao,
        7,
        ImportacaoLinha.Status.QUARENTENA,
        motivos=['Preço ausente', 'UF inválida: XX'],
        sku='SKU-777',
        preco='',
        uf='XX',
    )

    resposta = auth_client.get(f'/api/importacoes/{importacao.pk}/quarentena/')
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo['count'] == 1
    item = corpo['results'][0]
    assert item['numero_linha'] == 7
    assert item['status'] == 'quarentena'
    assert item['motivos'] == ['Preço ausente', 'UF inválida: XX']
    assert item['dados_originais']['sku'] == 'SKU-777'
    assert item['criada_em']


def test_padrao_oculta_linhas_importadas(auth_client):
    importacao = _importacao()
    _linha(importacao, 1, ImportacaoLinha.Status.IMPORTADA)
    _linha(importacao, 2, ImportacaoLinha.Status.QUARENTENA, motivos=['X'])
    _linha(importacao, 3, ImportacaoLinha.Status.DUPLICADA, motivos=['Y'])

    resposta = auth_client.get(f'/api/importacoes/{importacao.pk}/quarentena/')
    dados = resposta.json()
    assert dados['count'] == 2
    statuses = {item['status'] for item in dados['results']}
    assert statuses == {'quarentena', 'duplicada'}


@pytest.mark.parametrize(
    'filtro,esperado',
    [
        ('quarentena', {'quarentena'}),
        ('duplicada', {'duplicada'}),
        ('importada', {'importada'}),
        ('todas', {'quarentena', 'duplicada', 'importada'}),
    ],
)
def test_filtro_por_status(auth_client, filtro, esperado):
    importacao = _importacao()
    _linha(importacao, 1, ImportacaoLinha.Status.IMPORTADA)
    _linha(importacao, 2, ImportacaoLinha.Status.QUARENTENA, motivos=['X'])
    _linha(importacao, 3, ImportacaoLinha.Status.DUPLICADA, motivos=['Y'])

    resposta = auth_client.get(
        f'/api/importacoes/{importacao.pk}/quarentena/?status={filtro}'
    )
    assert resposta.status_code == 200
    assert {item['status'] for item in resposta.json()['results']} == esperado


def test_filtro_status_invalido_retorna_400(auth_client):
    importacao = _importacao()
    resposta = auth_client.get(f'/api/importacoes/{importacao.pk}/quarentena/?status=x')
    assert resposta.status_code == 400
    assert 'status' in resposta.json()


def test_quarentena_paginada(auth_client):
    importacao = _importacao()
    for numero in range(1, 26):
        _linha(
            importacao,
            numero,
            ImportacaoLinha.Status.QUARENTENA,
            motivos=[f'Motivo {numero}'],
        )

    pagina1 = auth_client.get(f'/api/importacoes/{importacao.pk}/quarentena/')
    assert pagina1.json()['count'] == 25
    assert len(pagina1.json()['results']) == 20

    pagina2 = auth_client.get(f'/api/importacoes/{importacao.pk}/quarentena/?page=2')
    assert len(pagina2.json()['results']) == 5


def test_quarentena_importacao_inexistente_404(auth_client):
    resposta = auth_client.get('/api/importacoes/99999/quarentena/')
    assert resposta.status_code == 404


def test_quarentena_da_importacao_correta(auth_client):
    outra = _importacao()
    _linha(outra, 1, ImportacaoLinha.Status.QUARENTENA, motivos=['De outra'])

    importacao = _importacao()
    _linha(importacao, 1, ImportacaoLinha.Status.QUARENTENA, motivos=['Destino'])

    resposta = auth_client.get(f'/api/importacoes/{importacao.pk}/quarentena/')
    assert resposta.json()['count'] == 1
    assert resposta.json()['results'][0]['motivos'] == ['Destino']