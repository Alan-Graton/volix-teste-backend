from django.contrib import admin

from .models import Importacao, ImportacaoLinha


class ImportacaoLinhaInline(admin.TabularInline):
    model = ImportacaoLinha
    extra = 0
    readonly_fields = ('numero_linha', 'status', 'motivos', 'dados_originais', 'preco')
    can_delete = False


@admin.register(Importacao)
class ImportacaoAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'status',
        'nome_arquivo_original',
        'total_linhas',
        'processadas',
        'quarentena_count',
        'duplicadas_count',
        'criada_em',
        'finalizada_em',
    )
    list_filter = ('status',)
    readonly_fields = (
        'arquivo_sha256',
        'total_linhas',
        'processadas',
        'quarentena_count',
        'duplicadas_count',
        'erro',
        'criada_em',
        'finalizada_em',
    )
    inlines = [ImportacaoLinhaInline]


@admin.register(ImportacaoLinha)
class ImportacaoLinhaAdmin(admin.ModelAdmin):
    list_display = ('id', 'importacao', 'numero_linha', 'status', 'criada_em')
    list_filter = ('status',)
    readonly_fields = ('importacao', 'numero_linha', 'dados_originais', 'status', 'motivos', 'preco')