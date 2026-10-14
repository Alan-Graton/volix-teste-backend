from django.urls import path

from . import views

urlpatterns = [
    path(
        '',
        views.ImportacaoListCreateView.as_view(),
        name='importacao-list-create',
    ),
    path(
        '<int:pk>/',
        views.ImportacaoDetailView.as_view(),
        name='importacao-detail',
    ),
    path(
        '<int:pk>/quarentena/',
        views.ImportacaoQuarentenaView.as_view(),
        name='importacao-quarentena',
    ),
]