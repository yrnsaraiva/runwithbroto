from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.db.models import Count, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from .forms import ActividadeForm, ParticipanteIdentificacaoForm
from .models import Actividade, Edicao, Missao, Participante

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


def regulamento(request):
    """Página pública e estática com as regras básicas e os prémios (secções 7 e 9)."""
    return render(request, "gameon/regulamento.html")


def _calcular_vencedores(edicao):
    """
    Categorias vencedoras (secção 6) para uma edição encerrada: soma de
    pontos das actividades aprovadas dessa edição, agrupada por categoria
    de missão. THE CONSISTENT usa a categoria "consistência" (missão
    'Treinar 3 dias consecutivos'); ajusta aqui se quiseres um critério
    mais elaborado (ex.: sequência real de dias activos).
    """
    base = Actividade.objects.filter(edicao=edicao, estado=Actividade.Estado.APROVADO)

    def melhor(categoria=None):
        qs = base.filter(missao__categoria=categoria) if categoria else base
        return (
            qs.values("participante__nome")
            .annotate(total=Sum("pontos"))
            .order_by("-total")
            .first()
        )

    return {
        "fastest": melhor(Missao.Categoria.CORRIDA),
        "consistent": melhor(Missao.Categoria.CONSISTENCIA),
        "community": melhor(Missao.Categoria.COMUNIDADE),
    }


def ranking(request, edicao_id=None):
    """
    Ranking de uma edição — a activa por omissão, ou uma edição encerrada
    específica (histórico). Edições encerradas mostram também os vencedores
    por categoria (secção 6), calculados a partir das actividades dessa
    edição, que já não mudam depois de encerrada.
    """
    if edicao_id:
        edicao = get_object_or_404(Edicao, pk=edicao_id)
    else:
        edicao = Edicao.atual() or Edicao.objects.first()

    participantes = []
    vencedores = {}
    if edicao is not None:
        participantes = list(
            Participante.objects.filter(
                actividades__edicao=edicao, actividades__estado=Actividade.Estado.APROVADO
            )
            .annotate(pontos_edicao=Sum("actividades__pontos"), desafios_edicao=Count("actividades"))
            .order_by("-pontos_edicao", "nome")
            .distinct()
        )

        if edicao.estado == Edicao.Estado.ENCERRADA:
            vencedores = _calcular_vencedores(edicao)

    edicoes = Edicao.objects.all()
    return render(
        request,
        "gameon/ranking.html",
        {"participantes": participantes, "edicao": edicao, "edicoes": edicoes, "vencedores": vencedores},
    )


@participante_required
def registar_actividade(request, participante):
    """Formulário onde o participante submete uma actividade para verificação."""
    edicao_atual = Edicao.atual()
    cartas_disponiveis = participante.cartas_atribuidas.filter(usada=False).select_related("carta")

    if edicao_atual is None:
        # Nenhuma edição activa: mostra a página sem formulário, em vez de
        # deixar o participante submeter algo que não pertence a nenhum jogo.
        return render(
            request,
            "gameon/registar_actividade.html",
            {"form": None, "participante": participante, "edicao_atual": None, "cartas_disponiveis": cartas_disponiveis},
        )

    if request.method == "POST":
        form = ActividadeForm(request.POST, request.FILES, participante=participante)
        if form.is_valid():
            form.save(participante=participante, edicao=edicao_atual)
            messages.success(request, "Actividade registada. Aguarda verificação da organização.")
            return redirect("gameon:minhas_actividades")
    else:
        form = ActividadeForm(participante=participante)

    return render(
        request,
        "gameon/registar_actividade.html",
        {"form": form, "participante": participante, "edicao_atual": edicao_atual, "cartas_disponiveis": cartas_disponiveis},
    )


@participante_required
def minhas_actividades(request, participante):
    actividades = participante.actividades.select_related("missao", "carta_surpresa", "edicao")
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
        .select_related("participante", "missao", "carta_surpresa", "edicao")
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