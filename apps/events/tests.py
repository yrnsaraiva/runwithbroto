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


EVENT = {"id": "EV1", "name": "Corrida", "date": "2099-01-01T08:00:00Z",
         "location": {"province": "Maputo", "details": "Marginal"},
         "prices": [{"id": "PRC1", "amount": 300, "status": "active"}]}
API_TICKET = {"status": "success", "message": "Ticket created successfully",
              "data": {"id": "TK9", "eventId": "EV1", "priceId": "PRC1", "payment": "pending",
                       "status": "valid", "price": {"amount": 300}}}


@mock.patch("apps.events.views._get_event_from_api", return_value=EVENT)
class RegisterFormTests(TestCase):
    url = "/events/event/EV1/inscrever/"
    data = {"full_name": "Ana", "phone": "841234567", "email": "a@b.co",
            "payment": "emola", "external_reference": "a" * 32}

    def test_form_shows_payment_methods(self, _):
        html = self.client.get(self.url).content.decode()
        for m in ("mpesa", "emola", "mkesh"):
            self.assertIn(f'value="{m}"', html)

    def test_payment_method_sent_to_api(self, _):
        with mock.patch("apps.events.views._create_ticket_in_api", return_value=API_TICKET) as m:
            r = self.client.post(self.url, self.data)
        self.assertEqual(r.status_code, 302)
        payload = m.call_args.args[0]
        self.assertEqual(payload["paymentMethod"], "emola")
        self.assertEqual(payload["externalReference"], "a" * 32)

    def test_missing_or_invalid_method_rejected(self, _):
        for bad in ("", "bitcoin"):
            with mock.patch("apps.events.views._create_ticket_in_api") as m:
                r = self.client.post(self.url, {**self.data, "payment": bad})
            self.assertEqual(r.status_code, 400)
            m.assert_not_called()


FREE_EVENT = {**EVENT, "prices": [{"id": "PRC1", "amount": 0, "status": "active"}]}


@mock.patch("apps.events.views._get_event_from_api", return_value=FREE_EVENT)
class FreeTicketFormTests(TestCase):
    url = "/events/event/EV1/inscrever/"
    data = {"full_name": "Ana", "phone": "841234567", "email": "a@b.co",
            "external_reference": "a" * 32}

    def test_form_hides_payment_methods(self, _):
        html = self.client.get(self.url).content.decode()
        for m in ("mpesa", "emola", "mkesh"):
            self.assertNotIn(f'value="{m}"', html)

    def test_no_payment_method_needed_or_sent(self, _):
        with mock.patch("apps.events.views._create_ticket_in_api", return_value=API_TICKET) as m:
            r = self.client.post(self.url, self.data)
        self.assertEqual(r.status_code, 302)
        self.assertNotIn("paymentMethod", m.call_args.args[0])


# ---------------------------------------------------------------------------
# Pré-inscrição + confirmação de presença
# ---------------------------------------------------------------------------

PRE_EVENT = {**EVENT, "registrationMode": "preregistration",
             "confirmationDeadline": "2099-01-05T08:00:00Z",
             "prices": [{"id": "PRC1", "amount": 0, "status": "active"}]}


def api_ticket(tid, name, payment="preregistered", phone="258841111111"):
    return {"id": tid, "eventId": "EV1", "priceId": "PRC1", "payment": payment, "status": "valid",
            "phone": phone, "fullName": name, "amount": 0, "expiresAt": "2099-01-05T08:00:00Z",
            "event": {"id": "EV1", "name": "Corrida", "location": {}}}


