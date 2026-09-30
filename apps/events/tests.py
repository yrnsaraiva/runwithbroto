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
             "confirmationOpensAt": "2000-01-01T00:00:00Z", "confirmationOpen": True,
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

    def test_confirmation_link_hidden_until_organizer_opens_it(self, _):
        shut = {**PRE_EVENT, "confirmationOpen": False, "confirmationOpensAt": None}
        t = make_ticket(external_id="TKP", payment_status="preregistered", event_id_external="EV1")
        with mock.patch("apps.events.views._get_event_from_api", return_value=shut):
            detail = self.client.get("/events/event/EV1/")
            success = self.client.get(reverse("events:registration_success", args=[t.public_token]))
        self.assertNotIn("/confirmar/", detail.content.decode())
        self.assertContains(detail, "será aberta mais perto do evento")
        self.assertNotIn("Confirmar presença", success.content.decode())
        # e com a confirmação aberta o link aparece nas duas páginas
        detail = self.client.get("/events/event/EV1/")
        success = self.client.get(reverse("events:registration_success", args=[t.public_token]))
        self.assertIn("/confirmar/", detail.content.decode())
        self.assertContains(success, "Confirmar presença")

    def test_confirmation_page_does_nothing_until_open(self, _):
        shut = {**PRE_EVENT, "confirmationOpen": False, "confirmationOpensAt": None}
        with mock.patch("apps.events.views._get_event_from_api", return_value=shut), \
             mock.patch("apps.events.views.etk_client.list_tickets") as lst, \
             mock.patch("apps.events.views.etk_client.confirm_ticket") as conf:
            get = self.client.get(self.url)
            post = self.client.post(self.url, {"phone": "841111111", "ticket_ids": ["TK1"]})
        self.assertContains(get, "ainda não está aberta")
        self.assertContains(post, "ainda não está aberta")
        lst.assert_not_called()
        conf.assert_not_called()

    def test_closed_after_deadline(self, _):
        past = {**PRE_EVENT, "confirmationDeadline": "2000-01-01T00:00:00Z"}
        with mock.patch("apps.events.views._get_event_from_api", return_value=past):
            r = self.client.get(self.url)
        self.assertContains(r, "prazo de confirmação terminou")


# ---------------------------------------------------------------------------
# Painel de convites (admin)
# ---------------------------------------------------------------------------
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import override_settings

INVITE_EVENT = {**EVENT, "prices": [{"id": "PRC1", "name": "Geral", "amount": 0,
                                     "status": "active", "available": 5}]}


def api_invite(tid, name="Ana", email="ana@x.co", phone="258841111111", note="Patrocinador"):
    return {"id": tid, "eventId": "EV1", "priceId": "PRC1", "payment": "invited", "status": "valid",
            "isInvite": True, "phone": phone, "fullName": name, "email": email, "note": note,
            "amount": 0, "qrValue": f"{tid}|sig",
            "event": {"id": "EV1", "name": "Corrida", "date": "2099-01-01T08:00:00Z",
                      "location": {"province": "Maputo", "details": "Marginal"}}}


