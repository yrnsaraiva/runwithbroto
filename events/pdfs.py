from io import BytesIO
from django.utils import timezone

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors

from reportlab.graphics.barcode import qr
from reportlab.graphics import renderPDF
from reportlab.graphics.shapes import Drawing


def _draw_qr(c, value: str, x: float, y: float, size: float):
    widget = qr.QrCodeWidget(value)
    bounds = widget.getBounds()
    w = bounds[2] - bounds[0]
    h = bounds[3] - bounds[1]

    d = Drawing(size, size, transform=[size / w, 0, 0, size / h, 0, 0])
    d.add(widget)
    renderPDF.draw(d, c, x, y)


def _event_location(event) -> str:
    # tenta vários campos comuns
    for attr in ("meeting_point", "location_name", "location"):
        v = getattr(event, attr, "") or ""
        if v.strip():
            return v.strip()
    return "—"


def build_ticket_pdf(reg) -> bytes:
    """
    Gera PDF A4 do ingresso (EventRegistration).
    """
    event = reg.event

    # Paleta
    INK = colors.HexColor("#0B0B0B")
    MUTED = colors.HexColor("#444444")
    PAPER = colors.white
    BRAND = colors.HexColor("#C98B56")

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    W, H = A4

    # fundo
    c.setFillColor(PAPER)
    c.rect(0, 0, W, H, stroke=0, fill=1)

    # ====== TICKET BAND ======
    band_h = 72 * mm
    band_y = H - band_h - 20 * mm
    band_x = 18 * mm
    band_w = W - 36 * mm

    c.setFillColor(BRAND)
    c.roundRect(band_x, band_y, band_w, band_h, 0, stroke=0, fill=1)

    pad = 8 * mm
    qr_size = 45 * mm
    qr_x = band_x + pad
    qr_y = band_y + (band_h - qr_size) / 2

    # caixa branca do QR
    c.setFillColor(colors.white)
    c.roundRect(qr_x - 5, qr_y - 5, qr_size + 10, qr_size + 10, 0, stroke=0, fill=1)

    # QR: recomendo usar ticket_code puro ou URL de validação
    # Ex: https://runwithbroto.co.mz/t/<ticket_code>
    qr_value = f"RWB|{reg.ticket_code}"
    _draw_qr(c, qr_value, qr_x, qr_y, qr_size)

    # Poster (direita)
    poster_w = 20 * mm
    poster_h = 35 * mm
    poster_x = band_x + band_w - pad - poster_w
    poster_y = band_y + (band_h - poster_h) / 2

    if getattr(event, "poster", None) and getattr(event.poster, "path", None):
        try:
            c.drawImage(
                event.poster.path,
                poster_x + 2,
                poster_y + 2,
                poster_w - 4,
                poster_h - 4,
                preserveAspectRatio=True,
                anchor="c",
                mask="auto",
            )
        except Exception:
            c.setFillColor(colors.HexColor("#f3f3f3"))
            c.rect(poster_x + 2, poster_y + 2, poster_w - 4, poster_h - 4, stroke=0, fill=1)
            c.setFillColor(MUTED)
            c.setFont("Helvetica", 8)
            c.drawCentredString(poster_x + poster_w / 2, poster_y + poster_h / 2, "POSTER")

    # textos (centro)
    text_x = qr_x + qr_size + 10 * mm
    text_right_limit = poster_x - 8 * mm
    col_w = (text_right_limit - text_x) / 2

    def draw_pair(label, value, cx, cy):
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(cx, cy, label)
        c.setFont("Helvetica", 9)
        c.drawString(cx, cy - 11, value)

    start_local = timezone.localtime(event.start_at)
    start_str = start_local.strftime("%d-%m-%Y %H:%M")

    left_col_x = text_x
    right_col_x = text_x + col_w + 6 * mm
    top_line_y = band_y + band_h - 16 * mm
    gap = 14 * mm

    # esquerda (evento)
    draw_pair("EVENTO", (event.title or "")[:32], left_col_x, top_line_y)
    draw_pair("CIDADE", getattr(event, "get_city_display", lambda: str(event.city))(), left_col_x, top_line_y - gap)
    draw_pair("LOCAL", _event_location(event)[:32], left_col_x, top_line_y - 2 * gap)
    draw_pair("DATA / HORA", start_str, left_col_x, top_line_y - 3 * gap)

    # direita (participante)
    draw_pair("NOME", (reg.full_name or "")[:32], right_col_x, top_line_y)
    draw_pair("TIPO", "ENTRADA", right_col_x, top_line_y - gap)
    draw_pair("TICKET", str(reg.ticket_code)[:32], right_col_x, top_line_y - 2 * gap)

    # preço
    price_y = band_y + 12 * mm
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(right_col_x, price_y + 10, "PRECO")
    c.setFont("Helvetica", 9)

    price = getattr(event, "price", 0)
    currency = getattr(event, "currency", "MZN")
    price_str = f"{price:,.2f} {currency}".replace(",", "X").replace(".", ",").replace("X", ".")
    c.drawString(right_col_x, price_y, price_str)

    # footer logo
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 9)
    c.drawCentredString(W / 2, band_y - 10 * mm, "Powered by RunWithBroto")

    # ====== Termos ======
    tc_top = band_y - 22 * mm
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 10)
    c.drawCentredString(W / 2, tc_top, "TERMOS E CONDIÇÕES")

    terms = [
        "1. O ingresso é pessoal e válido apenas para o evento descrito.",
        "2. O acesso ao evento depende da confirmação de pagamento e validação no check-in.",
        "3. Guarde este PDF/QR para apresentação na entrada.",
        "4. Em caso de cancelamento do evento, a política aplicável será comunicada pelo organizador.",
        "5. Os dados pessoais recolhidos são usados apenas para gestão de inscrições e controlo de acesso.",
    ]

    c.setFillColor(MUTED)
    c.setFont("Helvetica", 8.5)

    x = 22 * mm
    y = tc_top - 10 * mm
    line_h = 5.2 * mm
    for t in terms:
        c.drawString(x, y, t)
        y -= line_h

    c.showPage()
    c.save()

    pdf = buf.getvalue()
    buf.close()
    return pdf