from django.contrib import admin, messages
from django.urls import reverse
from django.utils.html import format_html
from .models import Event, EventRegistration, RegistrationStatus


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ("title", "city", "event_type", "start_at", "is_published")
    list_filter = ("city", "event_type", "is_published")
    search_fields = ("title", "meeting_point")
    prepopulated_fields = {"slug": ("title",)}
    ordering = ("start_at",)


@admin.register(EventRegistration)
class EventRegistrationAdmin(admin.ModelAdmin):
    list_display = ("ticket_code", "full_name", "phone", "event", "ticket_link")
    list_filter = ("event", "payment_status", "status")
    search_fields = ("full_name", "email", "phone", "ticket_code")
    readonly_fields = ("created_at", "updated_at")
    ordering = ("-created_at",)

    def ticket_link(self, obj: EventRegistration):
        """
        Link aparece no admin (lista + detalhe).
        Só habilita se estiver PAID.
        """
        if obj.status != RegistrationStatus.ACTIVE:
            return format_html(
                '<span style="color:#6b6b6b;">Ticket indisponível.</span>'
            )

        url = reverse("events:order_ticket_pdf", kwargs={"ticket_code": obj.ticket_code})
        return format_html(
            '<a href="{}" target="_blank">Baixar ticket</a>',
            url
        )

    ticket_link.short_description = "Ticket"
