"""Regras de consulta de preços (referência de mercado e ICMS).

Funções puras e determinísticas, testáveis isoladamente — nenhuma
dependência de CSV ou IA.
"""
from __future__ import annotations

from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import QuerySet

#: Alíquota de ICMS usada pelo time de precificação (definida no enunciado).
ALIQUOTA_ICMS = Decimal('0.18')

_CENTAVOS = Decimal('0.01')


def arredondar_centavos(valor: Decimal) -> Decimal:
    """Arredonda para 2 casas (meio para cima), padrão monetário BRL."""
    return valor.quantize(_CENTAVOS, rounding=ROUND_HALF_UP)


def calcular_preco_referencia(precos: Iterable[Decimal]) -> Decimal:
    """Preço de referência de mercado = mediana dos preços vigentes.

    Mediana (e não média) porque é robusta a outliers — um concorrente com
    preço atípico não distorce a referência. Com quantidade par de valores,
    a mediana é a média dos dois valores centrais (``statistics.median``).
    """
    from statistics import median

    valores = list(precos)
    if not valores:
        raise ValueError('É necessário ao menos um preço para calcular a referência.')
    return arredondar_centavos(median(valores))


def calcular_preco_liquido_icms(preco: Decimal) -> tuple[Decimal, Decimal]:
    """Devolve ``(preço líquido, valor de ICMS)`` considerando alíquota de 18%.

    Premissa registrada no README: o preço de mercado JÁ INCLUI o ICMS,
    logo o líquido é ``preco / (1 + 0.18)``.
    """
    liquido = arredondar_centavos(preco / (Decimal('1') + ALIQUOTA_ICMS))
    icms = arredondar_centavos(preco - liquido)
    return liquido, icms


def precos_vigentes_do_produto(produto, uf: str | None = None) -> QuerySet:
    """QuerySet dos preços vigentes do produto, opcionalmente filtrados por UF."""
    qs = produto.precos.filter(is_vigente=True).select_related('vendedor')
    if uf:
        qs = qs.filter(uf=uf)
    return qs