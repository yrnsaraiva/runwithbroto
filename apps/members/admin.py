from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from django.utils.html import format_html
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.admin import GroupAdmin as BaseGroupAdmin
from django.contrib.auth.models import User, Group
from django.db import models
from apps.members.models import User, Perfil, Assinatura, Pagamento, Plano

from unfold.forms import AdminPasswordChangeForm, UserChangeForm, UserCreationForm
from unfold.admin import ModelAdmin
from unfold.admin import StackedInline, TabularInline


admin.site.unregister(Group)
admin.site.unregister(User)


class PerfilInline(StackedInline):
    model = Perfil
    can_delete = False
    verbose_name = "Dados do Membro"
    verbose_name_plural = "Dados do Membro"
    fields = ["phone", "date_of_birth", "gender"]


@admin.register(User)
class UserAdmin(BaseUserAdmin, ModelAdmin):
    form = UserChangeForm
    add_form = UserCreationForm
    change_password_form = AdminPasswordChangeForm

    def get_inlines(self, request, obj=None):
        return [PerfilInline]


@admin.register(Group)
class GroupAdmin(BaseGroupAdmin, ModelAdmin):
    pass


@admin.register(Plano)
class PlanoAdmin(ModelAdmin):
    list_display = ("nome", "preco", "duracao_dias", "activo", "created_at")
    list_filter = ("activo",)
    search_fields = ("nome",)
    ordering = ("preco",)


class PagamentoInline(TabularInline):
    model = Pagamento
    extra = 0
    fields = ("valor", "status", "referencia_externa", "pago_em")
    readonly_fields = ("pago_em",)


@admin.register(Assinatura)
class AssinaturaAdmin(ModelAdmin):
    list_display = ("usuario", "plano", "estado", "data_inicio", "data_fim", "dias_restantes_col")
    list_filter = ("estado", "plano")
    search_fields = ("usuario__nome", "usuario__email")
    ordering = ("-created_at",)
    inlines = [PagamentoInline]
    readonly_fields = ("created_at",)

    @admin.display(description="Dias restantes")
    def dias_restantes_col(self, obj):
        dias = obj.dias_restantes
        colour = "#A32D2D" if dias <= 7 else "#854F0B" if dias <= 30 else "#3B6D11"
        return format_html('<span style="color:{}">{} dias</span>', colour, dias)


@admin.register(Pagamento)
class PagamentoAdmin(admin.ModelAdmin):
    list_display = ("__str__", "status", "pago_em", "created_at")
    list_filter = ("status",)
    search_fields = ("assinatura__usuario__nome", "referencia_externa")
    ordering = ("-created_at",)
    readonly_fields = ("pago_em", "created_at")