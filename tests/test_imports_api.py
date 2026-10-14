"""Endpoints de importação: upload assíncrono, andamento e falhas."""
import time

import pytest
from django.test import TestCase

from apps.imports import services
from apps.imports.models import Importacao, ImportacaoLinha

from .conftest import csv_padrao, enviar_csv, montar_csv

pytestmark = pytest.mark.django_db


def _refrescar(importacao) -> Importacao:
    importacao.refresh_from_db()
    return importacao


# --------------------------------------------------------------------------- #
# validação estrutural do upload
# --------------------------------------------------------------------------- #


def test_upload_sem_arquivo(auth_client):
    resposta = auth_client.post('/api/importacoes/', {}, format='multipart')
    assert resposta.status_code == 400
    assert 'arquivo' in resposta.json()


def test_upload_extensao_diferente_de_csv(auth_client):
    from django.core.files.uploadedfile import SimpleUploadedFile

    arquivo = SimpleUploadedFile('dados.txt', b'a;b\n1;2\n', content_type='text/plain')
    resposta = auth_client.post('/api/importacoes/', {'arquivo': arquivo}, format='multipart')
    assert resposta.status_code == 400
    assert '.csv' in str(resposta.json())


def test_upload_acima_do_limite_retorna_413(auth_client, monkeypatch):
    monkeypatch.setattr(services, 'TAMANHO_MAXIMO_BYTES', 10)
    resposta = enviar_csv(auth_client, b'sku;ean;produto\n' + b'x' * 100)
    assert resposta.status_code == 413


def test_upload_arquivo_vazio(auth_client):
    from django.core.files.uploadedfile import SimpleUploadedFile

    arquivo = SimpleUploadedFile('vazio.csv', b'', content_type='text/csv')
    resposta = auth_client.post('/api/importacoes/', {'arquivo': arquivo}, format='multipart')
    assert resposta.status_code == 400


# --------------------------------------------------------------------------- #
# requisito: resposta imediata (até 2s) independentemente do tamanho
# --------------------------------------------------------------------------- #


def test_upload_do_csv_real_responde_em_ate_2s(auth_client, csv_real, sem_despacho):
    inicio = time.perf_counter()
    resposta = enviar_csv(auth_client, csv_real, nome='precos_concorrentes.csv')
    duracao = time.perf_counter() - inicio

    assert resposta.status_code == 202
    assert duracao < 2.0, f'upload levou {duracao:.2f}s'
    assert resposta.json()['status'] == Importacao.Status.PENDENTE
    assert resposta.json()['duplicado'] is False
    # o processamento foi apenas agendado, não executado
    assert ImportacaoLinha.objects.count() == 0


def test_despacho_e_agendado_apos_commit(auth_client):
    with TestCase.captureOnCommitCallbacks(execute=True) as callbacks:
        resposta = enviar_csv(auth_client, csv_padrao())
    assert resposta.status_code == 202
    assert len(callbacks) == 1


# --------------------------------------------------------------------------- #
# processamento de ponta a ponta (com dublê de tratamento)
# --------------------------------------------------------------------------- #


def test_importacao_conclui_e_persiste_linhas(auth_client, tratamento_duble):
    with TestCase.captureOnCommitCallbacks(execute=True):
        resposta = enviar_csv(auth_client, csv_padrao(3))

    assert resposta.status_code == 202
    importacao = _refrescar(Importacao.objects.get(pk=resposta.json()['id']))
    assert importacao.status == Importacao.Status.CONCLUIDA
    assert importacao.total_linhas == 3
    assert importacao.processadas == 3
    assert importacao.quarentena_count == 0
    assert importacao.duplicadas_count == 0
    assert importacao.finalizada_em is not None

    assert ImportacaoLinha.objects.filter(importacao=importacao).count() == 3
    assert importacao.precos.count() == 3


