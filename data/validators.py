"""Regras de validação do conteúdo do CSV (pandas + stdlib, sem IA).

``validar_linha(bruta)`` devolve a lista de motivos (em português) pelos quais
a linha deve ir para a quarentena; lista vazia significa linha aproveitável.
Os motivos são expostos sem processamento adicional pela API de quarentena.

As funções de interpretação (``preco_em_decimal``, ``data_em_datetime``,
``inteiro``...) são o espelho da validação: ``data.normalizers`` reaproveita
justamente essas conversões para montar a linha normalizada, garantindo que
validação e conversão nunca discordem (o que passou na validação sempre
converte, e o que não converte sempre é rejeitado).

pandas é usado nos dois pontos pedidos pelo caso: leitura de datas
(``pd.to_datetime`` com formato explícito) e gate de numéricos
(``pd.to_numeric(..., errors='coerce')``); o valor em si é ``Decimal``
(extraído da string canônica — dinheiro não passa por float).
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

import pandas as pd

from .parsers import CHAVE_EXTRAS

#: Fuso assumido quando a data do CSV não traz offset (premissa no README).
FUSO_PADRAO = 'America/Sao_Paulo'
TZ_PADRAO = ZoneInfo(FUSO_PADRAO)

#: Folga para coletas "no futuro" (absorve diferença de relógio/fuso).
TOLERANCIA_FUTURO = timedelta(days=1)

MOEDA_ACEITA = 'BRL'

#: Faixa de preço plausível para varejo brasileiro (rejeita ruído/extremos).
PRECO_MINIMO = Decimal('0.05')
PRECO_MAXIMO = Decimal('10000.00')

UFS_BRASIL = frozenset(
    {
        'AC', 'AL', 'AM', 'AP', 'BA', 'CE', 'DF', 'ES', 'GO', 'MA', 'MG', 'MS',
        'MT', 'PA', 'PB', 'PE', 'PI', 'PR', 'RJ', 'RN', 'RO', 'RR', 'RS', 'SC',
        'SE', 'SP', 'TO',
    }
)

#: Chaves (``normalizers.normalizar_vendedor``) dos concorrentes aceitos.
#: Whitelist é a barreira de segurança contra injeção em ``vendedor``.
VENDEDORES_ACEITOS = frozenset(
    {'amazonbr', 'carrefour', 'casasbahia', 'magazineluiza', 'mercadolivre'}
)

#: Início de fórmula de planilha (=HYPERLINK etc.) em campos de texto.
INICIO_FORMULA = ('=', '+', '@')

#: Formatos com barra: dia/mês primeiro (padrão do arquivo), com fallback
#: mês/dia para datas como "03/25/2025" (impossíveis em dia/mês).
FORMATOS_DATA_COM_BARRA = (
    '%d/%m/%Y %H:%M',
    '%m/%d/%Y %H:%M',
    '%d/%m/%Y',
    '%m/%d/%Y',
)

_RE_NUMERO = re.compile(r'^[+-]?[\d.,]+$')
_RE_EAN13 = re.compile(r'^\d{13}$')
_RE_RUPEES = re.compile(r'^R\$\s*', re.IGNORECASE)


def _texto(bruta: dict[str, str], campo: str) -> str:
    return str(bruta.get(campo) or '').strip()


# --------------------------------------------------------------------------- #
# interpretações reaproveitadas por data.normalizers
# --------------------------------------------------------------------------- #


def canonico_numero(texto: str) -> str | None:
    """Normaliza um valor numérico do CSV para a forma ``1234.56``.

    Formatos aceitos (os presentes no arquivo):
    - pt-BR: ``3.169,98``, ``23,74``, ``R$ 127,50`` — vírgula é o decimal;
    - en-US: ``1234.56``, ``1,234.56`` — ponto é o decimal;
    - só-ponto em grupos de 3 dígitos = milhar: ``1.299`` -> ``1299`` e
      ``1.234.567`` -> ``1234567``;
    - vários pontos com último grupo ≠ 3 dígitos: o último ponto é o decimal
      (``1.299.90`` -> ``1299.90``).

    Devolve ``None`` quando o texto não é numérico ("Sob consulta").
    """
    txt = str(texto).replace('\u00a0', ' ').strip()
    txt = _RE_RUPEES.sub('', txt).strip()
    if not txt or not _RE_NUMERO.fullmatch(txt):
        return None
    if ',' in txt and '.' in txt:
        if txt.rfind(',') > txt.rfind('.'):
            txt = txt.replace('.', '').replace(',', '.')
        else:
            txt = txt.replace(',', '')
    elif ',' in txt:
        txt = txt.replace(',', '.')
    else:
        partes = txt.split('.')
        if len(partes) > 1 and partes[0].lstrip('+-').isdigit() and all(
            parte.isdigit() and len(parte) == 3 for parte in partes[1:]
        ):
            txt = ''.join(partes)
        elif len(partes) > 1:
            txt = ''.join(partes[:-1]) + '.' + partes[-1]
    return txt


def preco_em_decimal(texto: str) -> Decimal | None:
    """Interpreta valor monetário do CSV. ``None`` quando não interpretável.

    A string canônica passa pelo gate do pandas (``pd.to_numeric``) e o valor
    final é ``Decimal`` — exatidão de 2 casas, sem ponto flutuante.
    """
    canonico = canonico_numero(texto)
    if canonico is None:
        return None
    if pd.isna(pd.to_numeric(canonico, errors='coerce')):
        return None
    try:
        return Decimal(canonico)
    except InvalidOperation:
        return None


def inteiro(texto: str) -> int | None:
    """Interpreta inteiro do CSV (aceita "10", "-3", "1.299"). ``None`` se não for."""
    canonico = canonico_numero(texto)
    if canonico is None or pd.isna(pd.to_numeric(canonico, errors='coerce')):
        return None
    try:
        valor = Decimal(canonico)
    except InvalidOperation:
        return None
    if valor != valor.to_integral_value():
        return None
    return int(valor)


def estoque_em_inteiro(texto: str) -> int | None:
    """``"esgotado"`` -> ``0``; vazio/não numérico -> ``None``; senão o inteiro."""
    txt = str(texto).strip()
    if not txt:
        return None
    if txt.casefold() == 'esgotado':
        return 0
    return inteiro(txt)


def data_em_datetime(texto: str) -> datetime | None:
    """Interpreta ``coletado_em`` como datetime consciente de fuso.

    - ISO com offset (``2025-03-16T09:44:00-03:00``) e ``Z``: instante
      preservado e convertido para America/Sao_Paulo;
    - ``DD/MM/YYYY HH:MM`` (padrão do arquivo) e ``MM/DD/YYYY HH:MM``
      (fallback, ex.: ``03/25/2025``) e ``YYYY-MM-DD``: sem fuso → America/
      Sao_Paulo;
    - data impossível (``30/02/2025``) ou texto não reconhecido → ``None``.
    """
    txt = str(texto).strip()
    if not txt:
        return None
    if '/' in txt:
        momento: pd.Timestamp | None = None
        for formato in FORMATOS_DATA_COM_BARRA:
            candidato = pd.to_datetime(txt, format=formato, errors='coerce')
            if not pd.isna(candidato):
                momento = candidato
                break
    else:
        momento = pd.to_datetime(txt, errors='coerce')
    if momento is None or pd.isna(momento):
        return None
    instante = momento.to_pydatetime()
    if instante.tzinfo is None:
        return instante.replace(tzinfo=TZ_PADRAO)
    return instante.astimezone(TZ_PADRAO)


def ean_digito_verificador_ok(ean: str) -> bool:
    """GTIN-13: 13 dígitos e dígito verificador correto (módulo 10, pesos 1/3)."""
    if not _RE_EAN13.fullmatch(ean):
        return False
    soma = sum(int(digito) * (3 if indice % 2 else 1) for indice, digito in enumerate(ean[:12]))
    return (10 - soma % 10) % 10 == int(ean[12])


# --------------------------------------------------------------------------- #
# validação linha a linha
# --------------------------------------------------------------------------- #


def validar_linha(bruta: dict[str, str]) -> list[str]:
    """Valida uma linha bruta e retorna os motivos de rejeição (pt-BR).

    Coleta todos os problemas da linha (não para no primeiro), para que a
    quarentena registre o diagnóstico completo de cada registro.
    """
    motivos: list[str] = []
    motivos += _validar_estrutura(bruta)
    motivos += _validar_sku(bruta)
    motivos += _validar_produto(bruta)
    motivos += _validar_vendedor(bruta)
    motivos += _validar_uf(bruta)
    motivos += _validar_moeda(bruta)
    motivos += _validar_precos(bruta)
    motivos += _validar_estoque(bruta)
    motivos += _validar_embalagem(bruta)
    motivos += _validar_data(bruta)
    motivos += _validar_ean(bruta)
    return motivos


def _validar_estrutura(bruta: dict[str, str]) -> list[str]:
    extras = _texto(bruta, CHAVE_EXTRAS)
    if extras:
        return [f'Coluna extra fora do cabeçalho esperado: {extras!r}']
    return []


def _validar_sku(bruta: dict[str, str]) -> list[str]:
    sku = _texto(bruta, 'sku')
    if not sku:
        return ['SKU ausente']
    if sku.startswith(INICIO_FORMULA):
        return [f'SKU com início de fórmula suspeita (=, + ou @): {sku!r}']
    return []


def _validar_produto(bruta: dict[str, str]) -> list[str]:
    nome = _texto(bruta, 'produto')
    if not nome:
        return ['Nome do produto ausente']
    if nome.startswith(INICIO_FORMULA):
        return [f'Nome do produto com início de fórmula suspeita (=, + ou @): {nome!r}']
    return []


def _validar_vendedor(bruta: dict[str, str]) -> list[str]:
    from .normalizers import normalizar_vendedor  # import tardio: evita ciclo

    nome = _texto(bruta, 'vendedor')
    if not nome:
        return ['Vendedor ausente']
    if normalizar_vendedor(nome) not in VENDEDORES_ACEITOS:
        return [f'Vendedor fora da lista de concorrentes aceitos: {nome!r}']
    return []


def _validar_uf(bruta: dict[str, str]) -> list[str]:
    uf = _texto(bruta, 'uf').upper()
    if not uf:
        return ['UF ausente']
    if uf not in UFS_BRASIL:
        return [f'UF inválida: {uf!r}']
    return []


def _validar_moeda(bruta: dict[str, str]) -> list[str]:
    moeda = _texto(bruta, 'moeda')
    if not moeda:
        return ['Moeda ausente']
    if moeda.upper() != MOEDA_ACEITA:
        return [f'Moeda não suportada: {moeda!r} (apenas {MOEDA_ACEITA})']
    return []


def _validar_precos(bruta: dict[str, str]) -> list[str]:
    motivos: list[str] = []

    texto_preco = _texto(bruta, 'preco')
    preco: Decimal | None = None
    if not texto_preco:
        motivos.append('Preço ausente')
    else:
        preco = preco_em_decimal(texto_preco)
        if preco is None:
            motivos.append(f'Preço inválido: {texto_preco!r}')
        elif preco <= 0:
            motivos.append(f'Preço não positivo: {texto_preco}')
        elif preco < PRECO_MINIMO or preco > PRECO_MAXIMO:
            motivos.append(
                f'Preço fora da faixa plausível de R$ 0,05 a R$ 10.000,00: {texto_preco}'
            )

    texto_promo = _texto(bruta, 'preco_promocional')
    if texto_promo:
        promocao = preco_em_decimal(texto_promo)
        if promocao is None:
            motivos.append(f'Promoção inválida: {texto_promo!r}')
        elif promocao <= 0:
            motivos.append(f'Promoção não positiva: {texto_promo}')
        elif preco is not None and preco > 0 and promocao > preco:
            motivos.append(f'Promoção ({texto_promo}) maior que o preço ({texto_preco})')

    return motivos


def _validar_estoque(bruta: dict[str, str]) -> list[str]:
    texto = _texto(bruta, 'estoque')
    if not texto or texto.casefold() == 'esgotado':
        return []
    valor = inteiro(texto)
    if valor is None:
        return [f'Estoque inválido: {texto!r}']
    if valor < 0:
        return [f'Estoque negativo: {texto}']
    return []


def _validar_embalagem(bruta: dict[str, str]) -> list[str]:
    texto = _texto(bruta, 'embalagem')
    if not texto:
        return []
    valor = inteiro(texto)
    if valor is None or valor < 1:
        return [f'Embalagem inválida: {texto!r} (esperado inteiro maior ou igual a 1)']
    return []


def _validar_data(bruta: dict[str, str]) -> list[str]:
    texto = _texto(bruta, 'coletado_em')
    if not texto:
        return ['Data de coleta ausente']
    momento = data_em_datetime(texto)
    if momento is None:
        return [f'Data de coleta inválida: {texto!r}']
    if momento > datetime.now(TZ_PADRAO) + TOLERANCIA_FUTURO:
        return [f'Data de coleta no futuro: {texto}']
    return []


def _validar_ean(bruta: dict[str, str]) -> list[str]:
    texto = _texto(bruta, 'ean')
    if not texto:
        return []
    if not _RE_EAN13.fullmatch(texto):
        return [f'EAN inválido: {texto!r} (esperado GTIN-13 com 13 dígitos)']
    if not ean_digito_verificador_ok(texto):
        return [f'EAN com dígito verificador incorreto: {texto}']
    return []
