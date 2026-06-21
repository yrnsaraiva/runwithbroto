from django.urls import path
from . import views

app_name = "scanner"

urlpatterns = [
    path("",          views.scanner_view,   name="index"),
    path("validate/", views.validate_ticket, name="validate"),
    path("stats/",    views.stats_view,      name="stats"),
    path("log/",      views.log_view,        name="log"),
]