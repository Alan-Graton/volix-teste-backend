"""Endpoints de consulta de preços.

- ``GET /api/precos/?sku=&uf=&vendedor=``: lista paginada do preço vigente;
- ``GET /api/produtos/{sku}/referencia/``: preço de referência de mercado e
  preço líquido de ICMS (alíquota de 18%).
"""
import re

from django.http import Http404
from rest_framework import generics, status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from data.normalizers import normalizar_vendedor

from . import services
from .models import Preco, Produto
from .serializers import PrecoVigenteSerializer, ReferenciaSerializer

_RE_UF = re.compile(r'^[A-Za-z]{2}$')


def _uf_param(valor: str, campo: str = 'uf') -> str:
    """Normaliza/valida o parâmetro de UF (formato 2 letras; caixa normalizada)."""
    valor = valor.strip()
    if not _RE_UF.fullmatch(valor):
        raise ValidationError({campo: f'UF inválida: {valor!r}. Use 2 letras (ex.: SP).'})
    return valor.upper()


def _filtrar_por_vendedor(queryset, valor: str):
    """Filtro por vendedor: nome exato (caixa-insensitive) OU chave normalizada."""
    from django.db.models import Q

    valor = valor.strip()
    if not valor:
        return queryset
    return queryset.filter(
        Q(vendedor__nome__iexact=valor)
        | Q(vendedor__nome_normalizado=normalizar_vendedor(valor))
    )


class PrecoVigenteListView(generics.ListAPIView):
    """Lista paginada do preço vigente, com filtros opcionais sku/uf/vendedor."""

    serializer_class = PrecoVigenteSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        params = self.request.query_params
        queryset = (
            Preco.objects.filter(is_vigente=True)
            .select_related('produto', 'vendedor')
            .order_by('produto__sku', 'vendedor__nome', '-coletado_em')
        )

        sku = params.get('sku', '').strip()
        if sku:
            queryset = queryset.filter(produto__sku__iexact=sku)

        uf = params.get('uf', '').strip()
        if uf:
            queryset = queryset.filter(uf=_uf_param(uf))

        vendedor = params.get('vendedor', '').strip()
        if vendedor:
            queryset = _filtrar_por_vendedor(queryset, vendedor)

        return queryset


class ProdutoReferenciaView(APIView):
    """Referência de mercado do produto + preço líquido de ICMS (18%).

    Premissas (registradas no README):
    - referência = mediana dos preços vigentes do produto;
    - parâmetro opcional ``?uf=`` restringe a UF considerada;
    - o preço de mercado já inclui ICMS, logo líquido = preço / 1.18.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, sku: str):
        sku = sku.strip()
        try:
            produto = Produto.objects.get(sku__iexact=sku)
        except Produto.DoesNotExist:
            raise Http404(f'Produto com SKU {sku!r} não encontrado.')

        uf_param = request.query_params.get('uf', '').strip()
        uf = _uf_param(uf_param) if uf_param else None

        queryset = services.precos_vigentes_do_produto(produto, uf=uf)
        precos = [item.preco for item in queryset]
        if not precos:
            detalhe = f'Sem preço vigente para o SKU {produto.sku}'
            detalhe += f' na UF {uf}.' if uf else '.'
            raise Http404(detalhe)

        preco_referencia = services.calcular_preco_referencia(precos)
        preco_liquido, valor_icms = services.calcular_preco_liquido_icms(preco_referencia)

        dados = {
            'sku': produto.sku,
            'produto': produto.nome,
            'moeda': 'BRL',
            'preco_referencia': preco_referencia,
            'aliquota_icms': services.ALIQUOTA_ICMS,
            'valor_icms': valor_icms,
            'preco_liquido_icms': preco_liquido,
            'vendedores_considerados': len(precos),
            'uf': uf,
            'criterio': 'mediana dos preços vigentes',
        }
        return Response(ReferenciaSerializer(dados).data, status=status.HTTP_200_OK)