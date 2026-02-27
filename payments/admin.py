from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse

from .models import Payment


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        "reference",
        "status",
        "amount",
        "method",
        "paysuite_id",
        "registration_link",
        "created_at",
    )

    list_filter = (
        "status",
        "method",
        "created_at",
    )

    search_fields = (
        "reference",
        "paysuite_id",
        "transaction_id",
        "registration__ticket_code",
        "registration__full_name",
        "registration__phone",
        "registration__email",
        "registration__event__title",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
        "paid_at",
        "raw_provider_payload",
        "last_webhook_request_id",
    )

    fieldsets = (
        ("Core", {
            "fields": (
                "registration",
                "reference",
                "status",
                "amount",
            )
        }),
        ("PaySuite", {
            "fields": (
                "paysuite_id",
                "checkout_url",
                "method",
                "transaction_id",
                "paid_at",
            )
        }),
        ("Webhook / Logs", {
            "fields": (
                "last_webhook_request_id",
                "raw_provider_payload",
            )
        }),
        ("Meta", {
            "fields": (
                "created_at",
                "updated_at",
            )
        }),
    )

    def registration_link(self, obj: Payment):
        """
        Link clicável para a inscrição no admin.
        """
        if not obj.registration_id:
            return "-"
        url = reverse("admin:events_eventregistration_change", args=[obj.registration_id])
        label = getattr(obj.registration, "ticket_code", None) or f"Registration #{obj.registration_id}"
        return format_html('<a href="{}">{}</a>', url, label)

    registration_link.short_description = "Registration"

    def event_link(self, obj: Payment):
        """
        Link clicável para o evento no admin.
        """
        reg = getattr(obj, "registration", None)
        event_id = getattr(reg, "event_id", None)
        if not event_id:
            return "-"
        url = reverse("admin:events_event_change", args=[event_id])
        return format_html('<a href="{}">{}</a>', url, reg.event.title)

    event_link.short_description = "Event"