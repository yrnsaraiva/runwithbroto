from django.urls import path

from . import views

app_name = "gameon"

urlpatterns = [
    path("ranking/", views.ranking, name="ranking"),
    path("ranking/<uuid:edicao_id>/", views.ranking, name="ranking_edicao"),
    path("regulamento/", views.regulamento, name="regulamento"),
    path("entrar/", views.escolher_participante, name="escolher_participante"),
    path("sair/", views.sair_participante, name="sair_participante"),
    path("registar/", views.registar_actividade, name="registar_actividade"),
    path("minhas-actividades/", views.minhas_actividades, name="minhas_actividades"),
    path("painel/", views.painel_verificacao, name="painel_verificacao"),
    path("painel/<uuid:actividade_id>/aprovar/", views.aprovar_actividade, name="aprovar_actividade"),
    path("painel/<uuid:actividade_id>/rejeitar/", views.rejeitar_actividade, name="rejeitar_actividade"),
]