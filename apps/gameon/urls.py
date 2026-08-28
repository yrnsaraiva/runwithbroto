from django.urls import path

from . import views

app_name = "gameon"

urlpatterns = [
    path("ranking/", views.RankingView.as_view(), name="ranking"),
    path("registar/", views.registar_actividade, name="registar_actividade"),
    path("minhas-actividades/", views.minhas_actividades, name="minhas_actividades"),
    path("painel/", views.painel_verificacao, name="painel_verificacao"),
    path("painel/<uuid:actividade_id>/aprovar/", views.aprovar_actividade, name="aprovar_actividade"),
    path("painel/<uuid:actividade_id>/rejeitar/", views.rejeitar_actividade, name="rejeitar_actividade"),
]