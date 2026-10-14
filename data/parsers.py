
from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pandas as pd

from .exceptions import ArquivoInvalido

SEPARADOR = ';'
ENCODING = 'utf-8-sig'
CHAVE_EXTRAS = '_extras'

COLUNAS_ESPERADAS = [
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


def carregar_records(caminho: str | Path) -> list[dict[str, str]]:
    """Lê o CSV e devolve uma lista de registros (dicts) JSON-áveis."""
    caminho = Path(caminho)
    try:
        cabecalho = pd.read_csv(
            caminho,
            sep=SEPARADOR,
            nrows=0,
            dtype=str,
            keep_default_na=False,
            encoding=ENCODING,
        ).columns.tolist()
    except pd.errors.EmptyDataError as exc:
        raise ArquivoInvalido('Arquivo CSV vazio (sem cabeçalho).') from exc
    except pd.errors.ParserError as exc:
        raise ArquivoInvalido(f'Cabeçalho ilegível: {exc}.') from exc
    except UnicodeDecodeError as exc:
        raise ArquivoInvalido(
            'Falha ao decodificar o arquivo; use codificação UTF-8.'
        ) from exc
    except OSError as exc:
        raise ArquivoInvalido(f'Não foi possível ler o arquivo: {exc}.') from exc

    faltantes = [coluna for coluna in COLUNAS_ESPERADAS if coluna not in cabecalho]
    if faltantes:
        raise ArquivoInvalido(
            'Cabeçalho sem as colunas obrigatórias: ' + ', '.join(faltantes) + '.'
        )

    # +1 coluna de folga: linhas com campo além do cabeçalho não quebram a
    # leitura (o excedente vai para CHAVE_EXTRAS).
    nomes = list(cabecalho) + [CHAVE_EXTRAS]
    try:
        df = pd.read_csv(
            caminho,
            sep=SEPARADOR,
            header=None,
            names=nomes,
            dtype=str,
            keep_default_na=False,
            encoding=ENCODING,
        )
    except pd.errors.EmptyDataError as exc:
        raise ArquivoInvalido('Arquivo CSV vazio (sem cabeçalho).') from exc
    except pd.errors.ParserError as exc:
        raise ArquivoInvalido(f'Linha com número de campos inesperado: {exc}.') from exc
    except UnicodeDecodeError as exc:
        raise ArquivoInvalido(
            'Falha ao decodificar o arquivo; use codificação UTF-8.'
        ) from exc

    if len(df) <= 1:
        raise ArquivoInvalido('Arquivo CSV sem linhas de dados.')

    # A primeira linha lida (header=None) é o próprio cabeçalho.
    dados = df.iloc[1:]
    return [
        {str(chave): ('' if valor is None else str(valor)) for chave, valor in registro.items()}
        for registro in dados.to_dict(orient='records')
    ]


def csv_para_json(caminho: str | Path) -> str:
    """Converte o CSV inteiro em uma string JSON (registros por linha)."""
    return json.dumps(carregar_records(caminho), ensure_ascii=False)


def iterar_linhas(caminho: str | Path) -> Iterator[tuple[int, dict[str, str]]]:
    """Itera os registros: ``(numero_linha, registro)``, linha de dados 1-based."""
    for numero_linha, registro in enumerate(carregar_records(caminho), start=1):
        yield numero_linha, registro