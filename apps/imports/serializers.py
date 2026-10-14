from rest_framework import serializers

from .models import Importacao, ImportacaoLinha


class ImportacaoSerializer(serializers.ModelSerializer):
    arquivo = serializers.SerializerMethodField()
    quarentena_url = serializers.SerializerMethodField()

    class Meta:
        model = Importacao
        fields = [
            'id',
            'arquivo',
            'nome_arquivo_original',
            'status',
            'total_linhas',
            'processadas',
            'quarentena_count',
            'duplicadas_count',
            'erro',
            'criada_por',
            'criada_em',
            'finalizada_em',
            'quarentena_url',
        ]
        read_only_fields = fields

    def get_arquivo(self, obj) -> str:
        return obj.nome_arquivo_original or (obj.arquivo.name if obj.arquivo else '')

    def get_quarentena_url(self, obj) -> str:
        request = self.context.get('request')
        url = f'/api/importacoes/{obj.pk}/quarentena/'
        return request.build_absolute_uri(url) if request else url


class ImportacaoLinhaSerializer(serializers.ModelSerializer):
    class Meta:
        model = ImportacaoLinha
        fields = ['id', 'numero_linha', 'status', 'motivos', 'dados_originais', 'criada_em']
        read_only_fields = fields


class UploadImportacaoSerializer(serializers.Serializer):
    """Validação estrutural do upload; regras de conteúdo ficam em ``data/``."""

    arquivo = serializers.FileField(
        allow_empty_file=False,
        help_text='Arquivo CSV (;) com os preços coletados.',
    )

    def validate_arquivo(self, arquivo):
        from pathlib import Path

        nome = getattr(arquivo, 'name', '') or ''
        if Path(nome).suffix.lower() != '.csv':
            raise serializers.ValidationError('Formato aceito: apenas arquivos .csv.')
        return arquivo