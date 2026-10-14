"""Fixtures compartilhadas dos testes.

Observação sobre o tratamento do CSV: os testes usam um DUBLÊ de
``processar_linha`` (regras mínimas e determinísticas) para exercitar o
*pipeline* (persistência, deduplicação, vigência, quarentena). As regras
reais de validação/normalização são de responsabilidade de quem trata os
dados e têm seus próprios arquivos de teste (``test_validators.py`` e
``test_normalizers.py``, ainda pendentes).
"""
from __future__ import annotations

import csv
import io
from datetime import datetime
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.imports import services

CABECALHO = [
    'sku',
    'ean',
    'produto',
    'vendedor',
    'uf',
    'preco',
    'preco_promocional',
    'moeda',
    'estoque',
    'coletado_em',
    'embalagem',
]

UFS_BRASIL = {
    'AC', 'AL', 'AM', 'AP', 'BA', 'CE', 'DF', 'ES', 'GO', 'MA', 'MG', 'MS',
    'MT', 'PA', 'PB', 'PE', 'PI', 'PR', 'RJ', 'RN', 'RO', 'RR', 'RS', 'SC',
    'SE', 'SP', 'TO',
}


# --------------------------------------------------------------------------- #
# infra de teste
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def media_temporaria(settings, tmp_path):
    """Envia os uploads para um diretório temporário por teste."""
    settings.MEDIA_ROOT = str(tmp_path / 'media')
    yield


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def user(db, django_user_model):
    return django_user_model.objects.create_user(
        username='pricing', password='senha-forte-123', email='pricing@empresa.com'
    )


@pytest.fixture
def auth_client(api_client, user):
    token = str(RefreshToken.for_user(user).access_token)
    api_client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
    return api_client


@pytest.fixture
def sem_despacho(monkeypatch):
    """Impede o dispatch Celery (upload responde sem processar)."""
    chamadas = []
    monkeypatch.setattr(
        services, 'enviar_para_processamento', lambda imp: chamadas.append(imp.pk)
    )
    return chamadas


# --------------------------------------------------------------------------- #
# dublê do tratamento de dados (substitui data.normalizers.processar_linha)
# --------------------------------------------------------------------------- #


def _decimal(texto: str) -> Decimal:
    txt = texto.replace('R$', '').replace(' ', '')
    if ',' in txt:
        txt = txt.replace('.', '').replace(',', '.')
    return Decimal(txt)


