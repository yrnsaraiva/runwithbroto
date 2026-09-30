from io import BytesIO
from pathlib import Path
import requests

from django.conf import settings
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.timezone import is_naive, make_aware

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.utils import ImageReader

from reportlab.graphics.barcode import qr
from reportlab.graphics import renderPDF
from reportlab.graphics.shapes import Drawing

from .models import ExternalTicket


def _draw_qr(c, value: str, x: float, y: float, size: float):
    widget = qr.QrCodeWidget(value)
    bounds = widget.getBounds()
    w = bounds[2] - bounds[0]
    h = bounds[3] - bounds[1]

    d = Drawing(size, size, transform=[size / w, 0, 0, size / h, 0, 0])
    d.add(widget)
    renderPDF.draw(d, c, x, y)


def _ticket_location(ticket) -> str:
    for attr in ("event_location_details", "event_province"):
        v = getattr(ticket, attr, "") or ""
        if str(v).strip():
            return str(v).strip()
    return "—"


def _load_remote_image(url: str):
    if not url:
        return None
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        return ImageReader(BytesIO(resp.content))
    except Exception:
        return None


def _draw_wrapped_text(c, text, x, y, max_width, font_name="Helvetica", font_size=9, line_height=11):
    """
    Desenha texto com quebra automática de linha.

    Args:
        c: objeto canvas do reportlab
        text: texto a ser desenhado
        x: posição x inicial
        y: posição y inicial (base da primeira linha)
        max_width: largura máxima em pontos
        font_name: nome da fonte
        font_size: tamanho da fonte
        line_height: altura entre linhas em pontos
    """
    if not text:
        return y

    text = str(text)
    c.setFont(font_name, font_size)

    words = text.split(' ')
    lines = []
    current_line = []

    for word in words:
        test_line = ' '.join(current_line + [word])
        text_width = c.stringWidth(test_line, font_name, font_size)

        if text_width <= max_width:
            current_line.append(word)
        else:
            if current_line:
                lines.append(' '.join(current_line))
            current_line = [word]

    if current_line:
        lines.append(' '.join(current_line))

    # Desenha cada linha
    for i, line in enumerate(lines):
        line_y = y - (i * line_height)
        c.drawString(x, line_y, line)

    # Retorna a nova posição Y após todas as linhas
    return y - ((len(lines) - 1) * line_height)


# Marca (static/css/app.css): preto + amarelo.
INK = colors.HexColor("#0B0B0B")
YELLOW = colors.HexColor("#FABB00")
MUTED = colors.HexColor("#5B5B5B")
LINE = colors.HexColor("#D9D9D9")
PAPER = colors.white


def _logo():
    """Logótipo (amarelo com transparência): fica bem sobre o cabeçalho preto."""
    path = Path(settings.BASE_DIR) / "static" / "img" / "logo.png"
    try:
        return ImageReader(str(path)) if path.exists() else None
    except Exception:
        return None


def _caps_text(c, x, y, text, font="Helvetica-Bold", size=6.5, space=0.8, color=MUTED, align="left"):
    """Texto em maiúsculas com espaçamento entre letras (rótulos)."""
    text = text.upper()
    width = c.stringWidth(text, font, size) + space * max(len(text) - 1, 0)
    if align == "right":
        x -= width
    t = c.beginText(x, y)
    t.setFont(font, size)
    t.setCharSpace(space)
    t.setFillColor(color)
    t.textOut(text)
    t.setCharSpace(0)          # o espaçamento faz parte do estado gráfico: não pode "vazar"
    c.drawText(t)
    return width


def _fit_lines(c, text, font, size, max_width, max_lines):
    """Quebra em linhas; se passar de `max_lines`, corta a última com reticências."""
    words, lines, cur = str(text).split(), [], ""
    for w in words:
        test = f"{cur} {w}".strip()
        if c.stringWidth(test, font, size) <= max_width or not cur:
            cur = test
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while last and c.stringWidth(last + "…", font, size) > max_width:
            last = last[:-1]
        lines[-1] = last.rstrip() + "…"
    return lines


def _field(c, label, value, x, y, max_width, size=10.5):
    """Rótulo pequeno + valor (até 2 linhas). Devolve a altura ocupada."""
    _caps_text(c, x, y, label)
    lines = _fit_lines(c, value or "—", "Helvetica-Bold", size, max_width, 2)
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", size)
    for n, line in enumerate(lines):
        c.drawString(x, y - 5 * mm - n * (size + 2.5), line)
    return 5 * mm + len(lines) * (size + 2.5)


