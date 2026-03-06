from django.urls import path
from . import views

app_name = "events"

urlpatterns = [
    path("schedule/", views.event_list, name="event_list"),
    path("event/<str:event_id>/", views.event_detail, name="event_detail"),
    path("events/<str:event_id>/inscrever/", views.register_form, name="register"),
    path("<str:event_id>/success/", views.register_success, name="registration_success"),
]
