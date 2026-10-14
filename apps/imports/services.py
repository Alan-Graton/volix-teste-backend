"""Orquestração do processamento de importações.

Esta camada NÃO trata o CSV: leitura, validação e normalização dos campos
ficam no pacote ``data/`` (implementação manual pendente). Aqui ficam as
regras de negócio do enunciado que não dependem do conteúdo das linhas:

- resposta imediata do upload (despacho assíncrono via Celery);
- idempotência: mesmo arquivo duas vezes não duplica dados;
- quarentena: toda linha rejeitada é registrada com motivo;
- vigência: o preço vigente é o da última coleta, por
  (produto, vendedor, uf);
- progresso visível em ``GET /api/importacoes/{id}/``.
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from django.db import IntegrityError, transaction
from django.utils import timezone

from data.exceptions import ArquivoInvalido, LinhaRejeitada
from data.normalizers import LinhaNormalizada, processar_linha
from data.parsers import iterar_linhas

from .models import Importacao, ImportacaoLinha

logger = logging.getLogger(__name__)

#: Limite do upload (requisito: resposta em até 2s; limite de segurança extra).
TAMANHO_MAXIMO_BYTES = 20 * 1024 * 1024  # 20 MiB

#: A cada N linhas lidas, os contadores são persistidos para mostrar andamento.
LOTE_PROGRESSO = 25

STATUS_LINHA = ImportacaoLinha.Status


def calcular_sha256(arquivo) -> str:
    """Hash SHA-256 do arquivo enviado (lê em blocos; devolve o ponteiro ao início)."""
    arquivo.seek(0)
    digesto = hashlib.sha256()
    for bloco in iter(lambda: arquivo.read(64 * 1024), b''):
        digesto.update(bloco)
    arquivo.seek(0)
    return digesto.hexdigest()


def importacao_anterior(sha256: str) -> Importacao | None:
    """Retorna importação anterior com o mesmo conteúdo, quando houver.

    Arquivo idêntico não é reprocessado (não duplica dados). Importações que
    ``falharam`` são ignoradas na checagem para permitir nova tentativa.
    """
    if not sha256:
        return None
    return (
        Importacao.objects.filter(arquivo_sha256=sha256)
        .exclude(status=Importacao.Status.FALHOU)
        .order_by('criada_em')
        .first()
    )


def enviar_para_processamento(importacao: Importacao) -> None:
    """Agenda o processamento em segundo plano após o commit da transação."""
    from .tasks import processar_importacao_task

    transaction.on_commit(lambda: processar_importacao_task.delay(importacao.pk))


def processar_importacao(importacao_id: int) -> None:
    """Processa uma importação inteira (executado pelo worker Celery).

    Linha a linha: ``data.normalizers.processar_linha`` decide se a linha é
    aproveitável (retorno) ou vai para a quarentena (``LinhaRejeitada``).
    Erros inesperados/ilegibilidade do arquivo marcam a importação como
    ``falhou`` com a mensagem em ``erro``.
    """
    importacao = _iniciar(importacao_id)
    if importacao is None:
        return

    caminho = Path(importacao.arquivo.path)
    try:
        for numero_linha, bruta in iterar_linhas(caminho):
            status_linha = _processar_uma_linha(importacao, numero_linha, bruta)
            _contar(importacao, status_linha)
        _finalizar(importacao, Importacao.Status.CONCLUIDA)
        logger.info(
            'Importação %s concluída: %s linhas (%s ok, %s quarentena, %s duplicadas)',
            importacao.pk,
            importacao.total_linhas,
            importacao.processadas,
            importacao.quarentena_count,
            importacao.duplicadas_count,
        )
    except ArquivoInvalido as exc:
        _falhar(importacao, str(exc))
    except OSError:
        _falhar(importacao, 'Arquivo de importação não encontrado ou ilegível.')
    except Exception:
        logger.exception('Falha inesperada na importação %s', importacao.pk)
        _falhar(importacao, 'Erro inesperado durante o processamento; veja os logs do servidor.')


def _iniciar(importacao_id: int) -> Importacao | None:
    """Muda pendente -> processando de forma atômica (evita processar 2x)."""
    with transaction.atomic():
        try:
            importacao = Importacao.objects.select_for_update().get(pk=importacao_id)
        except Importacao.DoesNotExist:
            logger.warning('Importação %s não encontrada para processamento', importacao_id)
            return None
        if importacao.status != Importacao.Status.PENDENTE:
            logger.info(
                'Importação %s ignorada: status atual %s', importacao_id, importacao.status
            )
            return None
        importacao.status = Importacao.Status.PROCESSANDO
        importacao.save(update_fields=['status'])
    return importacao


def _processar_uma_linha(
    importacao: Importacao, numero_linha: int, bruta: dict[str, str]
) -> str:
    """Executa o tratamento de uma linha e persiste o resultado (ou a quarentena)."""
    preco_vinculado = None
    try:
        linha = processar_linha(bruta)
        with transaction.atomic():
            produto = _resolver_produto(linha)
            vendedor = _resolver_vendedor(linha)
            preco_vinculado, criado = _resolver_preco(importacao, produto, vendedor, linha)
    except LinhaRejeitada as rejeitada:
        _registrar_linha(importacao, numero_linha, bruta, STATUS_LINHA.QUARENTENA, rejeitada.motivos)
        return STATUS_LINHA.QUARENTENA
    except IntegrityError:
        logger.exception('Erro de integridade na linha %s da importação %s', numero_linha, importacao.pk)
        _registrar_linha(
            importacao,
            numero_linha,
            bruta,
            STATUS_LINHA.QUARENTENA,
            ['Erro interno de persistência (violação de restrição do banco); linha não gravada.'],
        )
        return STATUS_LINHA.QUARENTENA

    if not criado:
        _registrar_linha(
            importacao,
            numero_linha,
            bruta,
            STATUS_LINHA.DUPLICADA,
            [
                'Registro já existente: mesmo SKU, vendedor, UF e coletado_em '
                f'(preço #{preco_vinculado.pk}, importação #{preco_vinculado.importacao_id}).'
            ],
            preco=preco_vinculado,
        )
        return STATUS_LINHA.DUPLICADA

    _atualizar_vigente(preco_vinculado)
    _registrar_linha(importacao, numero_linha, bruta, STATUS_LINHA.IMPORTADA, [], preco=preco_vinculado)
    return STATUS_LINHA.IMPORTADA


def _resolver_produto(linha: LinhaNormalizada):
    """Cria/atualiza o produto; rejeita a linha se o EAN divergir do cadastrado."""
    from apps.products.models import Produto

    produto = Produto.objects.filter(sku=linha.sku).first()
    if produto is None:
        return Produto.objects.create(
            sku=linha.sku,
            ean=linha.ean,
            nome=linha.produto_nome,
            embalagem=linha.embalagem,
        )

    motivos = []
    if linha.ean and produto.ean and linha.ean != produto.ean:
        motivos.append(
            f'EAN divergente para o SKU {produto.sku}: cadastrado {produto.ean}, '
            f'linha informa {linha.ean}.'
        )
    if motivos:
        raise LinhaRejeitada(motivos)

    campos = []
    if produto.ean is None and linha.ean:
        produto.ean = linha.ean
        campos.append('ean')
    if produto.nome != linha.produto_nome:
        produto.nome = linha.produto_nome
        campos.append('nome')
    if produto.embalagem != linha.embalagem:
        produto.embalagem = linha.embalagem
        campos.append('embalagem')
    if campos:
        produto.save(update_fields=campos + ['atualizado_em'])
    return produto


def _resolver_vendedor(linha: LinhaNormalizada):
    """Vendedor identificado pela chave normalizada (deduplicação por design)."""
    from apps.products.models import Vendedor

    vendedor, _ = Vendedor.objects.get_or_create(
        nome_normalizado=linha.vendedor_chave,
        defaults={'nome': linha.vendedor_nome},
    )
    return vendedor


def _resolver_preco(importacao, produto, vendedor, linha: LinhaNormalizada):
    """Insere o preço; ``(preco, False)`` significa registro já existente."""
    from apps.products.models import Preco

    coletado_em = linha.coletado_em
    if timezone.is_naive(coletado_em):
        # Rede de segurança: o contrato pede datetime consciente de fuso.
        coletado_em = timezone.make_aware(coletado_em, timezone.get_current_timezone())

    preco, criado = Preco.objects.get_or_create(
        produto=produto,
        vendedor=vendedor,
        uf=linha.uf,
        coletado_em=coletado_em,
        defaults={
            'preco': linha.preco,
            'preco_promocional': linha.preco_promocional,
            'moeda': linha.moeda,
            'estoque': linha.estoque,
            'importacao': importacao,
            'is_vigente': False,
        },
    )
    return preco, criado


def _atualizar_vigente(preco) -> None:
    """Mantém exatamente um preço vigente por (produto, vendedor, uf).

    O vigente é o da última coleta (``coletado_em`` maior). Em caso de empate
    de data/hora, o registro recém-criado vence (última importação processada).
    """
    with transaction.atomic():
        existe_mais_nova = (
            preco.produto.precos.filter(
                vendedor_id=preco.vendedor_id,
                uf=preco.uf,
                coletado_em__gt=preco.coletado_em,
                is_vigente=True,
            )
            .exclude(pk=preco.pk)
            .exists()
        )
        if existe_mais_nova:
            if preco.is_vigente:
                preco.is_vigente = False
                preco.save(update_fields=['is_vigente'])
            return
        (
            preco.produto.precos.filter(
                vendedor_id=preco.vendedor_id, uf=preco.uf, is_vigente=True
            )
            .exclude(pk=preco.pk)
            .update(is_vigente=False)
        )
        if not preco.is_vigente:
            preco.is_vigente = True
            preco.save(update_fields=['is_vigente'])


def _registrar_linha(importacao, numero_linha, bruta, status, motivos, preco=None) -> None:
    ImportacaoLinha.objects.create(
        importacao=importacao,
        numero_linha=numero_linha,
        dados_originais=bruta,
        status=status,
        motivos=list(motivos),
        preco=preco,
    )


def _contar(importacao: Importacao, status_linha: str) -> None:
    importacao.total_linhas += 1
    if status_linha == STATUS_LINHA.IMPORTADA:
        importacao.processadas += 1
    elif status_linha == STATUS_LINHA.QUARENTENA:
        importacao.quarentena_count += 1
    else:
        importacao.duplicadas_count += 1
    if importacao.total_linhas % LOTE_PROGRESSO == 0:
        _salvar_contadores(importacao)


def _salvar_contadores(importacao: Importacao) -> None:
    importacao.save(
        update_fields=['total_linhas', 'processadas', 'quarentena_count', 'duplicadas_count']
    )


def _finalizar(importacao: Importacao, status: str, erro: str = '') -> None:
    """Persiste, de uma vez, contadores + status final + carimbo de término."""
    importacao.status = status
    importacao.erro = erro
    importacao.finalizada_em = timezone.now()
    importacao.save(
        update_fields=[
            'total_linhas',
            'processadas',
            'quarentena_count',
            'duplicadas_count',
            'status',
            'erro',
            'finalizada_em',
        ]
    )


def _falhar(importacao: Importacao, mensagem: str) -> None:
    _finalizar(importacao, Importacao.Status.FALHOU, mensagem)
    logger.warning('Importação %s falhou: %s', importacao.pk, mensagem)