"""Tarefas Celery da aplicação de importações."""
from celery import shared_task


@shared_task(name='imports.processar_importacao')
def processar_importacao_task(importacao_id: int) -> None:
    """Processa a importação em segundo plano (worker)."""
    from .services import processar_importacao

    processar_importacao(importacao_id)