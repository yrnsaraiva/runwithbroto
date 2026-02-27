from django.urls import path
from . import views
from .webhooks import paysuite_webhook

app_name = "payments"

urlpatterns = [
    path("start/", views.start_event_payment, name="start_event_payment"),
    path("return/", views.payment_return, name="return"),
    path("webhook/paysuite/", paysuite_webhook, name="webhook_paysuite"),
]