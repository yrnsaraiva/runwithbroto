import json

from django.test import TestCase
from django.urls import reverse

from .models import Product, ProductVariant


class CreateOrderTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(name="Camisola", slug="camisola", price=500, is_active=True)
        self.variant = ProductVariant.objects.create(product=self.product, size="M", stock_qty=2)

    def post(self, **over):
        body = {"name": "Ana", "phone": "258841234567",
                "items": [{"productId": "camisola", "size": "M", "qty": 1}]}
        body.update(over)
        return self.client.post(reverse("store:create_order"), json.dumps(body),
                                content_type="application/json")

    def test_ok_reduces_stock(self):
        self.assertEqual(self.post().status_code, 200)
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_qty, 1)

    def test_invalid_input(self):
        self.assertEqual(self.post(name="").status_code, 400)
        self.assertEqual(self.post(items=[{"productId": "camisola", "size": "M", "qty": "abc"}]).status_code, 400)
        self.assertEqual(self.post(items=[{"productId": "camisola", "size": "M", "qty": 999}]).status_code, 400)
        self.assertEqual(self.post(items=[{"productId": "x", "size": "M", "qty": 1}]).status_code, 400)

    def test_insufficient_stock(self):
        self.assertEqual(self.post(items=[{"productId": "camisola", "size": "M", "qty": 5}]).status_code, 409)
