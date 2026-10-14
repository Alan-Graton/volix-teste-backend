"""Testes das REGRAS DE VALIDAÇÃO do CSV — PENDENTES (implementação manual).

Arquivo reservado a quem trata os dados: implemente as regras de
``data.validators.validar_linha`` aqui.

Sugestão de cobertura (baseada nos problemas de dados do CSV real):
- preços: ausentes, "Sob consulta", negativos, zero, não numéricos;
- promoção maior que o preço normal;
- estoque: "esgotado", negativo, não numérico;
- UFs fora dos 27 estados; moeda ≠ BRL;
- datas: mês/dia impossíveis (30/02), formato americano, data futura;
- SKU/EAN: ausentes, EAN fora do padrão GTIN-13, notação científica;
- segurança: tentativas de injeção (SQL/formula) nos campos de texto.

Cada rejeição deve virar um motivo específico em português — os testes de
quarentena (tests/test_imports_api.py) já garantem que motivos recebidos
são persistidos e expostos na API.
"""
import pytest

pytestmark = pytest.mark.django_db


@pytest.mark.skip(
    reason='Implementar: data/validators.py ainda não foi implementado pelo responsável pelo CSV.'
)
def test_validar_linha_rejeita_precos_ruins():
    from data.validators import validar_linha  # noqa: F401

    raise NotImplementedError


@pytest.mark.skip(
    reason='Implementar: data/validators.py ainda não foi implementado pelo responsável pelo CSV.'
)
def test_validar_linha_aceita_linha_correta():
    from data.validators import validar_linha  # noqa: F401

    raise NotImplementedError