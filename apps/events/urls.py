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
    path("tickets/<uuid:token>/download/", views.download_external_ticket_pdf, name="download_external_ticket_pdf", )
]
