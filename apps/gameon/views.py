from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import ListView

from .forms import ActividadeForm
from .models import Actividade, Participante


class RankingView(ListView):
    """Ranking público (secção 5 do regulamento). Actualizado a partir do cache de pontos."""

    model = Participante
    template_name = "gameon/ranking.html"
    context_object_name = "participantes"
    paginate_by = 50

    def get_queryset(self):
        return Participante.objects.order_by("-pontos_totais_cache", "nome")


@login_required
def registar_actividade(request):
    """Formulário onde o participante submete uma actividade para verificação."""
    participante = get_object_or_404(Participante, utilizador=request.user)

    if request.method == "POST":
        form = ActividadeForm(request.POST, request.FILES)
        if form.is_valid():
            form.save(participante=participante)
            messages.success(request, "Actividade registada. Aguarda verificação da organização.")
            return redirect("gameon:minhas_actividades")
    else:
        form = ActividadeForm()

    return render(request, "gameon/registar_actividade.html", {"form": form})


@login_required
def minhas_actividades(request):
    participante = get_object_or_404(Participante, utilizador=request.user)
    actividades = participante.actividades.select_related("missao", "carta_surpresa")
    return render(request, "gameon/minhas_actividades.html", {"actividades": actividades})


def _is_staff(user):
    return user.is_staff


@user_passes_test(_is_staff)
def painel_verificacao(request):
    """
    Painel simples para a organização aprovar/rejeitar actividades pendentes,
    sem precisar do admin do Django. Uma linha por actividade, dois botões.
    """
    pendentes = (
        Actividade.objects.filter(estado=Actividade.Estado.PENDENTE)
        .select_related("participante", "missao", "carta_surpresa")
        .order_by("criado_em")
    )
    return render(request, "gameon/painel_verificacao.html", {"actividades": pendentes})


@user_passes_test(_is_staff)
def aprovar_actividade(request, actividade_id):
    actividade = get_object_or_404(Actividade, pk=actividade_id)
    actividade.aprovar(por_utilizador=request.user)
    messages.success(request, f"Actividade de {actividade.participante} aprovada.")
    return redirect("gameon:painel_verificacao")


@user_passes_test(_is_staff)
def rejeitar_actividade(request, actividade_id):
    actividade = get_object_or_404(Actividade, pk=actividade_id)
    motivo = request.POST.get("motivo", "")
    actividade.rejeitar(por_utilizador=request.user, motivo=motivo)
    messages.success(request, f"Actividade de {actividade.participante} rejeitada.")
    return redirect("gameon:painel_verificacao")