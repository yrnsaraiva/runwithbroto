"""Convites (bilhetes gratuitos emitidos pela organização) e o seu envio."""
import logging
import re
from urllib.parse import quote

from django.conf import settings
from django.core.mail import EmailMessage
from django.urls import reverse
from django.utils import timezone

from . import etk_client
from .models import ExternalTicket
from .pdf import build_external_ticket_pdf
from .sync import ensure_local_ticket

logger = logging.getLogger(__name__)


def create_invites(*, event_id, price_id, quantity, name="", email="", phone="", note="",
                   shirt_size=""):
    """Pede à API `quantity` convites e guarda-os localmente. Levanta
    `requests.HTTPError` se a API recusar (ex.: sem vagas)."""
    payload = {"eventId": event_id, "priceId": price_id, "quantity": quantity}
    for key, value in (("holderName", name), ("holderEmail", email),
                       ("phone", phone), ("note", note)):
        if value:
            payload[key] = value
    tickets = [ensure_local_ticket(t) for t in etk_client.create_invites(payload)]
    if name and len(tickets) > 1:
        _number_names(tickets, name)
    if shirt_size:
        # O tamanho é só do site (a API não o guarda).
        ExternalTicket.objects.filter(pk__in=[t.pk for t in tickets]).update(
            tamanho_camisete=shirt_size)
        for t in tickets:
            t.tamanho_camisete = shirt_size
    return tickets


def _number_names(tickets, name):
    """"Nome 1", "Nome 2"… nos convites de um mesmo nome. Continua a contagem dos
    convites já numerados para esse nome no evento. Só no site: a API guarda o nome sem número."""
    pattern = re.compile(rf"{re.escape(name)} (\d+)", re.IGNORECASE)
    existing = ExternalTicket.objects.filter(
        event_id_external=tickets[0].event_id_external,
        payment_status="invited",
        buyer_name__istartswith=f"{name} ",
    ).exclude(pk__in=[t.pk for t in tickets]).values_list("buyer_name", flat=True)
    last = max((int(m[1]) for m in map(pattern.fullmatch, existing) if m), default=0)
    for number, ticket in enumerate(tickets, start=last + 1):
        ticket.buyer_name = f"{name} {number}"
    ExternalTicket.objects.bulk_update(tickets, ["buyer_name"])


def email_enabled():
    return bool(settings.EMAIL_HOST)


def invite_link(request, ticket):
    """Link público do bilhete (página com QR e PDF), absoluto."""
    path = reverse("events:registration_success", args=[ticket.public_token])
    if settings.SITE_BASE_URL:
        return f"{settings.SITE_BASE_URL}{path}"
    return request.build_absolute_uri(path) if request else path


def normalize_phone(value):
    """Só dígitos com 258 à frente (aceita 84xxxxxxx); '' se não parecer um número."""
    digits = re.sub(r"\D", "", value or "")
    if not digits:
        return ""
    digits = digits if digits.startswith("258") else f"258{digits}"
    return digits if re.fullmatch(r"258\d{9}", digits) else ""


def _greeting(ticket):
    # Sem o contador dos convites: "Olá Ana," e não "Olá Ana 2,".
    name = re.sub(r"\s+\d+$", "", ticket.buyer_name)
    return f"Olá {name}," if name else "Olá,"


def _event_line(ticket):
    when = timezone.localtime(ticket.event_date).strftime("%d/%m/%Y às %H:%M") \
        if ticket.event_date else ""
    where = ticket.event_location_details or ticket.event_province
    return ", ".join(x for x in (ticket.event_name, when, where) if x)


def whatsapp_url(ticket, link):
    """Abre o WhatsApp com a mensagem pronta (o envio é feito por quem clica)."""
    phone = normalize_phone(ticket.buyer_phone)
    if not phone:
        return ""
    text = (f"{_greeting(ticket)} tem um convite para {_event_line(ticket)}. "
            f"O seu bilhete (mostre o QR na entrada): {link}")
    return f"https://wa.me/{phone}?text={quote(text)}"


def send_invite_email(tickets, links):
    """Um e-mail para o mesmo destinatário, com o link e o PDF de cada convite.

    `links` mapeia ticket.pk -> link. Devolve True se enviou. Só marca
    `invite_sent_at` depois de o envio ter corrido sem erro.
    """
    tickets = list(tickets)
    if not tickets or not email_enabled():
        return False
    first = tickets[0]
    if not first.buyer_email:
        return False

    lines = [_greeting(first), "", f"Tem {'um convite' if len(tickets) == 1 else f'{len(tickets)} convites'} "
             f"para {_event_line(first)}.", ""]
    for t in tickets:
        lines.append(f"• {links[t.pk]}")
    lines += ["", "Mostre o QR do bilhete (no telemóvel ou impresso) na entrada.", "", "Run With Broto"]

    message = EmailMessage(
        subject=f"O seu convite — {first.event_name}",
        body="\n".join(lines), to=[first.buyer_email],
    )
    for t in tickets:
        message.attach(f"convite-{t.external_id}.pdf", build_external_ticket_pdf(t), "application/pdf")
    message.send()

    ExternalTicket.objects.filter(pk__in=[t.pk for t in tickets]).update(
        invite_sent_at=timezone.now())
    return True


def send_ticket_email(ticket, link, to, name=""):
    """E-mail com o link e o PDF do bilhete de uma inscrição. Devolve True se enviou.

    Só marca `invite_sent_at` depois de o envio ter corrido sem erro.
    """
    if not to or not email_enabled():
        return False
    greeting = f"Olá {name}," if name else "Olá,"
    lines = [greeting, "", f"A sua inscrição está confirmada: {_event_line(ticket)}.", "",
             f"O seu bilhete: {link}", "",
             "Mostre o QR do bilhete (no telemóvel ou impresso) na entrada.", "", "Run With Broto"]
    message = EmailMessage(
        subject=f"O seu bilhete — {ticket.event_name}",
        body="\n".join(lines), to=[to],
    )
    message.attach(f"bilhete-{ticket.external_id}.pdf", build_external_ticket_pdf(ticket), "application/pdf")
    message.send()
    ExternalTicket.objects.filter(pk=ticket.pk).update(invite_sent_at=timezone.now())
    return True
