from django.contrib import admin
from unfold.admin import ModelAdmin

from apps.events.models import ExternalTicket
from .models import CheckInLog


@admin.register(CheckInLog)
class CheckInLogAdmin(ModelAdmin):
    list_display = (
        "ticket_external_id",
        "participant_name",
        "result",
        "scanned_by",
        "scanned_at",
        "entry_time",
        "raw_qr",
    )
    list_filter = ("result", "scanned_by")
    search_fields = ("ticket_external_id", "raw_qr")
    readonly_fields = ("ticket_external_id", "result", "scanned_by", "scanned_at", "raw_qr")
    ordering = ("-scanned_at",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        """
        Pré-carrega, em bloco (poucas queries no total, independente do
        número de linhas), os tickets associados e o horário da primeira
        entrada bem sucedida de cada ticket. Evita N+1 queries no list_display.
        """
        qs = super().get_queryset(request).select_related("scanned_by")

        external_ids = list(qs.values_list("ticket_external_id", flat=True))

        # Nome do participante (via ExternalTicket, ligado por external_id)
        self._tickets_cache = {
            t.external_id: t
            for t in ExternalTicket.objects.filter(external_id__in=external_ids)
        }

        # Horário real da entrada = scanned_at do primeiro log com result="ok"
        # para aquele ticket (cobre tanto o próprio check-in como tentativas
        # posteriores marcadas como "already_entered").
        first_entries = {}
        ok_logs = (
            CheckInLog.objects
            .filter(ticket_external_id__in=external_ids, result=CheckInLog.Result.OK)
            .order_by("ticket_external_id", "scanned_at")
        )
        for log in ok_logs:
            first_entries.setdefault(log.ticket_external_id, log.scanned_at)
        self._first_entry_cache = first_entries

        return qs

    @admin.display(description="Participante")
    def participant_name(self, obj):
        ticket = self._tickets_cache.get(obj.ticket_external_id)
        if ticket and ticket.buyer_name:
            return ticket.buyer_name
        return "-"

    @admin.display(description="Hora da entrada")
    def entry_time(self, obj):
        entry = self._first_entry_cache.get(obj.ticket_external_id)
        if entry:
            return entry.strftime("%d/%m/%Y %H:%M:%S")
        return "-"
