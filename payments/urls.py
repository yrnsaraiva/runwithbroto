from django.urls import path
from . import views
from . import webhooks

app_name = "payments"

urlpatterns = [
    path("start/", views.start_event_payment, name="start_event_payment"),
    path("return/", views.payment_return, name="return"),
    path("status/", views.payment_status, name="status"),
    path("webhook/paysuite/", webhooks.paysuite_webhook, name="webhook_paysuite"),
]