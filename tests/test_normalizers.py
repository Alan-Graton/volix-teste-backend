"""Testes das REGRAS DE NORMALIZAÇÃO do CSV — PENDENTES (implementação manual).

Arquivo reservado a quem trata os dados: implemente as regras de
``data.normalizers.processar_linha`` e ``normalizar_vendedor`` aqui.

Sugestão de cobertura (baseada nos problemas de dados do CSV real):
- preços pt-BR ("R$ 1.234,56"), en-US ("1234.56") e variações -> Decimal;
- datas: ISO com offset, "Z", DD/MM/YYYY, MM/DD/YYYY, YYYY-MM-DD -> datetime
  consciente de fuso (America/Sao_Paulo quando não houver offset);
- vendedor: caixa/espaços/acentos ("Casas Bahia" == "casasbahia");
- produto: caixa ("cafeteira elétrica" -> "Cafeteira Elétrica");
- uf: caixa ("sp" -> "SP");
- sku/ean: strip, caixa, EAN dígito-a-dígito ou None;
- LinhaRejeitada sempre com motivos claros (a API de quarentena os expõe).
"""
import pytest

pytestmark = pytest.mark.django_db


@pytest.mark.skip(
    reason='Implementar: data/normalizers.py ainda não foi implementado pelo responsável pelo CSV.'
)
def test_processar_linha_normaliza_formatos_br():
    from data.normalizers import processar_linha  # noqa: F401

    raise NotImplementedError


@pytest.mark.skip(
    reason='Implementar: data/normalizers.py ainda não foi implementado pelo responsável pelo CSV.'
)
def test_normalizar_vendedor_mesma_chave():
    from data.normalizers import normalizar_vendedor  # noqa: F401

    raise NotImplementedError