def test_linhas_ruins_vao_para_quarentena_com_motivo(auth_client, tratamento_duble):
    conteudo = montar_csv(
        [
            {  # válida
                'sku': 'SKU-3001',
                'ean': '7890001000001',
                'produto': 'Produto Ok',
                'vendedor': 'Carrefour',
                'uf': 'SP',
                'preco': '10.50',
                'moeda': 'BRL',
                'estoque': '5',
                'coletado_em': '2025-03-10T10:00:00-03:00',
                'embalagem': '1',
            },
            {  # preço ausente
                'sku': 'SKU-3002',
                'produto': 'Sem Preço',
                'vendedor': 'Carrefour',
                'uf': 'SP',
                'coletado_em': '2025-03-10T10:00:00-03:00',
            },
            {  # UF inválida + moeda USD
                'sku': 'SKU-3003',
                'produto': 'Outro',
                'vendedor': 'Carrefour',
                'uf': 'XX',
                'preco': '9.90',
                'moeda': 'USD',
                'coletado_em': '2025-03-10T10:00:00-03:00',
            },
            {  # data impossível
                'sku': 'SKU-3004',
                'produto': 'Data Ruim',
                'vendedor': 'Carrefour',
                'uf': 'SP',
                'preco': '9.90',
                'moeda': 'BRL',
                'coletado_em': '2025-02-30T10:00:00-03:00',
            },
        ]
    )
    with TestCase.captureOnCommitCallbacks(execute=True):
        resposta = enviar_csv(auth_client, conteudo)

    importacao = _refrescar(Importacao.objects.get(pk=resposta.json()['id']))
    assert importacao.status == Importacao.Status.CONCLUIDA
    assert importacao.total_linhas == 4
    assert importacao.processadas == 1
    assert importacao.quarentena_count == 3

    quarentena = importacao.linhas.filter(status=ImportacaoLinha.Status.QUARENTENA)
    assert quarentena.count() == 3
    linha_preco = quarentena.get(numero_linha=2)
    assert 'Preço ausente' in linha_preco.motivos
    assert linha_preco.dados_originais['sku'] == 'SKU-3002'

    linha_uf = quarentena.get(numero_linha=3)
    assert any('UF inválida' in motivo for motivo in linha_uf.motivos)
    assert any('Moeda' in motivo for motivo in linha_uf.motivos)

    # nenhuma linha descartada em silêncio: total = soma dos estados
    assert importacao.linhas.count() == importacao.total_linhas
    assert (
        importacao.processadas
        + importacao.quarentena_count
        + importacao.duplicadas_count
        == importacao.total_linhas
    )


def test_csv_real_importa_completo_sem_perder_linhas(
    auth_client, csv_real, tratamento_duble
):
    """Com o CSV real: toda linha é lida e classificada (nenhuma sumida)."""
    with TestCase.captureOnCommitCallbacks(execute=True):
        resposta = enviar_csv(auth_client, csv_real, nome='precos_concorrentes.csv')

    importacao = _refrescar(Importacao.objects.get(pk=resposta.json()['id']))
    assert importacao.status == Importacao.Status.CONCLUIDA
    assert importacao.total_linhas == 321
    assert importacao.linhas.count() == 321
    assert (
        importacao.processadas
        + importacao.quarentena_count
        + importacao.duplicadas_count
        == 321
    )
    # o dublê é propositalmente rígido: boa parte do CSV real cai em quarentena
    assert importacao.quarentena_count > 0
    assert importacao.processadas > 0


# --------------------------------------------------------------------------- #
# falhas
# --------------------------------------------------------------------------- #


def test_arquivo_com_cabecalho_invalido_falha_com_mensagem(auth_client):
    conteudo = b'sku;ean;produto\nSKU-1;x;P\n'
    with TestCase.captureOnCommitCallbacks(execute=True):
        resposta = enviar_csv(auth_client, conteudo)

    importacao = _refrescar(Importacao.objects.get(pk=resposta.json()['id']))
    assert importacao.status == Importacao.Status.FALHOU
    assert 'colunas obrigatórias' in importacao.erro
    assert importacao.finalizada_em is not None


def test_erro_inesperado_marca_falhou(auth_client, monkeypatch):
    def estoura(bruta):
        raise RuntimeError('boom')

    monkeypatch.setattr(services, 'processar_linha', estoura)
    with TestCase.captureOnCommitCallbacks(execute=True):
        resposta = enviar_csv(auth_client, csv_padrao())

    importacao = _refrescar(Importacao.objects.get(pk=resposta.json()['id']))
    assert importacao.status == Importacao.Status.FALHOU
    assert 'Erro inesperado' in importacao.erro
    assert 'boom' not in importacao.erro  # detalhe técnico fica no log, não na API


# --------------------------------------------------------------------------- #
# consulta de andamento/resultado
# --------------------------------------------------------------------------- #


def test_detalhe_da_importacao(auth_client, tratamento_duble):
    with TestCase.captureOnCommitCallbacks(execute=True):
        resposta = enviar_csv(auth_client, csv_padrao(2))
    importacao_id = resposta.json()['id']

    detalhe = auth_client.get(f'/api/importacoes/{importacao_id}/')
    assert detalhe.status_code == 200
    dados = detalhe.json()
    assert dados['status'] == Importacao.Status.CONCLUIDA
    assert dados['total_linhas'] == 2
    assert dados['processadas'] == 2
    assert dados['quarentena_count'] == 0
    assert dados['quarentena_url'].endswith(
        f'/api/importacoes/{importacao_id}/quarentena/'
    )


def test_detalhe_inexistente_retorna_404(auth_client):
    resposta = auth_client.get('/api/importacoes/99999/')
    assert resposta.status_code == 404


def test_lista_importacoes_paginada(auth_client):
    for i in range(25):
        Importacao.objects.create(
            nome_arquivo_original=f'a{i}.csv', arquivo_sha256=f'{i:064d}'
        )

    resposta = auth_client.get('/api/importacoes/')
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo['count'] == 25
    assert len(corpo['results']) == 20

    pagina2 = auth_client.get('/api/importacoes/?page=2')
    assert pagina2.status_code == 200
    assert len(pagina2.json()['results']) == 5