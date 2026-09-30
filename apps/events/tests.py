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