@mock.patch("apps.events.admin.etk_client.get_events", return_value=[INVITE_EVENT])
class InvitePanelTests(TestCase):
    url = "/admin/events/externalticket/invites/"

    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser("root", "r@x.co", "Pa$$w0rd!123")
        self.client.force_login(self.admin)
        self.data = {"lote": "EV1|PRC1", "quantity": "2", "name": "Ana", "email": "ana@x.co",
                     "phone": "84 111 1111", "note": "Patrocinador"}

    def post(self, **over):
        return self.client.post(self.url, {**self.data, **over})

    def test_form_lists_events_and_lots_with_spots(self, _):
        html = self.client.get(self.url).content.decode()
        self.assertIn('value="EV1|PRC1"', html)
        self.assertIn("5 vagas", html)

    def test_requires_staff_login(self, _):
        self.client.logout()
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 302)
        self.assertIn("/login/", r["Location"])

    def test_creates_invites_via_api_and_saves_them_locally(self, _):
        with mock.patch("apps.events.invites.etk_client.create_invites",
                        return_value=[api_invite("TKI1"), api_invite("TKI2")]) as api:
            r = self.post()
        self.assertRedirects(r, self.url, fetch_redirect_response=False)
        payload = api.call_args.args[0]
        self.assertEqual(payload, {"eventId": "EV1", "priceId": "PRC1", "quantity": 2,
                                   "holderName": "Ana", "holderEmail": "ana@x.co",
                                   "phone": "258841111111", "note": "Patrocinador"})
        tickets = ExternalTicket.objects.filter(payment_status="invited")
        self.assertEqual(tickets.count(), 2)
        self.assertEqual(tickets[0].note, "Patrocinador")
        self.assertEqual(tickets[0].buyer_email, "ana@x.co")

    def test_api_refusal_is_shown_and_nothing_saved(self, _):
        import requests
        resp = mock.Mock(); resp.json.return_value = {"message": "Só restam 1 vaga(s) neste lote."}
        with mock.patch("apps.events.invites.etk_client.create_invites",
                        side_effect=requests.HTTPError(response=resp)):
            r = self.post()
        self.assertEqual(r.status_code, 400)
        self.assertContains(r, "Só restam 1 vaga(s)", status_code=400)
        self.assertFalse(ExternalTicket.objects.exists())

    def test_validation_blocks_the_api_call(self, _):
        for bad in ({"lote": ""}, {"quantity": "0"}, {"quantity": "999"}, {"phone": "123"},
                    {"email": "nao-e-email"},
                    {"quantity": "1", "name": "", "email": "", "phone": "", "note": ""}):
            with mock.patch("apps.events.invites.etk_client.create_invites") as api:
                r = self.post(**bad)
            self.assertEqual(r.status_code, 400, bad)
            api.assert_not_called()

    @override_settings(EMAIL_HOST="smtp.test", EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_email_sent_once_with_link_and_a_pdf_per_invite(self, _):
        with mock.patch("apps.events.invites.etk_client.create_invites",
                        return_value=[api_invite("TKI1"), api_invite("TKI2")]):
            self.post()
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertEqual(msg.to, ["ana@x.co"])
        self.assertEqual(len(msg.attachments), 2)
        self.assertEqual(msg.body.count("/tickets/"), 2)
        self.assertTrue(all(t.invite_sent_at for t in ExternalTicket.objects.all()))

    @override_settings(EMAIL_HOST="")
    def test_no_email_when_not_configured(self, _):
        with mock.patch("apps.events.invites.etk_client.create_invites",
                        return_value=[api_invite("TKI1")]):
            r = self.post(quantity="1")
        self.assertEqual(len(mail.outbox), 0)
        self.assertFalse(ExternalTicket.objects.get().invite_sent_at)
        page = self.client.get(self.url).content.decode()
        self.assertIn("EMAIL_HOST", page)
        self.assertNotIn("Enviar e-mail", page)

    @override_settings(EMAIL_HOST="smtp.test", EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
                       SITE_BASE_URL="https://runwithbroto.test")
    def test_list_has_link_pdf_whatsapp_and_resend(self, _):
        t = make_ticket(external_id="TKI9", payment_status="invited", buyer_name="Rui",
                        buyer_email="rui@x.co", buyer_phone="258842222222", note="Imprensa",
                        event_name="Corrida")
        html = self.client.get(self.url).content.decode()
        self.assertIn(f"https://runwithbroto.test/events/tickets/{t.public_token}/success/", html)
        self.assertIn("https://wa.me/258842222222?text=", html)
        self.assertIn("Enviar e-mail", html)
        self.assertIn("Imprensa", html)
        r = self.client.post(f"{self.url}{t.pk}/send/")
        self.assertRedirects(r, self.url, fetch_redirect_response=False)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Reenviar e-mail", self.client.get(self.url).content.decode())

    def test_only_invites_are_listed(self, _):
        make_ticket(external_id="TKP", payment_status="paid", buyer_name="Comprador")
        make_ticket(external_id="TKI", payment_status="invited", buyer_name="Convidado")
        html = self.client.get(self.url).content.decode()
        self.assertIn("Convidado", html)
        self.assertNotIn("Comprador", html)

    def test_changelist_with_event_filter_still_works(self, _):
        """Regressão: o get_urls duplicado escondia as rotas da lista de check-in."""
        make_ticket(external_id="TKX", event_name="Corrida")
        r = self.client.get("/admin/events/externalticket/", {"event_name__exact": "Corrida"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("/checkin-list/pdf/", r.context["checkin_pdf_url"])
        self.assertEqual(self.client.get(r.context["checkin_csv_url"]).status_code, 200)


# ---------------------------------------------------------------------------
# Tipo do bilhete (lote da API, nunca fixo) e PDF
# ---------------------------------------------------------------------------
import unittest

try:                                    # só para ler o texto dos PDFs nos testes
    import fitz
except ImportError:                     # pragma: no cover
    fitz = None

needs_fitz = unittest.skipUnless(fitz, "pymupdf não instalado (só usado para testar o texto dos PDFs)")


class TicketTypeTests(TestCase):
    def test_type_comes_from_the_price_name(self):
        self.assertEqual(make_ticket(external_id="A", price_name="VIP").ticket_type, "VIP")
        self.assertEqual(make_ticket(external_id="B", price_name="Early bird").ticket_type, "Early bird")

    def test_invite_type(self):
        inv = dict(payment_status="invited")
        self.assertEqual(make_ticket(external_id="A", price_name="Geral", **inv).ticket_type, "Convite")
        self.assertEqual(make_ticket(external_id="B", price_name="", **inv).ticket_type, "Convite")
        self.assertEqual(make_ticket(external_id="C", price_name="VIP", **inv).ticket_type, "Convite · VIP")

    def test_old_tickets_without_a_synced_lot_keep_the_old_label(self):
        self.assertEqual(make_ticket(external_id="A", price_name="").ticket_type, "Entrada")

    def test_sync_fills_and_updates_the_type(self):
        from .sync import apply_api_ticket, ensure_local_ticket
        t = make_ticket(external_id="TKS", price_name="")
        apply_api_ticket({"id": "TKS", "payment": "paid", "price": {"name": "VIP"}})
        t.refresh_from_db()
        self.assertEqual(t.price_name, "VIP")
        # actualização sem preço não apaga o tipo já conhecido
        apply_api_ticket({"id": "TKS", "payment": "paid"})
        t.refresh_from_db()
        self.assertEqual(t.price_name, "VIP")
        novo = ensure_local_ticket({"id": "TKN", "eventId": "EV1", "payment": "invited",
                                    "price": {"name": "Imprensa"}, "event": {}})
        self.assertEqual(novo.ticket_type, "Convite · Imprensa")

    @mock.patch("apps.events.views._get_event_from_api", return_value=EVENT)
    def test_registration_stores_the_lot_name(self, _):
        api = {"status": "success", "data": {"id": "TK7", "eventId": "EV1", "priceId": "PRC1",
               "payment": "pending", "status": "valid", "price": {"amount": 300, "name": "VIP"}}}
        with mock.patch("apps.events.views._create_ticket_in_api", return_value=api):
            self.client.post("/events/event/EV1/inscrever/", {
                "full_name": "Ana", "phone": "841234567", "email": "a@b.co",
                "payment": "mpesa", "external_reference": "a" * 32})
        self.assertEqual(ExternalTicket.objects.get(external_id="TK7").price_name, "VIP")

    def test_success_page_shows_the_type(self):
        t = make_ticket(price_name="VIP")
        html = self.client.get(reverse("events:registration_success", args=[t.public_token])).content.decode()
        self.assertIn("VIP", html)

    @needs_fitz
    def test_pdf_text_uses_the_type_and_not_the_old_hardcoded_one(self):
        from .pdf import build_external_ticket_pdf

        def text(**kw):
            t = make_ticket(external_id=kw.pop("eid"), event_name="Corrida", **kw)
            doc = fitz.open(stream=build_external_ticket_pdf(t), filetype="pdf")
            return doc[0].get_text()

        vip = text(eid="P1", price_name="VIP", price_amount=500, tamanho_camisete="L")
        self.assertIn("VIP", vip)
        self.assertNotIn("ENTRADA", vip)
        self.assertIn("500,00 MZN", vip)
        self.assertIn("CAMISETE", vip)
        conv = text(eid="P2", payment_status="invited", price_name="Geral", tamanho_camisete="")
        self.assertIn("CONVITE", conv)
        self.assertNotIn("0,00 MZN", conv)
        self.assertNotIn("CAMISETE", conv)               # sem tamanho, sem linha
        self.assertNotIn("confirmação de pagamento", conv)
        gratis = text(eid="P3", price_name="Geral", price_amount=0)
        self.assertIn("Gratuito", gratis)

    def test_scanner_payload_includes_the_type(self):
        from apps.scanner.views import _ticket_info
        self.assertEqual(_ticket_info(make_ticket(price_name="VIP"))["ticket_type"], "VIP")

    @needs_fitz
    def test_checkin_list_pdf_has_a_type_column(self):
        from .pdfs_external_checkin import build_external_checkin_list_pdf
        pdf = build_external_checkin_list_pdf("Corrida", [make_ticket(price_name="VIP")])
        self.assertIn("VIP", fitz.open(stream=pdf, filetype="pdf")[0].get_text())


# ---------------------------------------------------------------------------
# Camisetes: nem todos os eventos têm
# ---------------------------------------------------------------------------
SHIRT_EVENT = {**EVENT, "offersShirts": True}


class ShirtTests(TestCase):
    reg_url = "/events/event/EV1/inscrever/"
    data = {"full_name": "Ana", "phone": "841234567", "email": "a@b.co",
            "payment": "mpesa", "external_reference": "a" * 32}

    def post(self, event, **over):
        with mock.patch("apps.events.views._get_event_from_api", return_value=event), \
             mock.patch("apps.events.views._create_ticket_in_api", return_value=API_TICKET) as api:
            r = self.client.post(self.reg_url, {**self.data, **over})
        return r, api

    def test_form_asks_for_the_size_only_when_the_event_has_shirts(self):
        with mock.patch("apps.events.views._get_event_from_api", return_value=SHIRT_EVENT):
            with_shirts = self.client.get(self.reg_url).content.decode()
        with mock.patch("apps.events.views._get_event_from_api", return_value=EVENT):
            without = self.client.get(self.reg_url).content.decode()
        self.assertIn('name="tamanho_camisete"', with_shirts)
        for size in ("S", "M", "L", "XL"):
            self.assertIn(f'value="{size}"', with_shirts)
        self.assertNotIn("tamanho_camisete", without)

    def test_size_is_required_when_the_event_has_shirts(self):
        for bad in ("", "XXL"):
            r, api = self.post(SHIRT_EVENT, tamanho_camisete=bad)
            self.assertEqual(r.status_code, 400, bad)
            api.assert_not_called()
        self.assertContains(r, "Escolha o tamanho da camisete", status_code=400)

    def test_size_is_saved_for_events_with_shirts(self):
        r, _ = self.post(SHIRT_EVENT, tamanho_camisete="L")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(ExternalTicket.objects.get(external_id="TK9").tamanho_camisete, "L")

    def test_chosen_size_survives_a_validation_error(self):
        with mock.patch("apps.events.views._get_event_from_api", return_value=SHIRT_EVENT):
            r = self.client.post(self.reg_url, {**self.data, "phone": "123", "tamanho_camisete": "XL"})
        self.assertEqual(r.status_code, 400)
        self.assertRegex(r.content.decode(), r'value="XL"\s+checked')

    def test_no_size_is_stored_for_events_without_shirts(self):
        r, _ = self.post(EVENT, tamanho_camisete="L")          # valor forçado no POST é ignorado
        self.assertEqual(r.status_code, 302)
        self.assertEqual(ExternalTicket.objects.get(external_id="TK9").tamanho_camisete, "")

    def test_tickets_created_by_sync_have_no_default_size(self):
        from .sync import ensure_local_ticket
        t = ensure_local_ticket({"id": "TKN", "eventId": "EV1", "payment": "invited", "event": {}})
        self.assertEqual(t.tamanho_camisete, "")
        self.assertEqual(ExternalTicket().tamanho_camisete, "")

    def test_sync_clears_the_old_default_size_only_for_events_without_shirts(self):
        from .sync import apply_api_ticket
        a = make_ticket(external_id="A", tamanho_camisete="M")
        b = make_ticket(external_id="B", tamanho_camisete="M")
        c = make_ticket(external_id="C", tamanho_camisete="M")
        apply_api_ticket({"id": "A", "payment": "paid", "event": {"offersShirts": False}})
        apply_api_ticket({"id": "B", "payment": "paid", "event": {"offersShirts": True}})
        apply_api_ticket({"id": "C", "payment": "paid"})                   # API antiga: não sabemos
        for t in (a, b, c):
            t.refresh_from_db()
        self.assertEqual((a.tamanho_camisete, b.tamanho_camisete, c.tamanho_camisete), ("", "M", "M"))

    def test_pdf_and_scanner_hide_the_size_when_there_is_none(self):
        from apps.scanner.views import _ticket_info
        self.assertEqual(_ticket_info(make_ticket(tamanho_camisete=""))["tamanho_camisete"], "—")
        self.assertEqual(_ticket_info(make_ticket(external_id="B", tamanho_camisete="L"))["tamanho_camisete"],
                         "Grande (L)")


@mock.patch("apps.events.admin.etk_client.get_events", return_value=[INVITE_EVENT])
class InviteShirtTests(TestCase):
    url = "/admin/events/externalticket/invites/"

    def setUp(self):
        self.client.force_login(get_user_model().objects.create_superuser("root", "r@x.co", "Pa$$w0rd!123"))
        self.data = {"lote": "EV1|PRC1", "quantity": "1", "name": "Ana", "size": "XL"}

    def test_form_offers_an_optional_size(self, _):
        html = self.client.get(self.url).content.decode()
        self.assertIn('name="size"', html)
        self.assertIn("só eventos com camisetes", html)

    def test_size_is_saved_on_the_invites(self, _):
        with mock.patch("apps.events.invites.etk_client.create_invites", return_value=[api_invite("TKI1")]):
            self.client.post(self.url, self.data)
        self.assertEqual(ExternalTicket.objects.get().tamanho_camisete, "XL")

    def test_no_size_by_default(self, _):
        with mock.patch("apps.events.invites.etk_client.create_invites", return_value=[api_invite("TKI1")]):
            self.client.post(self.url, {**self.data, "size": ""})
        self.assertEqual(ExternalTicket.objects.get().tamanho_camisete, "")

    def test_invalid_size_is_rejected(self, _):
        with mock.patch("apps.events.invites.etk_client.create_invites") as api:
            r = self.client.post(self.url, {**self.data, "size": "XXL"})
        self.assertEqual(r.status_code, 400)
        api.assert_not_called()


class FlashMessagesTests(TestCase):
    """Os erros de validação do formulário chegam mesmo ao utilizador."""

    @mock.patch("apps.events.views._get_event_from_api", return_value=EVENT)
    def test_validation_errors_are_shown_on_the_form(self, _):
        r = self.client.post("/events/event/EV1/inscrever/", {"phone": "123", "payment": "mpesa"})
        self.assertContains(r, "Número inválido", status_code=400)

    @mock.patch("apps.events.views._get_event_from_api", return_value=EVENT)
    def test_api_refusal_is_shown_on_the_form(self, _):
        import requests
        resp = mock.Mock(status_code=402); resp.json.return_value = {"message": "Saldo insuficiente."}
        with mock.patch("apps.events.views._create_ticket_in_api",
                        side_effect=requests.HTTPError(response=resp)):
            r = self.client.post("/events/event/EV1/inscrever/", {
                "full_name": "Ana", "phone": "841234567", "email": "a@b.co", "payment": "mpesa",
                "external_reference": "a" * 32})
        self.assertContains(r, "Saldo insuficiente.", status_code=402)
