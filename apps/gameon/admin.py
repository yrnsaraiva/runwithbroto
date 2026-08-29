from django.contrib import admin
from django.utils import timezone

from unfold.admin import ModelAdmin

from .models import Actividade, CartaAtribuida, CartaSurpresa, Edicao, Missao, Participante


@admin.register(Edicao)
class EdicaoAdmin(ModelAdmin):
    list_display = ("nome", "data_inicio", "data_fim_prevista", "estado", "encerrada_em")
    list_filter = ("estado",)
    list_editable = ("estado",)  # activar/encerrar directamente da lista — o modelo trata de haver só uma activa
    search_fields = ("nome",)
    actions = ["encerrar_seleccionadas"]

    @admin.action(description="Encerrar edição(ões) seleccionada(s)")
    def encerrar_seleccionadas(self, request, queryset):
        for edicao in queryset:
            edicao.encerrar()
        self.message_user(request, f"{queryset.count()} edição(ões) encerrada(s).")


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


@admin.register(CartaAtribuida)
class CartaAtribuidaAdmin(ModelAdmin):
    list_display = ("participante", "carta", "atribuida_em", "usada")
    list_filter = ("usada", "carta__tipo")
    search_fields = ("participante__nome", "participante__telefone")
    autocomplete_fields = ("participante", "carta")


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
    list_display = ("participante", "edicao", "origem", "pontos", "estado", "data_actividade", "revisado_por")
    list_filter = ("edicao", "estado", "missao__categoria", "data_actividade")
    search_fields = ("participante__nome",)
    autocomplete_fields = ("participante", "missao", "carta_surpresa", "edicao")
    list_editable = ("estado",)  # a forma normal de anular/rejeitar: mudar o estado aqui mesmo
    actions = ["rejeitar_seleccionadas"]

    def origem(self, obj):
        return obj.missao or obj.carta_surpresa

    def save_model(self, request, obj, form, change):
        # Regista quem reviu sempre que o estado é alterado à mão no admin
        # (quer pela lista — list_editable — quer pela página de edição).
        # A aprovação em si já não passa por aqui: acontece sozinha ao
        # registar (ver Actividade.save()); isto só regista intervenções manuais.
        if change and "estado" in form.changed_data:
            obj.revisado_por = request.user
            obj.revisado_em = timezone.now()
        super().save_model(request, obj, form, change)

    @admin.action(description="Rejeitar actividades seleccionadas")
    def rejeitar_seleccionadas(self, request, queryset):
        for actividade in queryset.select_related("participante"):
            actividade.estado = Actividade.Estado.REJEITADO
            actividade.revisado_por = request.user
            actividade.revisado_em = timezone.now()
            if not actividade.nota_organizacao:
                actividade.nota_organizacao = "Rejeitado em massa pelo admin"
            actividade.save()  # dispara recálculo de pontos e libertação da carta
        self.message_user(request, f"{queryset.count()} actividade(s) rejeitada(s).")