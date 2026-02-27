from django.urls import path
from . import views

app_name = "events"

urlpatterns = [
    path("schedule/", views.event_list, name="event_list"),
    path("event/<slug:slug>/", views.event_detail, name="event_detail"),

    # Checkout
    path("events/<slug:slug>/inscrever/", views.register_form, name="register_form"),
    path("schedule/<slug:slug>/register/", views.register, name="register"),
    path("orders/<str:ticket_code>/success/", views.registration_success, name="registration_success"),

    path("orders/<str:ticket_code>/ticket.pdf", views.order_ticket_pdf, name="order_ticket_pdf"),
]
