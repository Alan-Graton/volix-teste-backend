"""Endpoints das importações.

- ``POST /api/importacoes/``  -> aceita o CSV e responde imediatamente (202);
- ``GET  /api/importacoes/``  -> lista o andamento/resultado de cada importação;
- ``GET  /api/importacoes/{id}/`` -> detalhe (status, contadores, erro);
- ``GET  /api/importacoes/{id}/quarentena/`` -> linhas rejeitadas + motivos.
"""
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .models import Importacao, ImportacaoLinha
from .serializers import ImportacaoLinhaSerializer, ImportacaoSerializer, UploadImportacaoSerializer


class ImportacaoListCreateView(generics.ListCreateAPIView):
    """Lista importações (GET) e recebe novas importações (POST)."""

    queryset = Importacao.objects.all()
    serializer_class = ImportacaoSerializer
    permission_classes = [IsAuthenticated]

    def create(self, request, *args, **kwargs):
        serializer = UploadImportacaoSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        arquivo = serializer.validated_data['arquivo']

        if arquivo.size > services.TAMANHO_MAXIMO_BYTES:
            limite_mb = services.TAMANHO_MAXIMO_BYTES // (1024 * 1024)
            return Response(
                {'arquivo': [f'Arquivo acima do limite de {limite_mb} MiB.']},
                status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )

        sha256 = services.calcular_sha256(arquivo)
        existente = services.importacao_anterior(sha256)
        if existente is not None:
            data = self.get_serializer(existente).data
            data['duplicado'] = True
            data['detalhe'] = (
                'Arquivo idêntico já importado; nenhum dado novo será processado.'
            )
            return Response(data, status=status.HTTP_202_ACCEPTED)

        importacao = Importacao.objects.create(
            arquivo=arquivo,
            nome_arquivo_original=getattr(arquivo, 'name', '') or '',
            arquivo_sha256=sha256,
            criada_por=request.user,
        )
        services.enviar_para_processamento(importacao)

        data = self.get_serializer(importacao).data
        data['duplicado'] = False
        data['detalhe'] = 'Importação aceita; acompanhe o andamento neste recurso.'
        return Response(data, status=status.HTTP_202_ACCEPTED)


class ImportacaoDetailView(generics.RetrieveAPIView):
    """Andamento e resultado de uma importação."""

    queryset = Importacao.objects.all()
    serializer_class = ImportacaoSerializer
    permission_classes = [IsAuthenticated]


class ImportacaoQuarentenaView(generics.ListAPIView):
    """Linhas não aproveitadas (quarentena/duplicadas) com os motivos.

    Filtro ``?status=``: ``nao_importadas`` (padrão), ``quarentena``,
    ``duplicada``, ``importada`` ou ``todas``.
    """

    serializer_class = ImportacaoLinhaSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        from rest_framework.exceptions import NotFound, ValidationError

        try:
            importacao = Importacao.objects.get(pk=self.kwargs['pk'])
        except Importacao.DoesNotExist:
            raise NotFound('Importação não encontrada.')

        qs = importacao.linhas.all()
        filtro = self.request.query_params.get('status', 'nao_importadas')
        opcoes = {
            'nao_importadas': qs.exclude(status=ImportacaoLinha.Status.IMPORTADA),
            'quarentena': qs.filter(status=ImportacaoLinha.Status.QUARENTENA),
            'duplicada': qs.filter(status=ImportacaoLinha.Status.DUPLICADA),
            'importada': qs.filter(status=ImportacaoLinha.Status.IMPORTADA),
            'todas': qs,
        }
        if filtro not in opcoes:
            raise ValidationError(
                {'status': f"Filtro inválido: {filtro!r}. Use um de: {', '.join(opcoes)}."}
            )
        return opcoes[filtro]