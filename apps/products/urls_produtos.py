from django.urls import path

from . import views

urlpatterns = [
    path(
        '<str:sku>/referencia/',
        views.ProdutoReferenciaView.as_view(),
        name='produto-referencia',
    ),
]