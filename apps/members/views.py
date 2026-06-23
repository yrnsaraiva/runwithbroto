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
            # Save the membership interest
            instance = form.save()

            # Prepare success response
            if is_ajax:
                return JsonResponse({
                    'success': True,
                    'message': 'A tua inscrição foi enviada com sucesso! 🎉'
                })
            else:
                messages.success(
                    request,
                    'A tua inscrição foi enviada com sucesso.'
                )
                return redirect('membro_fundador')
        else:
            # Form has errors
            if is_ajax:
                # Return field errors as JSON
                errors = {
                    field: [str(error) for error in errors]
                    for field, errors in form.errors.items()
                }
                return JsonResponse({
                    'success': False,
                    'errors': errors
                }, status=400)
            else:
                # Standard POST with errors – re-render the page
                # The template will display errors via the form
                return render(
                    request,
                    'members/membro_fundador.html',
                    {'form': form}
                )
    else:
        # GET request – display empty form
        form = InteresseMembroFundadorForm()

    return render(
        request,
        'members/membro_fundador.html',
        {'form': form}
    )