def build_external_ticket_pdf(ticket: ExternalTicket) -> bytes:
    """
    PDF A4 do ingresso: cabeçalho da marca com o tipo em destaque, dados do
    evento, picotado e talão com o QR (o que o porteiro lê).
    """
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    W, H = A4

    c.setFillColor(PAPER)
    c.rect(0, 0, W, H, stroke=0, fill=1)

    # ---- geometria do cartão
    cx, cw = 18 * mm, W - 36 * mm
    right = cx + cw
    top = H - 16 * mm
    header_h = 28 * mm
    body_h = 68 * mm
    stub_h = 68 * mm
    footer_h = 9 * mm
    pad = 9 * mm
    card_bottom = top - header_h - body_h - stub_h - footer_h
    y_perf = top - header_h - body_h

    # ---- cabeçalho (preto)
    c.setFillColor(INK)
    c.rect(cx, top - header_h, cw, header_h, stroke=0, fill=1)
    logo = _logo()
    logo_h = 15 * mm
    if logo:
        logo_w = logo_h * 411 / 179
        c.drawImage(logo, cx + pad, top - header_h / 2 - logo_h / 2, logo_w, logo_h,
                    mask="auto", preserveAspectRatio=True)
    else:
        c.setFillColor(YELLOW)
        c.setFont("Helvetica-Bold", 16)
        c.drawString(cx + pad, top - header_h / 2 - 5, "RUN WITH BROTO")

    # tipo do bilhete (lote da API): a informação que o participante e o porteiro procuram
    tipo = ticket.ticket_type.upper()
    _caps_text(c, right - pad, top - 9 * mm, "Tipo de bilhete", size=6.5, color=colors.HexColor("#BBBBBB"),
               align="right")
    pill_font, pill_size = "Helvetica-Bold", 12
    pill_w = c.stringWidth(tipo, pill_font, pill_size) + 10 * mm
    pill_h = 9 * mm
    pill_y = top - 12 * mm - pill_h
    c.setFillColor(YELLOW)
    c.rect(right - pad - pill_w, pill_y, pill_w, pill_h, stroke=0, fill=1)
    c.setFillColor(INK)
    c.setFont(pill_font, pill_size)
    c.drawCentredString(right - pad - pill_w / 2, pill_y + 2.7 * mm, tipo)

    # ---- corpo: título, poster e dados
    body_top = top - header_h
    poster = _load_remote_image(ticket.event_image_url)
    poster_w, poster_h = 30 * mm, 40 * mm
    title_w = cw - 2 * pad - ((poster_w + 6 * mm) if poster else 0)

    c.setFillColor(YELLOW)
    c.rect(cx + pad, body_top - 11 * mm, 14 * mm, 1.6 * mm, stroke=0, fill=1)   # barra da marca
    title_size = 22
    lines = _fit_lines(c, (ticket.event_name or "Evento").upper(), "Helvetica-Bold", title_size, title_w, 2)
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", title_size)
    ty = body_top - 20 * mm
    for n, line in enumerate(lines):
        c.drawString(cx + pad, ty - n * (title_size + 3), line)

    if poster:
        try:
            c.drawImage(poster, right - pad - poster_w, body_top - 8 * mm - poster_h, poster_w, poster_h,
                        preserveAspectRatio=True, anchor="ne", mask="auto")
        except Exception:
            pass

    start_local = None
    if ticket.event_date:
        dt = ticket.event_date
        if is_naive(dt):
            dt = make_aware(dt)
        start_local = timezone.localtime(dt)
    date_str = start_local.strftime("%d/%m/%Y") if start_local else "—"
    time_str = start_local.strftime("%H:%M") if start_local else "—"

    col_w = (cw - 2 * pad - 8 * mm) / 2
    col1, col2 = cx + pad, cx + pad + col_w + 8 * mm
    row1 = body_top - 43 * mm
    row2 = body_top - 57 * mm
    # a 2.ª coluna não pode invadir o poster
    col2_w = min(col_w, (right - pad - poster_w - 4 * mm) - col2) if poster else col_w
    _field(c, "Data", date_str, col1, row1, col_w)
    _field(c, "Hora", time_str, col2, row1, col2_w)
    _field(c, "Local", _ticket_location(ticket), col1, row2, col_w)
    _field(c, "Cidade", ticket.event_province or "—", col2, row2, col2_w)

    # ---- picotado
    c.setStrokeColor(LINE)
    c.setLineWidth(0.8)
    c.setDash(2.5, 2.5)
    c.line(cx + 6 * mm, y_perf, right - 6 * mm, y_perf)
    c.setDash()

    # ---- talão: QR + participante
    stub_top = y_perf
    qr_size = 46 * mm
    qr_x = cx + pad + 3 * mm
    qr_y = stub_top - stub_h / 2 - qr_size / 2 + 2 * mm
    c.setStrokeColor(INK)
    c.setLineWidth(1)
    c.rect(qr_x - 3 * mm, qr_y - 3 * mm, qr_size + 6 * mm, qr_size + 6 * mm, stroke=1, fill=0)
    qr_value = ticket.qr_value or f"RWB|{ticket.external_id}"  # QR assinado pela API; RWB| só p/ bilhetes antigos
    _draw_qr(c, qr_value, qr_x, qr_y, qr_size)
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 7)
    c.drawCentredString(qr_x + qr_size / 2, qr_y - 8 * mm, "Apresente este QR na entrada")

    info_x = qr_x + qr_size + 16 * mm
    info_w = right - pad - info_x
    y = stub_top - 12 * mm
    y -= _field(c, "Participante", ticket.buyer_name or "Participante", info_x, y, info_w, size=13) + 5 * mm

    # código do bilhete (também serve para o check-in manual)
    _caps_text(c, info_x, y, "Bilhete")
    c.setFillColor(INK)
    c.setFont("Courier-Bold", 9)
    c.drawString(info_x, y - 4.6 * mm, ticket.external_id)
    y -= 12 * mm

    half = info_w / 2
    if ticket.tamanho_camisete:
        _field(c, "Camisete", ticket.get_tamanho_camisete_display(), info_x, y, half - 2 * mm, size=10)
        price_x = info_x + half
    else:
        price_x = info_x

    # preço: gratuito/convite não mostram "0,00 MZN"
    price = ticket.price_amount or 0
    if ticket.is_invite:
        price_str = "Convite"
    elif not price:
        price_str = "Gratuito"
    else:
        try:
            price_str = f"{float(price):,.2f} MZN".replace(",", "X").replace(".", ",").replace("X", ".")
        except Exception:
            price_str = f"{price} MZN"
    _field(c, "Preço", price_str, price_x, y, half if ticket.tamanho_camisete else info_w, size=10)

    # ---- rodapé do cartão + contorno
    foot_y = card_bottom
    c.setFillColor(INK)
    c.rect(cx, foot_y, cw, footer_h, stroke=0, fill=1)
    c.setFillColor(YELLOW)
    c.rect(cx, foot_y + footer_h, cw, 1.2 * mm, stroke=0, fill=1)
    c.setFillColor(colors.HexColor("#DDDDDD"))
    c.setFont("Helvetica", 7.5)
    c.drawCentredString(cx + cw / 2, foot_y + 3.2 * mm, "runwithbroto.com   ·   Powered by Shakes")
    c.setStrokeColor(INK)
    c.setLineWidth(1)
    c.rect(cx, card_bottom, cw, top - card_bottom, stroke=1, fill=0)

    # entalhes do picotado (por cima do contorno)
    c.setFillColor(PAPER)
    c.setStrokeColor(INK)
    for nx in (cx, right):
        c.circle(nx, y_perf, 3.6 * mm, stroke=1, fill=1)
    c.setFillColor(PAPER)
    c.setStrokeColor(PAPER)
    c.rect(cx - 3.8 * mm, y_perf - 3.8 * mm, 3.8 * mm, 7.6 * mm, stroke=0, fill=1)
    c.rect(right, y_perf - 3.8 * mm, 3.8 * mm, 7.6 * mm, stroke=0, fill=1)

    # ---- termos
    tc_top = card_bottom - 12 * mm
    _caps_text(c, cx, tc_top, "Termos e condições", size=8, color=INK)
    terms = [
        "O ingresso é pessoal e válido apenas para o evento descrito.",
        "O acesso ao evento depende da validação no check-in"
        + ("." if not ticket.price_amount or ticket.is_invite else " e da confirmação de pagamento."),
        "Guarde este PDF/QR para apresentação na entrada.",
        "Em caso de cancelamento do evento, a política aplicável será comunicada pelo organizador.",
        "Os dados pessoais recolhidos são usados apenas para gestão de inscrições e controlo de acesso.",
    ]
    y = tc_top - 6 * mm
    c.setFillColor(MUTED)
    for n, t in enumerate(terms, start=1):
        y = _draw_wrapped_text(c, f"{n}. {t}", cx, y, cw, "Helvetica", 7.8, 10) - 5.4 * mm

    c.showPage()
    c.save()

    pdf = buf.getvalue()
    buf.close()
    return pdf
