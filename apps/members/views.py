from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.contrib import messages
from django.http import JsonResponse

from .models import Perfil, Assinatura, Pagamento
from .forms import InteresseMembroFundadorForm


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


def membro_fundador(request):
    if request.method == 'POST':
        form = InteresseMembroFundadorForm(request.POST)
        is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest'

        if form.is_valid():
            form.save()
            if is_ajax:
                return JsonResponse({
                    'success': True,
                    'message': 'A tua inscrição foi enviada com sucesso! 🎉'
                })
            messages.success(request, 'A tua inscrição foi enviada com sucesso.')
            return redirect('membro_fundador')
        else:
            if is_ajax:
                erros_campo = {          # ← nome diferente para evitar shadowing
                    field: [str(e) for e in errs]
                    for field, errs in form.errors.items()
                }
                return JsonResponse({'success': False, 'errors': erros_campo}, status=400)
            return render(request, 'members/membro_fundador.html', {'form': form})

    form = InteresseMembroFundadorForm()
    return render(request, 'members/membro_fundador.html', {'form': form})