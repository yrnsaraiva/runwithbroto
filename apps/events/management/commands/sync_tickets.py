from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.events import etk_client
from apps.events.sync import apply_api_ticket


class Command(BaseCommand):
    help = ("Atualiza o pagamento/entrada dos bilhetes locais a partir da API. "
            "Rede de segurança para webhooks perdidos; correr a cada poucos minutos.")

    def add_arguments(self, parser):
        parser.add_argument("--minutes", type=int, default=30,
                            help="Só bilhetes alterados nos últimos N minutos (default 30).")
        parser.add_argument("--all", action="store_true",
                            help="Todos os bilhetes (ex.: preencher o tipo/lote dos bilhetes antigos).")

    def handle(self, *args, **opts):
        since = None if opts["all"] else \
            (timezone.now() - timedelta(minutes=opts["minutes"])).isoformat().replace("+00:00", "Z")
        tickets = etk_client.list_tickets(since=since)
        updated = sum(1 for t in tickets if apply_api_ticket(t))
        self.stdout.write(f"{len(tickets)} bilhetes recebidos, {updated} atualizados localmente.")
