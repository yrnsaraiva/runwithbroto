from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from .models import Perfil, Assinatura, Pagamento


@login_required
def perfil_view(request):
    perfil, _ = Perfil.objects.get_or_create(user=request.user)

    assinatura = (
        Assinatura.objects
        .filter(usuario=request.user, estado="activa")
        .select_related("plano")
        .first()
    )

    pagamentos = (
        Pagamento.objects
        .filter(assinatura__usuario=request.user)
        .select_related("assinatura", "assinatura__plano")
        .order_by("-pago_em")
    )

    context = {
        "perfil": perfil,
        "assinatura": assinatura,
        "pagamentos": pagamentos,
    }

    return render(request, "members/perfil.html", context)