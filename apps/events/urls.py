from django.urls import path
from . import views

app_name = "events"

urlpatterns = [
    path("schedule/", views.event_list, name="event_list"),
    path("event/<str:event_id>/", views.event_detail, name="event_detail"),
    path("event/<str:event_id>/inscrever/", views.register_form, name="register"),
    path("event/<str:event_id>/confirmar/", views.confirm_presence, name="confirm_presence"),
    path("tickets/<uuid:token>/success/", views.register_success, name="registration_success"),
    path("tickets/<uuid:token>/status/", views.ticket_status, name="ticket_status"),
    path("webhooks/etk/", views.etk_webhook, name="etk_webhook"),
    path("tickets/<uuid:token>/download/", views.download_external_ticket_pdf, name="download_external_ticket_pdf"),

    # Inscrição Temporária
    path("temp/<slug:slug>/", views.temp_registration_form, name="temp_registration"),
    path("temp/aguardando/<str:token>/", views.temp_registration_waiting, name="temp_registration_waiting"),
    path("temp/status/<str:token>/", views.temp_registration_status, name="temp_registration_status"),
    path("temp/<uuid:token>/sucesso/", views.temp_registration_success, name="temp_registration_success"),
    path("temp/<uuid:token>/download/", views.temp_registration_download, name="temp_registration_download"),
    path("webhooks/temp/", views.temp_registration_webhook, name="temp_registration_webhook"),
]
