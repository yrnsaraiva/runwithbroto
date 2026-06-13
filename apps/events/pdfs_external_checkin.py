from io import BytesIO
from django.utils import timezone

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    PageTemplate,
    Frame,
    Table,
    TableStyle,
    Paragraph,
    Spacer,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER


def build_external_checkin_list_pdf(event_name, tickets) -> bytes:
    buf = BytesIO()

    doc = BaseDocTemplate(
        buf,
        pagesize=landscape(A4),
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
    )

    frame = Frame(
        doc.leftMargin,
        doc.bottomMargin,
        doc.width,
        doc.height,
        id="normal",
    )
    doc.addPageTemplates([PageTemplate(id="checkin", frames=[frame])])

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "Title",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=22,
        textColor=colors.HexColor("#0B0B0B"),
        alignment=TA_LEFT,
        spaceAfter=6,
    )

    meta_style = ParagraphStyle(
        "Meta",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#555555"),
        alignment=TA_LEFT,
    )

    cell_style = ParagraphStyle(
        "Cell",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor("#111111"),
        alignment=TA_LEFT,
    )

    cell_center = ParagraphStyle(
        "CellCenter",
        parent=cell_style,
        alignment=TA_CENTER,
    )

    story = []

    story.append(Paragraph("Lista de Check-in", title_style))
    story.append(
        Paragraph(
            f"<b>Evento:</b> {event_name} &nbsp;&nbsp;&nbsp; "
            f"<b>Total de inscritos:</b> {len(tickets)}",
            meta_style,
        )
    )
    story.append(
        Paragraph(
            f"<b>Emitido em:</b> {timezone.now().strftime('%d-%m-%Y %H:%M:%S')}",
            meta_style,
        )
    )
    story.append(Spacer(1, 8 * mm))

    data = [[
        Paragraph("<b>#</b>", cell_center),
        Paragraph("<b>Ticket</b>", cell_style),
        Paragraph("<b>Nome</b>", cell_style),
        Paragraph("<b>Telefone</b>", cell_style),
        Paragraph("<b>Email</b>", cell_style),
        Paragraph("<b>Confirm.</b>", cell_center),
    ]]

    for i, t in enumerate(tickets, start=1):
        data.append([
            Paragraph(str(i), cell_center),
            Paragraph(t.external_id or "—", cell_style),
            Paragraph(t.buyer_name or "—", cell_style),
            Paragraph(t.buyer_phone or "—", cell_style),
            Paragraph(t.buyer_email or "—", cell_style),
            Paragraph(" ", cell_center),
        ])

    table = Table(
        data,
        colWidths=[
            12 * mm,
            42 * mm,
            78 * mm,
            38 * mm,
            28 * mm,
            22 * mm,
            55 * mm,
        ],
        repeatRows=1,
    )

    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F3F4F6")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#111827")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D1D5DB")),
        ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#9CA3AF")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("ALIGN", (4, 1), (6, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#FAFAFA")]),
    ]))

    story.append(table)
    doc.build(story)

    pdf = buf.getvalue()
    buf.close()
    return pdf