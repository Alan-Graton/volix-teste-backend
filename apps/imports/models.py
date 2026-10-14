import uuid
from pathlib import Path

from django.conf import settings
from django.db import models


def caminho_importacao(instance, filename: str) -> str:
    """Guarda o upload com nome aleatório (evita colisão e travessia de caminho)."""
    extensao = Path(filename).suffix.lower()
    if not extensao or len(extensao) > 10:
        extensao = '.csv'
    return f'importacoes/{uuid.uuid4().hex}{extensao}'


class Importacao(models.Model):
    """Uma tentativa de importação de um arquivo CSV (upload -> processamento assíncrono)."""

    class Status(models.TextChoices):
        PENDENTE = 'pendente', 'Pendente'
        PROCESSANDO = 'processando', 'Processando'
        CONCLUIDA = 'concluida', 'Concluída'
        FALHOU = 'falhou', 'Falhou'

    arquivo = models.FileField(upload_to=caminho_importacao, max_length=500)
    nome_arquivo_original = models.CharField(max_length=255, blank=True)
    arquivo_sha256 = models.CharField(max_length=64, db_index=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDENTE,
        db_index=True,
    )
    total_linhas = models.PositiveIntegerField(default=0)
    processadas = models.PositiveIntegerField(default=0)
    quarentena_count = models.PositiveIntegerField(default=0)
    duplicadas_count = models.PositiveIntegerField(default=0)
    erro = models.TextField(blank=True)
    criada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='importacoes',
    )
    criada_em = models.DateTimeField(auto_now_add=True)
    finalizada_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-criada_em']
        verbose_name = 'importação'
        verbose_name_plural = 'importações'

    def __str__(self) -> str:
        return f'Importação #{self.pk} ({self.status})'

    @property
    def em_andamento(self) -> bool:
        return self.status in (self.Status.PENDENTE, self.Status.PROCESSANDO)


class ImportacaoLinha(models.Model):
    """Auditoria linha a linha de uma importação.

    Toda linha lida do arquivo vira um registro aqui — importada, em
    quarentena ou duplicada — para que nenhuma linha seja descartada em
    silêncio (requisito do enunciado).
    """

    class Status(models.TextChoices):
        IMPORTADA = 'importada', 'Importada'
        QUARENTENA = 'quarentena', 'Quarentena'
        DUPLICADA = 'duplicada', 'Duplicada'

    importacao = models.ForeignKey(
        Importacao, on_delete=models.CASCADE, related_name='linhas'
    )
    numero_linha = models.PositiveIntegerField()
    dados_originais = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, db_index=True)
    motivos = models.JSONField(default=list, blank=True)
    preco = models.ForeignKey(
        'products.Preco',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='linhas_importacao',
    )
    criada_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['numero_linha']
        constraints = [
            models.UniqueConstraint(
                fields=['importacao', 'numero_linha'],
                name='unica_linha_por_importacao',
            )
        ]
        indexes = [
            models.Index(fields=['importacao', 'status'], name='idx_linha_imp_status'),
        ]
        verbose_name = 'linha de importação'
        verbose_name_plural = 'linhas de importação'

    def __str__(self) -> str:
        return f'Linha {self.numero_linha} [{self.status}] (importação #{self.importacao_id})'