from django.contrib import admin
from django.utils import timezone

from unfold.admin import ModelAdmin

from .models import Actividade, CartaSurpresa, Missao, Participante


@admin.register(Missao)
class MissaoAdmin(ModelAdmin):
    list_display = ("nome", "categoria", "pontos", "activa")
    list_filter = ("categoria", "activa")
    search_fields = ("nome", "chave")
    list_editable = ("pontos", "activa")  # ajustar pontuação a meio do jogo (regra 7)


@admin.register(CartaSurpresa)
class CartaSurpresaAdmin(ModelAdmin):
    list_display = ("tipo", "descricao", "pontos", "data_lancamento", "activa")
    list_filter = ("tipo", "activa")
    list_editable = ("activa",)
    search_fields = ("descricao", "tipo")


@admin.register(Participante)
class ParticipanteAdmin(ModelAdmin):
    list_display = ("nome", "telefone", "pontos_totais_cache", "numero_desafios_concluidos", "inscrito_em")
    search_fields = ("nome", "telefone")
    readonly_fields = ("pontos_totais_cache",)

    def numero_desafios_concluidos(self, obj):
        return obj.numero_desafios_concluidos()

    numero_desafios_concluidos.short_description = "Desafios concluídos"


@admin.register(Actividade)
class ActividadeAdmin(ModelAdmin):
    list_display = ("participante", "origem", "pontos", "estado", "data_actividade", "revisado_por")
    list_filter = ("estado", "missao__categoria", "data_actividade")
    search_fields = ("participante__nome",)
    autocomplete_fields = ("participante", "missao", "carta_surpresa")
    actions = ["aprovar_seleccionadas", "rejeitar_seleccionadas"]

    def origem(self, obj):
        return obj.missao or obj.carta_surpresa

    @admin.action(description="Aprovar actividades seleccionadas")
    def aprovar_seleccionadas(self, request, queryset):
        for actividade in queryset.select_related("participante"):
            actividade.aprovar(por_utilizador=request.user)
        self.message_user(request, f"{queryset.count()} actividade(s) aprovada(s).")

    @admin.action(description="Rejeitar actividades seleccionadas")
    def rejeitar_seleccionadas(self, request, queryset):
        for actividade in queryset.select_related("participante"):
            actividade.rejeitar(por_utilizador=request.user, motivo="Rejeitado em massa pelo painel")
        self.message_user(request, f"{queryset.count()} actividade(s) rejeitada(s).")