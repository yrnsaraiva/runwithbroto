import json
from decimal import Decimal

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from .models import Order, Product


def store_list(request):
    products = Product.objects.filter(is_active=True)

    products_data = [
        {
            "id": p.slug,
            "name": p.name,
            "category": p.category,
            "price": float(p.price),
            "sizes": p.sizes_list(),
            "blurb": p.description,
            "image": p.image.url if p.image else "",
            "badge": p.badge,
            "soldOut": p.sold_out,
        }
        for p in products
    ]

    return render(
        request,
        "store/store.html",
        {"products_json": json.dumps(products_data)},
    )


@require_POST
def create_order(request):
    """
    Recebe o carrinho em JSON (enviado pelo JS antes de abrir o WhatsApp) e
    grava uma Order para ficares com registo, mesmo sem gateway de pagamento.
    """
    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "payload inválido"}, status=400)

    items = payload.get("items", [])
    if not items:
        return JsonResponse({"error": "carrinho vazio"}, status=400)

    slugs = [i.get("productId") for i in items]
    products = {p.slug: p for p in Product.objects.filter(slug__in=slugs)}

    subtotal = Decimal("0")
    snapshot = []
    for item in items:
        product = products.get(item.get("productId"))
        if not product:
            continue
        qty = max(1, int(item.get("qty", 1)))
        line_total = product.price * qty
        subtotal += line_total
        snapshot.append(
            {
                "name": product.name,
                "size": item.get("size"),
                "qty": qty,
                "price": float(product.price),
                "lineTotal": float(line_total),
            }
        )

    if not snapshot:
        return JsonResponse({"error": "nenhum produto válido"}, status=400)

    order = Order.objects.create(
        customer_name=payload.get("name", ""),
        customer_phone=payload.get("phone", ""),
        items_snapshot=snapshot,
        subtotal=subtotal,
    )

    return JsonResponse({"orderId": order.id, "subtotal": float(subtotal)})
