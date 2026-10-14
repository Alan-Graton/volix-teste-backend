from rest_framework import serializers

from .models import Preco


class PrecoVigenteSerializer(serializers.ModelSerializer):
    """Formato de ``GET /api/precos/`` (preço vigente por vendedor)."""

    sku = serializers.CharField(source='produto.sku')
    produto = serializers.CharField(source='produto.nome')
    ean = serializers.CharField(source='produto.ean', default=None, allow_null=True)
    vendedor = serializers.CharField(source='vendedor.nome')

    class Meta:
        model = Preco
        fields = [
            'sku',
            'produto',
            'ean',
            'vendedor',
            'uf',
            'preco',
            'preco_promocional',
            'moeda',
            'estoque',
            'coletado_em',
        ]


class ReferenciaSerializer(serializers.Serializer):
    """Formato de ``GET /api/produtos/{sku}/referencia/``."""

    sku = serializers.CharField()
    produto = serializers.CharField()
    moeda = serializers.CharField()
    preco_referencia = serializers.DecimalField(max_digits=12, decimal_places=2)
    aliquota_icms = serializers.DecimalField(max_digits=4, decimal_places=2)
    valor_icms = serializers.DecimalField(max_digits=12, decimal_places=2)
    preco_liquido_icms = serializers.DecimalField(max_digits=12, decimal_places=2)
    vendedores_considerados = serializers.IntegerField()
    uf = serializers.CharField(allow_null=True)
    criterio = serializers.CharField()