def tratamento_falso(bruta: dict[str, str]):
    """Dublê de teste: valida/normaliza com regras mínimas.

    Regras (propositalmente simples, não são as regras do caso):
    - SKU, preço (> 0), UF (27 estados), data ISO obrigatórios;
    - moeda deve ser BRL; estoque/embalagem inteiros quando presentes.
    Qualquer outro campo é copiado com ``strip()``.
    """
    from data.exceptions import LinhaRejeitada
    from data.normalizers import LinhaNormalizada

    motivos: list[str] = []

    sku = (bruta.get('sku') or '').strip()
    if not sku:
        motivos.append('SKU ausente')

    texto_preco = (bruta.get('preco') or '').strip()
    preco = None
    if not texto_preco:
        motivos.append('Preço ausente')
    else:
        try:
            preco = _decimal(texto_preco)
            if preco <= 0:
                motivos.append(f'Preço não positivo: {texto_preco}')
        except Exception:
            motivos.append(f'Preço inválido: {texto_preco!r}')

    preco_promo = None
    texto_promo = (bruta.get('preco_promocional') or '').strip()
    if texto_promo:
        try:
            preco_promo = _decimal(texto_promo)
        except Exception:
            motivos.append(f'Promoção inválida: {texto_promo!r}')

    uf = (bruta.get('uf') or '').strip().upper()
    if uf not in UFS_BRASIL:
        motivos.append(f'UF inválida: {uf!r}')

    texto_data = (bruta.get('coletado_em') or '').strip()
    coletado_em = None
    if not texto_data:
        motivos.append('Data ausente')
    else:
        try:
            coletado_em = datetime.fromisoformat(texto_data)
        except ValueError:
            motivos.append(f'Data inválida: {texto_data!r}')

    moeda = (bruta.get('moeda') or '').strip()
    if moeda != 'BRL':
        motivos.append(f'Moeda não suportada: {moeda!r}')

    estoque = None
    texto_estoque = (bruta.get('estoque') or '').strip()
    if texto_estoque:
        try:
            estoque = int(texto_estoque)
        except ValueError:
            motivos.append(f'Estoque inválido: {texto_estoque!r}')

    embalagem = 1
    texto_embalagem = (bruta.get('embalagem') or '').strip()
    if texto_embalagem:
        try:
            embalagem = int(texto_embalagem)
        except ValueError:
            motivos.append(f'Embalagem inválida: {texto_embalagem!r}')

    vendedor = (bruta.get('vendedor') or '').strip()
    if not vendedor:
        motivos.append('Vendedor ausente')

    produto_nome = (bruta.get('produto') or '').strip()
    if not produto_nome:
        motivos.append('Nome do produto ausente')

    if motivos:
        raise LinhaRejeitada(motivos)

    return LinhaNormalizada(
        sku=sku,
        ean=(bruta.get('ean') or '').strip() or None,
        produto_nome=produto_nome,
        embalagem=embalagem,
        vendedor_nome=vendedor,
        vendedor_chave=vendedor.lower().replace(' ', ''),
        uf=uf.upper(),
        preco=preco,
        preco_promocional=preco_promo,
        moeda=moeda,
        estoque=estoque,
        coletado_em=coletado_em,
        dados_originais=dict(bruta),
    )


@pytest.fixture
def tratamento_duble(monkeypatch):
    """Instala o dublê de tratamento no serviço de importação."""
    monkeypatch.setattr(services, 'processar_linha', tratamento_falso)
    return tratamento_falso


# --------------------------------------------------------------------------- #
# montagem e envio de CSVs
# --------------------------------------------------------------------------- #


def montar_csv(linhas: list[dict]) -> bytes:
    """Gera um CSV (;) com o cabeçalho canônico e as linhas informadas."""
    buffer = io.StringIO()
    escritor = csv.DictWriter(buffer, fieldnames=CABECALHO, delimiter=';', restval='')
    escritor.writeheader()
    for linha in linhas:
        escritor.writerow({coluna: linha.get(coluna, '') for coluna in CABECALHO})
    return buffer.getvalue().encode('utf-8')


def csv_padrao(n: int = 3) -> bytes:
    """CSV sintético com linhas já em formato "limpo" (datas ISO, preços com ponto)."""
    linhas = []
    for i in range(1, n + 1):
        linhas.append(
            {
                'sku': f'SKU-2{i:03d}',
                'ean': f'789000100000{i}',
                'produto': f'Produto {i}',
                'vendedor': 'Carrefour' if i % 2 else 'Mercado Livre',
                'uf': 'SP',
                'preco': f'{10 + i}.50',
                'moeda': 'BRL',
                'estoque': str(10 + i),
                'coletado_em': f'2025-03-1{i}T10:00:00-03:00',
                'embalagem': '1',
            }
        )
    return montar_csv(linhas)


def enviar_csv(client, conteudo: bytes, nome: str = 'precos.csv'):
    """POST /api/importacoes/ com um CSV em memória."""
    arquivo = SimpleUploadedFile(nome, conteudo, content_type='text/csv')
    return client.post('/api/importacoes/', {'arquivo': arquivo}, format='multipart')


@pytest.fixture
def csv_real():
    from pathlib import Path

    from django.conf import settings

    caminho = Path(settings.BASE_DIR) / 'dados' / 'precos_concorrentes.csv'
    return caminho.read_bytes()