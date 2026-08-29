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
]