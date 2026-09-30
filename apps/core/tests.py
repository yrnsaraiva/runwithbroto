import json
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.events.models import ExternalTicket
from apps.scanner.models import CheckInLog

User = get_user_model()


def ticket(n, event="EV1", name="Corrida", payment="paid", amount=0, phone=None, size="M",
           entered=False, days_ago=0):
    when = timezone.now() - timedelta(days=days_ago)
    return ExternalTicket.objects.create(
        external_id=f"TK{n}", event_id_external=event, event_name=name, payment_status=payment,
        price_amount=amount, buyer_phone=phone or f"2588400000{n:02d}", buyer_name=f"Pessoa {n}",
        tamanho_camisete=size, entered=entered, external_created_at=when)


class DashboardTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("root", "r@x.co", "Pa$$w0rd!123")
        self.client.force_login(self.admin)

    def get(self, **params):
        r = self.client.get(reverse("admin:index"), params)
        self.assertEqual(r.status_code, 200)
        return r

    def kpi(self, r, title):
        return next((k for k in r.context["kpis"] if k["title"] == title), None)

    def test_empty_database_renders(self):
        r = self.get()
        self.assertEqual(self.kpi(r, "Inscrições")["metric"], "0")
        self.assertIsNone(self.kpi(r, "Por confirmar"))     # só aparece se houver
        self.assertIsNone(self.kpi(r, "Receita"))

    def test_kpis_count_states_people_entries_and_revenue(self):
        ticket(1, payment="paid", amount=300, phone="258841111111", entered=True)
        ticket(2, payment="paid", amount=300, phone="258841111111")      # mesma pessoa
        ticket(3, payment="invited")
        ticket(4, payment="preregistered")
        ticket(5, payment="pending")
        ticket(6, payment="refunded")
        r = self.get()
        self.assertEqual(self.kpi(r, "Inscrições")["metric"], "6")
        self.assertEqual(self.kpi(r, "Confirmados")["metric"], "3")            # paid + invited
        self.assertEqual(self.kpi(r, "Confirmados")["footer"], "50% das inscrições")
        self.assertEqual(self.kpi(r, "Por confirmar")["metric"], "1")
        self.assertEqual(self.kpi(r, "Pagamento pendente")["metric"], "1")
        self.assertEqual(self.kpi(r, "Pessoas (telefones únicos)")["metric"], "5")
        entradas = self.kpi(r, "Entradas (check-in)")
        self.assertEqual(entradas["metric"], "1")
        self.assertEqual(entradas["footer"], "33% dos confirmados")
        self.assertEqual(self.kpi(r, "Receita")["metric"], "600 MZN")
        self.assertIn("300 MZN", self.kpi(r, "Receita")["footer"])            # ticket médio

    def test_event_filter_applies_to_everything(self):
        ticket(1, event="EV1", name="Corrida")
        ticket(2, event="EV2", name="Trail")
        ticket(3, event="EV2", name="Trail")
        self.assertEqual(self.kpi(self.get(), "Inscrições")["metric"], "3")
        self.assertEqual(self.kpi(self.get(evento="EV2"), "Inscrições")["metric"], "2")
        self.assertEqual(len(self.get().context["filtro_eventos"]), 2)

    def test_daily_series_and_cumulative_respect_period(self):
        ticket(1, days_ago=0)
        ticket(2, days_ago=0)
        ticket(3, days_ago=2)
        ticket(4, days_ago=20)                     # fora dos 7 dias, conta no acumulado
        r = self.get(dias=7)
        diario = json.loads(r.context["diarioChartData"])["datasets"][0]["data"]
        acum = json.loads(r.context["acumuladoChartData"])["datasets"][0]["data"]
        self.assertEqual(len(diario), 7)
        self.assertEqual(sum(diario), 3)
        self.assertEqual(diario[-1], 2)
        self.assertEqual(acum[0], 1)               # o bilhete de há 20 dias
        self.assertEqual(acum[-1], 4)

    def test_invalid_filters_fall_back_to_defaults(self):
        ticket(1)
        r = self.get(dias="abc", evento="nao-existe")
        self.assertEqual(r.context["filtro_dias"], 30)
        self.assertEqual(self.kpi(r, "Inscrições")["metric"], "0")

    def test_all_time_period(self):
        ticket(1, days_ago=100)
        r = self.get(dias=0)
        labels = json.loads(r.context["diarioChartData"])["labels"]
        self.assertGreaterEqual(len(labels), 101)

    def test_shirt_sizes_count_only_tickets_holding_a_spot(self):
        ticket(1, size="L")
        ticket(2, size="L", payment="preregistered")
        ticket(3, size="XL", payment="refunded")   # não ocupa vaga
        r = self.get()
        dados = json.loads(r.context["camisetesChartData"])
        self.assertEqual(dict(zip(dados["labels"], dados["datasets"][0]["data"]))["L"], 2)
        self.assertEqual(dict(zip(dados["labels"], dados["datasets"][0]["data"]))["XL"], 0)

    def test_status_chart_groups_states(self):
        ticket(1, payment="paid")
        ticket(2, payment="invited")
        ticket(3, payment="failed")
        ticket(4, payment="review")
        dados = json.loads(self.get().context["estadoChartData"])
        contagem = dict(zip(dados["labels"], dados["datasets"][0]["data"]))
        self.assertEqual(contagem["Confirmados"], 2)
        self.assertEqual(contagem["Falhados / em revisão"], 2)
        self.assertNotIn("Reembolsados", contagem)             # sem zeros

    def test_checkin_metrics_by_hour_result_and_gatekeeper(self):
        t = ticket(1, event="EV1")
        other = ticket(2, event="EV2")
        for tk, result in [(t, "ok"), (t, "already_entered"), (other, "ok")]:
            CheckInLog.objects.create(ticket_external_id=tk.external_id, result=result,
                                      scanned_by=self.admin)
        r = self.get(evento="EV1")
        horas = json.loads(r.context["horasChartData"])["datasets"][0]["data"]
        self.assertEqual(sum(horas), 1)
        scans = dict(r.context["table_scans"]["rows"])
        self.assertEqual(scans, {"Entrada autorizada": "1", "Já tinha entrado": "1"})
        self.assertEqual(r.context["table_porteiros"]["rows"], [["root", "1"]])
        self.assertEqual(sum(json.loads(self.get().context["horasChartData"])["datasets"][0]["data"]), 2)

    def test_no_checkin_cards_without_scans(self):
        r = self.get()
        self.assertIsNone(r.context["horasChartData"])
        self.assertFalse(r.context["tem_scans"])

    def test_event_table_and_recent_registrations(self):
        ticket(1, name="Corrida", payment="paid", entered=True, amount=100)
        ticket(2, name="Corrida", payment="preregistered")
        r = self.get()
        linha = r.context["table_eventos"]["rows"][0]
        self.assertEqual(linha, ["Corrida", "2", "1", "1", "1", "100%", "100 MZN"])
        estados = [row[3] for row in r.context["table_recentes"]["rows"]]
        self.assertCountEqual(estados, ["Confirmado", "Por confirmar"])

    def test_page_contains_filters_and_cards(self):
        ticket(1, payment="preregistered")
        html = self.get().content.decode()
        self.assertIn('name="evento"', html)
        self.assertIn("Inscrições por dia", html)
        self.assertIn("Últimas inscrições", html)

    def test_old_dashboard_url_redirects_to_the_single_dashboard(self):
        r = self.client.get(reverse("admin:externalticket_dashboard"))
        self.assertRedirects(r, reverse("admin:index"), fetch_redirect_response=False)

    def test_recent_registrations_are_ordered_by_registration_date(self):
        ticket(1, days_ago=5)
        ticket(2, days_ago=1)
        ticket(3, days_ago=3)
        nomes = [row[0] for row in self.get().context["table_recentes"]["rows"]]
        self.assertEqual(nomes, ["Pessoa 2", "Pessoa 3", "Pessoa 1"])
