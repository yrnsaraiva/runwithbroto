import csv
from django.contrib import admin
from django.http import HttpResponse
from django.urls import path, reverse
from django.utils.html import format_html
from django.utils import timezone
import json
from django.db.models import Count, Sum, Q, Avg
from datetime import timedelta
from django.shortcuts import render

from .models import ExternalTicket, Provincia
from .pdfs_external_checkin import build_external_checkin_list_pdf

from django.contrib.admin import AdminSite


class CustomAdminSite(AdminSite):
    def get_app_list(self, request):
        app_list = super().get_app_list(request)

        # Adicionar Dashboard no topo do menu
        app_list.insert(0, {
            'name': 'Dashboard',
            'app_label': 'dashboard',
            'models': [{
                'name': 'Visão Geral',
                'object_name': 'dashboard',
                'admin_url': reverse('admin:externalticket_dashboard'),
                'view_only': True,
                'perms': {'add': False, 'change': False, 'delete': False}
            }]
        })
        return app_list


# Substituir o admin padrão (opcional)
# admin_site = CustomAdminSite(name='myadmin')


@admin.register(ExternalTicket)
class ExternalTicketAdmin(admin.ModelAdmin):
    list_display = (
        "external_id",
        "event_name",
        "buyer_name",
        "buyer_phone",
        "price_amount",
        "payment_status",
    )

    search_fields = (
        "external_id",
        "event_name",
        "buyer_phone",
    )

    list_filter = (
        "payment_status",
        "status",
        "event_name",
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

    actions = ("export_selected_csv", "export_selected_pdf")

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
                "buyer_email",
                "buyer_province",
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

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "event/<path:event_name>/checkin-list/pdf/",
                self.admin_site.admin_view(self.event_checkin_pdf_view),
                name="externalticket_event_checkin_pdf",
            ),
            path(
                "event/<path:event_name>/checkin-list/csv/",
                self.admin_site.admin_view(self.event_checkin_csv_view),
                name="externalticket_event_checkin_csv",
            ),
        ]
        return custom_urls + urls

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}

        extra_context['dashboard_url'] = reverse('admin:externalticket_dashboard')

        event_name = request.GET.get("event_name__exact")
        if event_name:
            pdf_url = reverse("admin:externalticket_event_checkin_pdf", args=[event_name])
            csv_url = reverse("admin:externalticket_event_checkin_csv", args=[event_name])
            extra_context["checkin_pdf_url"] = pdf_url
            extra_context["checkin_csv_url"] = csv_url
            extra_context["selected_event_name"] = event_name

        return super().changelist_view(request, extra_context=extra_context)

    def event_checkin_pdf_view(self, request, event_name):
        tickets = list(
            ExternalTicket.objects
            .filter(event_name=event_name, payment_status__iexact="paid")
            .order_by("buyer_name")
        )

        pdf_bytes = build_external_checkin_list_pdf(event_name, tickets)

        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="checkin-{event_name}.pdf"'
        return response

    def event_checkin_csv_view(self, request, event_name):
        tickets = (
            ExternalTicket.objects
            .filter(event_name=event_name, payment_status__iexact="paid")
            .order_by("buyer_name")
        )

        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="checkin-{event_name}.csv"'
        response.write("\ufeff")

        writer = csv.writer(response)
        writer.writerow([
            "ticket_id",
            "buyer_name",
            "buyer_phone",
            "buyer_email",
            "payment_status",
            "entered",
            "event_name",
            "event_date",
        ])

        for t in tickets:
            writer.writerow([
                t.external_id,
                t.buyer_name,
                t.buyer_phone,
                t.buyer_email,
                t.payment_status,
                "YES" if t.entered else "NO",
                t.event_name,
                t.event_date,
            ])

        return response

    def export_selected_csv(self, request, queryset):
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="external-tickets.csv"'
        response.write("\ufeff")

        writer = csv.writer(response)
        writer.writerow([
            "ticket_id",
            "buyer_name",
            "buyer_phone",
            "buyer_email",
            "payment_status",
            "entered",
            "event_name",
            "event_date",
        ])

        for t in queryset.order_by("event_name", "buyer_name"):
            writer.writerow([
                t.external_id,
                t.buyer_name,
                t.buyer_phone,
                t.buyer_email,
                t.payment_status,
                "YES" if t.entered else "NO",
                t.event_name,
                t.event_date,
            ])

        return response

    export_selected_csv.short_description = "Exportar selecionados (CSV)"

    def export_selected_pdf(self, request, queryset):
        tickets = list(queryset.order_by("buyer_name"))
        if not tickets:
            return None

        event_name = tickets[0].event_name if len({t.event_name for t in tickets}) == 1 else "multi-event"
        pdf_bytes = build_external_checkin_list_pdf(event_name, tickets)

        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="checkin-{event_name}.pdf"'
        return response

    export_selected_pdf.short_description = "Exportar selecionados (PDF)"

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            # ... suas URLs existentes ...
            path(
                "dashboard/",
                self.admin_site.admin_view(self.dashboard_view),
                name="externalticket_dashboard",
            ),
        ]
        return custom_urls + urls

    def dashboard_view(self, request):
        # 1. TOTAL DE PESSOAS QUE COMPRARAM BILHETES
        total_compradores = ExternalTicket.objects.values('buyer_phone').distinct().count()
        total_tickets = ExternalTicket.objects.count()

        # 2. RECEITA TOTAL
        receita_total = ExternalTicket.objects.filter(
            payment_status__iexact='paid'
        ).aggregate(total=Sum('price_amount'))['total'] or 0

        # 3. PESSOAS POR PROVÍNCIA
        provincia_stats = []
        for codigo, nome in Provincia.choices:
            count = ExternalTicket.objects.filter(buyer_province=codigo).count()
            if count > 0:
                provincia_stats.append({
                    'nome': nome,
                    'quantidade': count
                })

        # Ordenar por quantidade (maior para menor)
        provincia_stats.sort(key=lambda x: x['quantidade'], reverse=True)

        context = {
            'title': 'Dashboard',
            'total_compradores': total_compradores,
            'total_tickets': total_tickets,
            'receita_total': receita_total,
            'provincia_stats': provincia_stats,
        }

        return render(request, 'admin/events/externalticket/dashboard.html', context)