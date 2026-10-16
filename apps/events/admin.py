import csv
import logging
import requests
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.validators import validate_email
from django.http import HttpResponse
from django.urls import path, reverse
from django.utils.html import format_html
from django.utils import timezone
import json
from django.db.models import Count, Sum, Q, Avg
from datetime import timedelta
from django.shortcuts import get_object_or_404, redirect, render

from . import etk_client
from .models import ExternalTicket, Provincia, TamanhoCamisete
from .pdfs_external_checkin import build_external_checkin_list_pdf
from .pdf import build_external_ticket_pdf

from django.contrib.admin import AdminSite
from unfold.admin import ModelAdmin
from unfold.contrib.filters.admin import RangeDateFilter, RangeDateTimeFilter

from import_export.admin import ImportExportModelAdmin


logger = logging.getLogger(__name__)


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
class ExternalTicketAdmin(ModelAdmin, ImportExportModelAdmin):
    list_display = (
        "external_id",
        "event_name",
        "buyer_name",
        "buyer_phone",
        "entered",
        "download_ticket_link",
    )

    search_fields = (
        "external_id",
        "buyer_phone",
    )

    list_filter_submit = True

    list_filter = (
        "payment_status",
        "status",
        "event_name",
        "entered",
        ("created_at", RangeDateTimeFilter)
    )

    list_editable = ("entered",)

    list_per_page = 500

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

    def get_queryset(self, request):
        # Só bilhetes com pagamento confirmado (pago ou convite).
        return super().get_queryset(request).filter(payment_status__in=("paid", "invited"))

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
                "tamanho_camisete",
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

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}

        extra_context['dashboard_url'] = reverse('admin:externalticket_dashboard')
        extra_context['invites_url'] = reverse('admin:externalticket_invites')

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

    def download_ticket_pdf_view(self, request, ticket_id):
        ticket = get_object_or_404(ExternalTicket, pk=ticket_id)

        pdf_bytes = build_external_ticket_pdf(ticket)

        filename = f"ticket-{ticket.external_id}.pdf"
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response

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
            path(
                "dashboard/",
                self.admin_site.admin_view(self.dashboard_view),
                name="externalticket_dashboard",
            ),
            path(
                "invites/",
                self.admin_site.admin_view(self.invites_view),
                name="externalticket_invites",
            ),
            path(
                "invites/<int:ticket_id>/send/",
                self.admin_site.admin_view(self.invite_send_view),
                name="externalticket_invite_send",
            ),
            path(
                "<int:ticket_id>/download-ticket-pdf/",
                self.admin_site.admin_view(self.download_ticket_pdf_view),
                name="externalticket_download_ticket_pdf",
            ),
        ]
        return custom_urls + urls

    def _invite_context(self, request, extra=None):
        from . import invites
        try:
            events = [e for e in etk_client.get_events() if e.get("prices")]
            events_error = ""
        except Exception as exc:
            logger.warning("Convites: não foi possível ler os eventos: %s", exc)
            events, events_error = [], "Não foi possível carregar os eventos da API."
        rows = []
        for t in ExternalTicket.objects.filter(payment_status="invited").order_by("-created_at")[:100]:
            link = invites.invite_link(request, t)
            rows.append({
                "ticket": t, "link": link, "whatsapp": invites.whatsapp_url(t, link),
                "pdf": reverse("admin:externalticket_download_ticket_pdf", args=[t.pk]),
            })
        context = {
            **self.admin_site.each_context(request),
            "title": "Convites", "events": events, "events_error": events_error,
            "rows": rows, "email_enabled": invites.email_enabled(),
            "form": {"quantity": 1}, "sizes": TamanhoCamisete.choices,
        }
        context.update(extra or {})
        return context

    def invites_view(self, request):
        """Criar convites (bilhetes gratuitos que ocupam vaga) e enviá-los."""
        from . import invites
        if not self.has_add_permission(request):
            raise PermissionDenied
        if request.method != "POST":
            return render(request, "admin/events/externalticket/invites.html",
                          self._invite_context(request))

        form = {k: request.POST.get(k, "").strip() for k in
                ("lote", "quantity", "name", "email", "phone", "note", "size")}
        errors = []
        event_id, _, price_id = form["lote"].partition("|")
        if not event_id or not price_id:
            errors.append("Escolha o evento e o lote.")
        try:
            quantity = int(form["quantity"] or 1)
            if not 1 <= quantity <= 200:
                raise ValueError
        except ValueError:
            quantity = 1
            errors.append("A quantidade tem de estar entre 1 e 200.")
        phone = ""
        if form["phone"]:
            phone = invites.normalize_phone(form["phone"])
            if not phone:
                errors.append("Telefone inválido. Use 9 dígitos (ex.: 84xxxxxxx).")
        if form["size"] and form["size"] not in TamanhoCamisete.values:
            errors.append("Tamanho de camisete inválido.")
        if form["email"]:
            try:
                validate_email(form["email"])
            except ValidationError:
                errors.append("E-mail inválido.")
        if not (form["name"] or form["email"] or phone or form["note"]) and quantity == 1:
            errors.append("Indique pelo menos o nome, o contacto ou uma nota do convidado.")
        if errors:
            for e in errors:
                messages.error(request, e)
            return render(request, "admin/events/externalticket/invites.html",
                          self._invite_context(request, {"form": {**form, "quantity": form["quantity"]}}),
                          status=400)

        try:
            tickets = invites.create_invites(
                event_id=event_id, price_id=price_id, quantity=quantity, name=form["name"],
                email=form["email"], phone=phone, note=form["note"], shirt_size=form["size"])
        except requests.HTTPError as exc:
            detail = ""
            try:
                detail = exc.response.json().get("message", "")
            except Exception:
                pass
            messages.error(request, detail or "A API recusou o pedido de convites.")
            return render(request, "admin/events/externalticket/invites.html",
                          self._invite_context(request, {"form": form}), status=400)
        except Exception as exc:
            logger.error("Convites: erro ao criar: %s", exc)
            messages.error(request, "Não foi possível criar os convites. Tente novamente.")
            return render(request, "admin/events/externalticket/invites.html",
                          self._invite_context(request, {"form": form}), status=502)

        messages.success(request, f"{len(tickets)} convite(s) criado(s).")
        if form["email"]:
            self._send_email(request, tickets)
        return redirect("admin:externalticket_invites")

    def _send_email(self, request, tickets):
        from . import invites
        if not invites.email_enabled():
            messages.warning(
                request, "Envio por e-mail não configurado (EMAIL_HOST): partilhe o link ou use o WhatsApp.")
            return
        links = {t.pk: invites.invite_link(request, t) for t in tickets}
        try:
            invites.send_invite_email(tickets, links)
            messages.success(request, f"E-mail enviado para {tickets[0].buyer_email}.")
        except Exception as exc:
            logger.error("Convites: falha ao enviar e-mail: %s", exc)
            messages.error(request, "Os convites foram criados, mas o e-mail falhou. Tente reenviar.")

    def invite_send_view(self, request, ticket_id):
        """(Re)enviar o e-mail de um convite."""
        if request.method != "POST":
            return redirect("admin:externalticket_invites")
        if not self.has_change_permission(request):
            raise PermissionDenied
        ticket = get_object_or_404(ExternalTicket, pk=ticket_id, payment_status="invited")
        if not ticket.buyer_email:
            messages.error(request, "Este convite não tem e-mail.")
        else:
            self._send_email(request, [ticket])
        return redirect("admin:externalticket_invites")

    def dashboard_view(self, request):
        # O dashboard único vive no índice do admin (apps.core.dashboard).
        return redirect("admin:index")

    @admin.display(description="Ticket PDF")
    def download_ticket_link(self, obj):
        url = reverse("admin:externalticket_download_ticket_pdf", args=[obj.pk])
        return format_html('<a class="button" href="{}">Baixar PDF</a>', url)