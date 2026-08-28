from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.generic import ListView

from .forms import ActividadeForm, ParticipanteIdentificacaoForm
from .models import Actividade, Participante

SESSION_KEY = "gameon_participante_id"


def get_participante_atual(request):
    """Devolve o Participante identificado nesta sessão, ou None."""
    participante_id = request.session.get(SESSION_KEY)
    if not participante_id:
        return None
    return Participante.objects.filter(pk=participante_id).first()


def participante_required(view_func):
    """
    Substitui @login_required para as páginas do participante: não há contas
    nem passwords — só um número de telefone guardado em sessão. Sem ele,
    manda para a identificação e volta depois para onde o participante ia.
    """

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        participante = get_participante_atual(request)
        if participante is None:
            proximo = request.get_full_path()
            return redirect(f"{reverse('gameon:escolher_participante')}?next={proximo}")
        return view_func(request, participante, *args, **kwargs)

    return wrapper


def escolher_participante(request):
    """Identificação por telefone — entra num participante existente ou cria um novo."""
    proximo = request.GET.get("next") or request.POST.get("next") or reverse("gameon:ranking")

    if request.method == "POST":
        form = ParticipanteIdentificacaoForm(request.POST)
        if form.is_valid():
            telefone = form.cleaned_data["telefone"]
            nome = form.cleaned_data["nome"]
            participante, criado = Participante.objects.get_or_create(
                telefone=telefone, defaults={"nome": nome or telefone}
            )
            if criado is False and nome and participante.nome != nome:
                # Deixa o participante actualizar o nome se o escreveu de forma diferente.
                participante.nome = nome
                participante.save(update_fields=["nome"])

            request.session[SESSION_KEY] = str(participante.pk)
            return redirect(proximo)
    else:
        form = ParticipanteIdentificacaoForm()

    return render(request, "gameon/escolher_participante.html", {"form": form, "next": proximo})


def sair_participante(request):
    request.session.pop(SESSION_KEY, None)
    return redirect("gameon:entrar")


class RankingView(ListView):
    """Ranking público (secção 5 do regulamento). Actualizado a partir do cache de pontos."""

    model = Participante
    template_name = "gameon/ranking.html"
    context_object_name = "participantes"
    paginate_by = 50

    def get_queryset(self):
        return Participante.objects.order_by("-pontos_totais_cache", "nome")


@participante_required
def registar_actividade(request, participante):
    """Formulário onde o participante submete uma actividade para verificação."""
    if request.method == "POST":
        form = ActividadeForm(request.POST, request.FILES, participante=participante)
        if form.is_valid():
            form.save(participante=participante)
            messages.success(request, "Actividade registada. Aguarda verificação da organização.")
            return redirect("gameon:minhas_actividades")
    else:
        form = ActividadeForm(participante=participante)

    cartas_disponiveis = participante.cartas_atribuidas.filter(usada=False).select_related("carta")
    return render(
        request,
        "gameon/registar_actividade.html",
        {"form": form, "participante": participante, "cartas_disponiveis": cartas_disponiveis},
    )


@participante_required
def minhas_actividades(request, participante):
    actividades = participante.actividades.select_related("missao", "carta_surpresa")
    return render(
        request, "gameon/minhas_actividades.html", {"actividades": actividades, "participante": participante}
    )


def _is_staff(user):
    return user.is_authenticated and user.is_staff


@user_passes_test(_is_staff, login_url="/admin/login/")
def painel_verificacao(request):
    """
    Painel simples para a organização aprovar/rejeitar actividades pendentes.
    Protegido pelo login do Django admin (já existe em qualquer projecto,
    não precisa de rotas de autenticação próprias).
    """
    pendentes = (
        Actividade.objects.filter(estado=Actividade.Estado.PENDENTE)
        .select_related("participante", "missao", "carta_surpresa")
        .order_by("criado_em")
    )
    return render(request, "gameon/painel_verificacao.html", {"actividades": pendentes})


@user_passes_test(_is_staff, login_url="/admin/login/")
def aprovar_actividade(request, actividade_id):
    actividade = get_object_or_404(Actividade, pk=actividade_id)
    actividade.aprovar(por_utilizador=request.user)
    messages.success(request, f"Actividade de {actividade.participante} aprovada.")
    return redirect("gameon:painel_verificacao")


@user_passes_test(_is_staff, login_url="/admin/login/")
def rejeitar_actividade(request, actividade_id):
    actividade = get_object_or_404(Actividade, pk=actividade_id)
    motivo = request.POST.get("motivo", "")
    actividade.rejeitar(por_utilizador=request.user, motivo=motivo)
    messages.success(request, f"Actividade de {actividade.participante} rejeitada.")
    return redirect("gameon:painel_verificacao")