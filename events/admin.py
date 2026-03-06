from django.contrib import admin
from .models import ExternalTicket


@admin.register(ExternalTicket)
class ExternalTicketAdmin(admin.ModelAdmin):

    list_display = (
        "external_id",
        "event_name",
        "buyer_phone",
        "price_amount",
        "payment_status",
        "status",
        "entered",
        "external_created_at",
    )

    search_fields = (
        "external_id",
        "event_name",
        "buyer_phone",
    )

    list_filter = (
        "payment_status",
        "status",
        "entered",
        "event_category",
        "external_created_at",
    )

    ordering = ("-external_created_at",)

    readonly_fields = (
        "external_id",
        "event_id_external",
        "price_id_external",
        "external_created_at",
        "external_updated_at",
        "raw_payload",
    )

    fieldsets = (

        ("Ticket", {
            "fields": (
                "external_id",
                "status",
                "payment_status",
                "entered",
            )
        }),

        ("Buyer", {
            "fields": (
                "buyer_name",
                "buyer_phone",
            )
        }),

        ("Event", {
            "fields": (
                "event_id_external",
                "event_name",
                "event_category",
                "event_province",
                "event_location_details",
                "event_date",
                "event_image_url",
            )
        }),

        ("Price", {
            "fields": (
                "price_id_external",
                "price_amount",
            )
        }),

        ("External Data", {
            "fields": (
                "external_created_at",
                "external_updated_at",
                "raw_payload",
            ),
            "classes": ("collapse",),
        }),

    )