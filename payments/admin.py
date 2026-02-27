from django.contrib import admin
from .models import Payment


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        "reference",
        "status",
        "method",
        "amount",
        "currency",
        "registration",
        "paysuite_id",
        "transaction_id",
        "paid_at",
        "created_at",
    )
    list_filter = ("status", "method", "currency", "created_at")
    search_fields = ("reference", "paysuite_id", "transaction_id", "registration__ticket_code", "registration__phone")
    readonly_fields = ("created_at", "updated_at", "raw_provider_payload", "last_webhook_request_id")