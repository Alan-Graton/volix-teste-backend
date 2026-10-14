"""Conversão CSV -> JSON (data.parsers, camada de leitura com pandas).

Estes testes cobrem SOMENTE a conversão estrutural. As regras de validação e
normalização do conteúdo são testadas em ``test_validators.py`` e
``test_normalizers.py``.
"""
import json
from pathlib import Path

import pytest

from data.exceptions import ArquivoInvalido
from data.parsers import carregar_records, csv_para_json, iterar_linhas

pytestmark = pytest.mark.django_db


@pytest.fixture
def csv_real(settings):
    caminho = Path(settings.BASE_DIR) / 'dados' / 'precos_concorrentes.csv'
    return caminho


def test_le_todas_as_linhas_do_csv_real(csv_real):
    registros = carregar_records(csv_real)
    assert len(registros) == 321


def test_chaves_dos_registros_sao_o_cabecalho_mais_extras(csv_real):
    registros = carregar_records(csv_real)
    esperado = [
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
        '_extras',
    ]
    assert list(registros[0].keys()) == esperado


def test_primeira_linha_conteudo_bruto(csv_real):
    registros = carregar_records(csv_real)
    primeira = registros[0]
    assert primeira['sku'] == 'SKU-1011'
    assert primeira['produto'] == 'Notebook 15" 8GB'  # aspas escapadas resolvidas
    assert primeira['vendedor'] == 'Carrefour'
    assert primeira['preco'] == '3.169,98'  # valor cheio, sem interpretação
    assert primeira['coletado_em'] == '04/03/2025 13:41'


def test_linha_truncada_e_lida_com_campos_vazios(csv_real):
    registros = carregar_records(csv_real)
    # linha de dados 320 (penúltima): só 4 campos no arquivo
    truncada = registros[319]
    assert truncada['sku'] == 'SKU-1001'
    assert truncada['produto'] == 'Linha truncada'
    assert truncada['ean'] == '7890001370000'
    assert truncada['vendedor'] == ''
    assert truncada['preco'] == ''
    assert truncada['coletado_em'] == ''


def test_coluna_extra_e_preservada(csv_real):
    registros = carregar_records(csv_real)
    ultima = registros[320]
    assert ultima['sku'] == 'SKU-1002'
    assert ultima['_extras'] == 'coluna-extra'
    # linhas sem extras ficam com a chave presente e vazia
    assert registros[0]['_extras'] == ''


def test_linha_com_aspas_embutidas(csv_real):
    registros = carregar_records(csv_real)
    # dados 162: "Fone ""Pro""; edição limitada"
    linha = registros[161]
    assert linha['produto'] == 'Fone "Pro"; edição limitada'
    assert linha['vendedor'] == 'Mercado Livre'


def test_iterar_linhas_numeracao_1_based(csv_real):
    linhas = list(iterar_linhas(csv_real))
    assert len(linhas) == 321
    assert linhas[0][0] == 1
    assert linhas[-1][0] == 321
    assert linhas[0][1]['sku'] == 'SKU-1011'


def test_csv_para_json_roundtrip(csv_real):
    texto = json.loads(csv_para_json(csv_real))
    assert isinstance(texto, list)
    assert len(texto) == 321
    assert texto[0]['sku'] == 'SKU-1011'
    # JSON válido de verdade (sem NaN solto)
    assert 'NaN' not in json.dumps(texto, allow_nan=False)


def test_cabecalho_com_coluna_ausente_erro(tmp_path):
    arquivo = tmp_path / 'sem-preco.csv'
    arquivo.write_text('sku;ean;produto\nSKU-1;1;P\n', encoding='utf-8')
    with pytest.raises(ArquivoInvalido) as capturado:
        carregar_records(arquivo)
    assert 'preco' in str(capturado.value)
    assert 'colunas obrigatórias' in str(capturado.value)


def test_arquivo_vazio_erro(tmp_path):
    arquivo = tmp_path / 'vazio.csv'
    arquivo.write_text('', encoding='utf-8')
    with pytest.raises(ArquivoInvalido):
        carregar_records(arquivo)


def test_apenas_cabecalho_erro(tmp_path):
    arquivo = tmp_path / 'só-cabecalho.csv'
    arquivo.write_text(
        'sku;ean;produto;vendedor;uf;preco;preco_promocional;moeda;estoque;coletado_em;embalagem\n',
        encoding='utf-8',
    )
    with pytest.raises(ArquivoInvalido) as capturado:
        carregar_records(arquivo)
    assert 'sem linhas de dados' in str(capturado.value)


def test_arquivo_codificacao_invalida_erro(tmp_path):
    arquivo = tmp_path / 'binario.csv'
    arquivo.write_bytes(b'\xff\xfe\x00\x01\x02arquivo n\xe3o utf-8')
    with pytest.raises(ArquivoInvalido) as capturado:
        carregar_records(arquivo)
    assert 'UTF-8' in str(capturado.value)


def test_csv_com_dados_simples(tmp_path):
    arquivo = tmp_path / 'simples.csv'
    arquivo.write_text(
        'sku;ean;produto;vendedor;uf;preco;preco_promocional;moeda;estoque;coletado_em;embalagem\n'
        'SKU-1;789;P;V;SP;10.50;;BRL;3;2025-03-10T10:00:00-03:00;1\n',
        encoding='utf-8',
    )
    registros = carregar_records(arquivo)
    assert registros == [
        {
            'sku': 'SKU-1',
            'ean': '789',
            'produto': 'P',
            'vendedor': 'V',
            'uf': 'SP',
            'preco': '10.50',
            'preco_promocional': '',
            'moeda': 'BRL',
            'estoque': '3',
            'coletado_em': '2025-03-10T10:00:00-03:00',
            'embalagem': '1',
            '_extras': '',
        }
    ]