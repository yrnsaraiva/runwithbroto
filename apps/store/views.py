import json
from decimal import Decimal

from django.db import transaction
from django.db.models import F
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from .models import Order, Product, ProductVariant


def store_list(request):
    products = Product.objects.filter(is_active=True).prefetch_related("variants", "images")

    products_data = []
    for p in products:
        gallery_images = [p.image.url] if p.image else []
        gallery_images += [img.image.url for img in p.images.all()]

        variants = [
            {
                "size": v.size,
                "sizeLabel": v.get_size_display(),
                "price": float(v.get_final_price()),
                "stock": v.stock_qty,
                "soldOut": not v.is_in_stock(),
            }
            for v in p.variants.filter(is_active=True).order_by("size")
        ]
        products_data.append(
            {
                "id": p.slug,
                "name": p.name,
                "category": p.category,
                "price": float(p.price),
                "variants": variants,
                "blurb": p.description,
                "image": gallery_images[0] if gallery_images else "",
                "images": gallery_images,
                "badge": p.badge,
                "soldOut": p.is_sold_out(),
            }
        )

    return render(
        request,
        "store/store.html",
        {"products_json": json.dumps(products_data)},
    )


@require_POST
def create_order(request):
    """
    Recebe o carrinho em JSON, valida e reserva o stock de cada variação de
    forma atómica (select_for_update evita vender o mesmo tamanho a duas
    pessoas ao mesmo tempo), grava a Order, e só depois o JS abre o WhatsApp.
    Se algum item já não tiver stock suficiente, devolve 409 com detalhes
    para o frontend mostrar ao cliente sem criar a encomenda.
    """
    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "payload inválido"}, status=400)

    items = payload.get("items", [])
    if not items:
        return JsonResponse({"error": "carrinho vazio"}, status=400)

    slugs = [i.get("productId") for i in items]

    with transaction.atomic():
        products = {p.slug: p for p in Product.objects.filter(slug__in=slugs)}

        sizes = [i.get("size") for i in items if i.get("size")]
        variants_qs = (
            ProductVariant.objects.select_for_update()
            .select_related("product")
            .filter(product__slug__in=slugs, size__in=sizes)
        )
        variants_by_key = {(v.product.slug, v.size): v for v in variants_qs}

        subtotal = Decimal("0")
        snapshot = []
        stock_errors = []

        for item in items:
            slug = item.get("productId")
            product = products.get(slug)
            if not product:
                continue

            qty = max(1, int(item.get("qty", 1)))
            size = item.get("size")
            variant = variants_by_key.get((slug, size))

            if variant:
                if variant.stock_qty < qty:
                    stock_errors.append(
                        {
                            "productId": slug,
                            "name": product.name,
                            "size": size,
                            "available": variant.stock_qty,
                            "requested": qty,
                        }
                    )
                    continue
                unit_price = variant.get_final_price()
            else:
                unit_price = product.price

            line_total = unit_price * qty
            subtotal += line_total
            snapshot.append(
                {
                    "productId": slug,
                    "name": product.name,
                    "size": size,
                    "qty": qty,
                    "price": float(unit_price),
                    "lineTotal": float(line_total),
                }
            )

        if stock_errors:
            return JsonResponse({"error": "stock insuficiente", "stockErrors": stock_errors}, status=409)

        if not snapshot:
            return JsonResponse({"error": "nenhum produto válido"}, status=400)

        for item in snapshot:
            variant = variants_by_key.get((item["productId"], item["size"]))
            if variant:
                ProductVariant.objects.filter(pk=variant.pk).update(stock_qty=F("stock_qty") - item["qty"])

        order = Order.objects.create(
            customer_name=payload.get("name", ""),
            customer_phone=payload.get("phone", ""),
            items_snapshot=snapshot,
            subtotal=subtotal,
        )

    return JsonResponse({"orderId": order.order_id, "subtotal": float(subtotal)})