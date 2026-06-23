from django.urls import path
from .views import perfil_view, membro_fundador

urlpatterns = [
    path("perfil/", perfil_view, name="perfil"),
    path('membro-fundador/', membro_fundador, name='membro_fundador'),
]