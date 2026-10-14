from django.contrib import admin

from .models import Preco, Produto, Vendedor


@admin.register(Produto)
class ProdutoAdmin(admin.ModelAdmin):
    list_display = ('sku', 'ean', 'nome', 'embalagem', 'atualizado_em')
    search_fields = ('sku', 'ean', 'nome')


@admin.register(Vendedor)
class VendedorAdmin(admin.ModelAdmin):
    list_display = ('nome', 'nome_normalizado', 'criado_em')
    search_fields = ('nome', 'nome_normalizado')


@admin.register(Preco)
class PrecoAdmin(admin.ModelAdmin):
    list_display = ('produto', 'vendedor', 'uf', 'preco', 'coletado_em', 'is_vigente')
    list_filter = ('uf', 'vendedor', 'is_vigente')
    search_fields = ('produto__sku', 'produto__nome')
    readonly_fields = ('criado_em',)