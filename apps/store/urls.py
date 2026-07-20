from django.urls import path

from . import views

app_name = "store"

urlpatterns = [
    path("", views.store_list, name="store_list"),
    path("encomendas/nova/", views.create_order, name="create_order"),
]
