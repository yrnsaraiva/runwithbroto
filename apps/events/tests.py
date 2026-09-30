from unittest import mock

from django.test import TestCase
from django.urls import reverse

from .models import ExternalTicket


def make_ticket(**kw):
    defaults = dict(external_id="TK1", event_id_external="EV1", event_name="Corrida",
                    payment_status="paid", buyer_name="Ana")
    defaults.update(kw)
    return ExternalTicket.objects.create(**defaults)


class TicketAccessTests(TestCase):
    def test_success_and_download_need_token(self):
        t = make_ticket()
        self.assertEqual(self.client.get(reverse("events:registration_success", args=[t.public_token])).status_code, 200)
        with mock.patch("apps.events.views.build_external_ticket_pdf", return_value=b"%PDF"):
            r = self.client.get(reverse("events:download_external_ticket_pdf", args=[t.public_token]))
        self.assertEqual(r.status_code, 200)

    def test_sequential_id_no_longer_works(self):
        make_ticket()
        self.assertEqual(self.client.get("/events/tickets/1/download/").status_code, 404)
        self.assertEqual(self.client.get("/events/EV1/success/").status_code, 404)


import hashlib
import hmac
import json

from django.test import override_settings


@override_settings(ETICKETS_WEBHOOK_SECRET="segredo")
class WebhookTests(TestCase):
    def post(self, body, sig=None):
        raw = json.dumps(body).encode()
        sig = sig or hmac.new(b"segredo", raw, hashlib.sha256).hexdigest()
        return self.client.post(reverse("events:etk_webhook"), raw,
                                content_type="application/json", HTTP_X_ETK_SIGNATURE=sig)

    def test_paid_webhook_updates_ticket(self):
        t = make_ticket(payment_status="pending")
        r = self.post({"event": "ticket.paid", "data": {"id": "TK1", "payment": "paid",
                                                        "status": "valid", "qrValue": "TK1|sig"}})
        self.assertEqual(r.status_code, 200)
        t.refresh_from_db()
        self.assertEqual((t.payment_status, t.qr_value), ("paid", "TK1|sig"))

    def test_bad_signature_rejected(self):
        t = make_ticket(payment_status="pending")
        self.assertEqual(self.post({"data": {"id": "TK1", "payment": "paid"}}, sig="x").status_code, 401)
        t.refresh_from_db()
        self.assertEqual(t.payment_status, "pending")

    @override_settings(ETICKETS_WEBHOOK_SECRET="")
    def test_unconfigured_secret(self):
        self.assertEqual(self.post({"data": {}}).status_code, 503)


class StatusPollingTests(TestCase):
    def test_polls_api_until_paid(self):
        t = make_ticket(payment_status="pending")
        api = {"id": "TK1", "payment": "paid", "status": "valid"}
        with mock.patch("apps.events.views.etk_client.get_ticket", return_value=api):
            r = self.client.get(reverse("events:ticket_status", args=[t.public_token]))
        self.assertTrue(r.json()["paid"])
        t.refresh_from_db()
        self.assertEqual(t.payment_status, "paid")

    def test_api_down_keeps_pending(self):
        t = make_ticket(payment_status="pending")
        with mock.patch("apps.events.views.etk_client.get_ticket", side_effect=Exception("down")):
            r = self.client.get(reverse("events:ticket_status", args=[t.public_token]))
        self.assertFalse(r.json()["paid"])
