from django.db import models


class Produto(models.Model):
    """Produto do catálogo interno, identificado pelo SKU do concorrente.

    O EAN é opcional no modelo: linhas sem EAN aproveitáveis mantêm o EAN já
    cadastrado; EAN divergente para o mesmo SKU rejeita a linha na importação
    (regra do serviço de importação).
    """

    sku = models.CharField(max_length=50, unique=True, db_index=True)
    ean = models.CharField(max_length=14, null=True, blank=True, db_index=True)
    nome = models.CharField(max_length=255)
    embalagem = models.PositiveIntegerField(default=1)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['sku']
        verbose_name = 'produto'
        verbose_name_plural = 'produtos'

    def __str__(self) -> str:
        return f'{self.sku} — {self.nome}'


class Vendedor(models.Model):
    """Vendedor/concorrente. Identidade pela chave normalizada (deduplicação)."""

    nome = models.CharField(max_length=100)
    nome_normalizado = models.CharField(max_length=100, unique=True, db_index=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['nome']
        verbose_name = 'vendedor'
        verbose_name_plural = 'vendedores'

    def __str__(self) -> str:
        return self.nome


class Preco(models.Model):
    """Histórico de preços coletados (uma linha do CSV = um registro aqui).

    Nunca é atualizado in place: cada coleta gera um registro, permitindo
    histórico completo e consulta do vigente (``is_vigente=True``, o da
    última coleta por produto+vendedor+UF).
    """

    produto = models.ForeignKey(Produto, on_delete=models.CASCADE, related_name='precos')
    vendedor = models.ForeignKey(Vendedor, on_delete=models.CASCADE, related_name='precos')
    uf = models.CharField(max_length=2)
    preco = models.DecimalField(max_digits=12, decimal_places=2)
    preco_promocional = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    moeda = models.CharField(max_length=3, default='BRL')
    estoque = models.IntegerField(null=True, blank=True)
    coletado_em = models.DateTimeField()
    importacao = models.ForeignKey(
        'imports.Importacao', on_delete=models.CASCADE, related_name='precos'
    )
    is_vigente = models.BooleanField(default=False, db_index=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-coletado_em', 'produto__sku']
        constraints = [
            models.UniqueConstraint(
                fields=['produto', 'vendedor', 'uf', 'coletado_em'],
                name='unica_coleta_por_vendedor',
            )
        ]
        indexes = [
            models.Index(
                fields=['produto', 'vendedor', 'uf', '-coletado_em'],
                name='idx_coleta_vigente',
            ),
            models.Index(fields=['uf', 'is_vigente'], name='idx_uf_vigente'),
        ]
        verbose_name = 'preço'
        verbose_name_plural = 'preços'

    def __str__(self) -> str:
        return f'{self.produto_id} @ {self.vendedor_id}/{self.uf}: {self.preco}'