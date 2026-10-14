from django.urls import path

from . import views

urlpatterns = [
    path('', views.PrecoVigenteListView.as_view(), name='preco-vigente-list'),
]