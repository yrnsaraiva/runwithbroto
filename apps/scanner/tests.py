import json
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.events.models import ExternalTicket


class ValidateTicketTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("staff", password="x", is_staff=True)
        self.client.force_login(self.user)
        self.ticket = ExternalTicket.objects.create(
            external_id="TK1", event_id_external="EV1", event_name="Corrida", payment_status="paid")

    def scan(self, qr):
        r = self.client.post(reverse("scanner:validate"), json.dumps({"qr_value": qr}),
                             content_type="application/json")
        return r.json()["status"]

    def test_checkin_once(self):
        self.assertEqual(self.scan("RWB|TK1"), "ok")
        self.assertEqual(self.scan("RWB|TK1"), "already_entered")

    def test_not_paid_not_found_invalid(self):
        ExternalTicket.objects.filter(pk=self.ticket.pk).update(payment_status="pending")
        self.assertEqual(self.scan("RWB|TK1"), "not_paid")
        self.assertEqual(self.scan("RWB|NOPE"), "not_found")
        api = ("QR não reconhecido.", {"result": "invalid_qr", "ticket": None})
        with mock.patch("apps.scanner.views.etk_client.check_in", return_value=api):
            self.assertEqual(self.scan("xxx"), "invalid_qr")

    def test_requires_staff(self):
        self.client.logout()
        r = self.client.post(reverse("scanner:validate"), "{}", content_type="application/json")
        self.assertEqual(r.status_code, 302)


class ApiCheckInTests(TestCase):
    setUp = ValidateTicketTests.setUp
    scan = ValidateTicketTests.scan
    def test_signed_qr_goes_through_api(self):
        api = ("Entrada autorizada.", {"result": "ok", "ticket": {
            "id": "TK1", "payment": "paid", "status": "valid", "entered": True}})
        with mock.patch("apps.scanner.views.etk_client.check_in", return_value=api) as m:
            self.assertEqual(self.scan("TK1|abc123"), "ok")
        m.assert_called_once_with("TK1|abc123")
        self.ticket.refresh_from_db()
        self.assertTrue(self.ticket.entered)  # espelhado localmente

    def test_api_down_returns_502(self):
        with mock.patch("apps.scanner.views.etk_client.check_in", side_effect=Exception("down")):
            r = self.client.post(reverse("scanner:validate"), json.dumps({"qr_value": "TK1|x"}),
                                 content_type="application/json")
        self.assertEqual(r.status_code, 502)
