from django.contrib import admin
from unfold.admin import ModelAdmin
from .models import CheckInLog


@admin.register(CheckInLog)
class CheckInLogAdmin(ModelAdmin):
    list_display = ("ticket_external_id", "result", "scanned_by", "scanned_at", "raw_qr")
    list_filter = ("result", "scanned_by")
    search_fields = ("ticket_external_id", "raw_qr")
    readonly_fields = ("ticket_external_id", "result", "scanned_by", "scanned_at", "raw_qr")
    ordering = ("-scanned_at",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False