@mock.patch("apps.events.views._get_event_from_api", return_value=PRE_EVENT)
class PreRegistrationTests(TestCase):
    reg_url = "/events/event/EV1/inscrever/"
    url = "/events/event/EV1/confirmar/"

    def test_form_is_preregistration_without_payment_method(self, _):
        html = self.client.get(self.reg_url).content.decode()
        self.assertIn("Pré-inscrever-me", html)
        self.assertNotIn('value="mpesa"', html)

    def test_preregistration_saved_locally_and_not_downloadable(self, _):
        resp = {"status": "success", "data": {**api_ticket("TK9", "Ana"), "expiresAt": "2099-01-05T08:00:00Z"}}
        with mock.patch("apps.events.views._create_ticket_in_api", return_value=resp):
            r = self.client.post(self.reg_url, {"full_name": "Ana", "phone": "841111111",
                                                "email": "a@b.co", "external_reference": "a" * 32})
        self.assertEqual(r.status_code, 302)
        t = ExternalTicket.objects.get(external_id="TK9")
        self.assertEqual(t.payment_status, "preregistered")
        self.assertIsNotNone(t.confirmation_deadline)
        page = self.client.get(reverse("events:registration_success", args=[t.public_token]))
        self.assertContains(page, "Pré-inscrição registada")
        self.assertContains(page, "Confirmar presença")
        self.assertEqual(
            self.client.get(reverse("events:download_external_ticket_pdf", args=[t.public_token])).status_code, 404)

    def test_phone_with_several_tickets_lists_each(self, _):
        tickets = [api_ticket("TK1", "Ana Sousa"), api_ticket("TK2", "Rui Costa"),
                   api_ticket("TK3", "Eva Lima", payment="paid")]
        with mock.patch("apps.events.views.etk_client.list_tickets", return_value=tickets) as m:
            r = self.client.post(self.url, {"phone": "84 111 1111"})
        m.assert_called_once_with(event_id="EV1", phone="258841111111")
        html = r.content.decode()
        self.assertIn('value="TK1"', html)
        self.assertIn('value="TK2"', html)
        self.assertNotIn('value="TK3"', html)          # já confirmado: só link
        self.assertIn("Ana S.", html)
        self.assertNotIn("Ana Sousa", html)            # nome mascarado

    def test_confirm_only_selected_tickets(self, _):
        tickets = [api_ticket("TK1", "Ana"), api_ticket("TK2", "Rui")]
        confirmed = api_ticket("TK1", "Ana", payment="paid")
        with mock.patch("apps.events.views.etk_client.list_tickets", return_value=tickets), \
             mock.patch("apps.events.views.etk_client.confirm_ticket", return_value=confirmed) as c:
            r = self.client.post(self.url, {"phone": "841111111", "ticket_ids": ["TK1"]})
        c.assert_called_once_with("TK1", "258841111111")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(ExternalTicket.objects.get(external_id="TK1").payment_status == "paid")
        self.assertFalse(ExternalTicket.objects.filter(external_id="TK2").exists())

    def test_cannot_confirm_ticket_of_another_phone(self, _):
        with mock.patch("apps.events.views.etk_client.list_tickets", return_value=[api_ticket("TK1", "Ana")]), \
             mock.patch("apps.events.views.etk_client.confirm_ticket") as c:
            self.client.post(self.url, {"phone": "841111111", "ticket_ids": ["TK-OUTRO"]})
        c.assert_not_called()

    def test_api_refusal_is_shown_per_ticket(self, _):
        import requests
        resp = mock.Mock(); resp.json.return_value = {"message": "O prazo de confirmação terminou"}
        err = requests.HTTPError(response=resp)
        with mock.patch("apps.events.views.etk_client.list_tickets", return_value=[api_ticket("TK1", "Ana")]), \
             mock.patch("apps.events.views.etk_client.confirm_ticket", side_effect=err):
            r = self.client.post(self.url, {"phone": "841111111", "ticket_ids": ["TK1"]})
        self.assertContains(r, "O prazo de confirmação terminou")

    def test_invalid_phone_rejected(self, _):
        r = self.client.post(self.url, {"phone": "123"})
        self.assertEqual(r.status_code, 400)

    def test_direct_event_has_no_confirmation_page(self, _):
        with mock.patch("apps.events.views._get_event_from_api", return_value=EVENT):
            r = self.client.get(self.url)
        self.assertEqual(r.status_code, 302)

    def test_closed_after_deadline(self, _):
        past = {**PRE_EVENT, "confirmationDeadline": "2000-01-01T00:00:00Z"}
        with mock.patch("apps.events.views._get_event_from_api", return_value=past):
            r = self.client.get(self.url)
        self.assertContains(r, "prazo de confirmação terminou")
