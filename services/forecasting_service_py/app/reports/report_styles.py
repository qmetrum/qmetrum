"""
report_styles.py: Shared brand tokens, styles, and helpers for all PDF reports.
Import this in every template so branding stays consistent.
"""

from xml.sax.saxutils import escape

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.platypus import Table, TableStyle, Paragraph, Spacer, HRFlowable

# ─── PAGE DIMENSIONS ───
W, H = letter
PAGE_WIDTH = W - 108  # usable content width (54pt margins each side)

# ─── BRAND PALETTE ───
NAVY       = HexColor("#0B1D3A")
DARK_NAVY  = HexColor("#0E2444")
SLATE      = HexColor("#2D3E50")
TEAL       = HexColor("#0F8B6E")
TEAL_LIGHT = HexColor("#E6F5F0")
CORAL      = HexColor("#D85A30")
AMBER      = HexColor("#D4920B")
AMBER_LIGHT= HexColor("#FDF5E6")
BLUE       = HexColor("#2B7ACC")
BLUE_LIGHT = HexColor("#EAF2FB")
LIGHT_BG   = HexColor("#F7F8FA")
BORDER     = HexColor("#DDE1E6")
TEXT_PRI   = HexColor("#1A1A2E")
TEXT_SEC   = HexColor("#5A6270")
TEXT_MUTED = HexColor("#8B95A2")
GREEN      = HexColor("#1B8553")
GREEN_LIGHT= HexColor("#E8F5EC")
RED        = HexColor("#C0392B")
RED_LIGHT  = HexColor("#FDECEC")
WHITE      = HexColor("#FFFFFF")

# ─── PARAGRAPH STYLES ───
s_section = ParagraphStyle(
    "Section", fontName="Helvetica-Bold", fontSize=8, textColor=TEAL,
    spaceAfter=2, spaceBefore=14, leading=10,
)
s_heading = ParagraphStyle(
    "Heading", fontName="Helvetica-Bold", fontSize=16, textColor=NAVY,
    spaceAfter=6, spaceBefore=4, leading=20,
)
s_subheading = ParagraphStyle(
    "Subheading", fontName="Helvetica-Bold", fontSize=12, textColor=SLATE,
    spaceAfter=4, spaceBefore=10, leading=16,
)
s_body = ParagraphStyle(
    "Body", fontName="Helvetica", fontSize=9, textColor=TEXT_PRI,
    spaceAfter=6, leading=14,
)
s_body_sm = ParagraphStyle(
    "BodySm", fontName="Helvetica", fontSize=8, textColor=TEXT_SEC,
    spaceAfter=4, leading=11,
)
s_disclaimer = ParagraphStyle(
    "Disclaimer", fontName="Helvetica", fontSize=6.5, textColor=TEXT_MUTED,
    spaceAfter=2, leading=8.5,
)
s_metric_val = ParagraphStyle(
    "MetricVal", fontName="Helvetica-Bold", fontSize=16,
    textColor=NAVY, alignment=TA_CENTER, leading=20,
)
s_metric_lbl = ParagraphStyle(
    "MetricLbl", fontName="Helvetica", fontSize=7.5,
    textColor=TEXT_SEC, alignment=TA_CENTER, leading=10,
)
s_footer_meta = ParagraphStyle(
    "FooterMeta", fontName="Helvetica", fontSize=7, textColor=TEXT_MUTED,
    spaceAfter=0, leading=10,
)
s_callout_body = ParagraphStyle(
    "CalloutBody", fontName="Helvetica", fontSize=9, textColor=TEXT_PRI,
    spaceAfter=4, leading=13,
)

# ─── REUSABLE COMPONENTS ───

# Humanize internal enum/scenario keys for client-facing display.
_LABEL_MAP = {
    "high_fragility": "High fragility",
    "elevated_fragility": "Elevated fragility",
    "normal": "Normal",
    "low_vol": "Low volatility",
    "high_vol": "High volatility",
    "base": "Base case",
    "bull_10": "Bull: +10% equity shock",
    "bear_10": "Bear: -10% equity shock",
    "high_vol_regime": "High volatility regime",
    "low_vol_regime": "Low volatility regime",
    "worst_case_cvar": "Adversarial worst case",
}


def humanize_label(value) -> str:
    """Turn an internal key like 'High_Fragility' or 'bear_10' into a phrase an
    advisor would actually say. Unknown values get underscores spaced out and
    title-cased."""
    if value is None:
        return ""
    key = str(value).strip()
    mapped = _LABEL_MAP.get(key.lower())
    if mapped:
        return mapped
    return key.replace("_", " ").strip().capitalize() if key else ""


def metric_card(value_str, label, color=NAVY):
    """A small metric card (value on top, label below) for dashboard rows.

    value_str/label are escaped: reportlab Paragraph treats text as mini-HTML,
    so an unescaped '&' (e.g. 'S&P 500') would render as a broken entity."""
    data = [
        [Paragraph(escape(str(value_str)), ParagraphStyle("_v", fontName="Helvetica-Bold",
                   fontSize=16, textColor=color, alignment=TA_CENTER, leading=20))],
        [Paragraph(escape(str(label)), s_metric_lbl)],
    ]
    t = Table(data, colWidths=[120], rowHeights=[28, 16])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT_BG),
        ("ROUNDEDCORNERS", [6, 6, 6, 6]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (0, 0), 8),
        ("BOTTOMPADDING", (-1, -1), (-1, -1), 8),
    ]))
    return t


def metrics_row(cards_list, page_width=PAGE_WIDTH):
    """Horizontal row of metric_card elements."""
    n = len(cards_list)
    t = Table([cards_list], colWidths=[page_width / n] * n)
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
    ]))
    return t


def styled_table(data, col_widths, page_width=PAGE_WIDTH):
    """Standard data table with navy header and alternating rows."""
    widths = [page_width * w for w in col_widths]
    t = Table(data, colWidths=widths)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (1, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("TEXTCOLOR", (0, 1), (-1, -1), TEXT_PRI),
        ("BACKGROUND", (0, 1), (-1, -1), WHITE),
        *[("BACKGROUND", (0, i), (-1, i), LIGHT_BG) for i in range(2, len(data), 2)],
        ("LINEBELOW", (0, 0), (-1, 0), 1, NAVY),
        ("LINEBELOW", (0, 1), (-1, -2), 0.3, BORDER),
        ("LINEBELOW", (0, -1), (-1, -1), 0.5, BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROUNDEDCORNERS", [4, 4, 4, 4]),
    ]))
    return t


def callout_box(text, bg_color=TEAL_LIGHT, border_color=TEAL):
    """Colored callout/alert box for key messages."""
    data = [[Paragraph(text, s_callout_body)]]
    t = Table(data, colWidths=[PAGE_WIDTH - 12])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), bg_color),
        ("LINEBELOW", (0, 0), (-1, -1), 0, bg_color),
        ("LINEBEFORE", (0, 0), (0, -1), 3, border_color),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LEFTPADDING", (0, 0), (-1, -1), 14),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
    ]))
    return t


def section_divider():
    return HRFlowable(width="100%", thickness=0.5, color=BORDER, spaceAfter=6, spaceBefore=6)


def draw_cover_page(c, doc, *, firm_name, client_name, report_date,
                    report_type, subtitle, cover_metrics):
    """Generic dark cover page. cover_metrics = [(label, value), ...]"""
    c.setFillColor(NAVY)
    c.rect(0, 0, W, H, fill=1, stroke=0)
    c.setFillColor(TEAL)
    c.rect(0, H - 8, W, 8, fill=1, stroke=0)

    c.setFillColor(WHITE)
    c.setFont("Helvetica", 10)
    c.drawString(54, H - 50, firm_name.upper())

    c.setStrokeColor(HexColor("#1E3A5F"))
    c.setLineWidth(0.5)
    c.line(54, H - 62, W - 54, H - 62)

    c.setFillColor(TEAL)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(54, H - 100, report_type.upper())

    c.setFillColor(WHITE)
    c.setFont("Helvetica-Bold", 28)
    c.drawString(54, H - 170, client_name)

    c.setFillColor(HexColor("#8BA3BF"))
    c.setFont("Helvetica", 12)
    c.drawString(54, H - 200, subtitle)

    # Metrics box
    if cover_metrics:
        box_y, box_h = 260, 150
        c.setFillColor(DARK_NAVY)
        c.roundRect(54, box_y, W - 108, box_h, 8, fill=1, stroke=0)

        col_w = (W - 108) / len(cover_metrics)
        for i, (label, value) in enumerate(cover_metrics):
            cx = 54 + col_w * i + col_w / 2
            c.setFillColor(HexColor("#6B8DAE"))
            c.setFont("Helvetica", 7)
            c.drawCentredString(cx, box_y + box_h - 38, label)
            c.setFillColor(WHITE)
            c.setFont("Helvetica-Bold", 17)
            c.drawCentredString(cx, box_y + box_h - 66, value)

        c.setStrokeColor(HexColor("#1A3355"))
        c.setLineWidth(0.5)
        for i in range(1, len(cover_metrics)):
            x = 54 + col_w * i
            c.line(x, box_y + 20, x, box_y + box_h - 20)

    # Footer
    c.setFillColor(HexColor("#6B8DAE"))
    c.setFont("Helvetica", 8)
    c.drawString(54, 76, f"Powered by Qsight Risk Intelligence")

    c.setFillColor(HexColor("#1E3A5F"))
    c.roundRect(W - 180, 56, 126, 24, 4, fill=1, stroke=0)
    c.setFillColor(HexColor("#6B8DAE"))
    c.setFont("Helvetica-Bold", 7)
    c.drawCentredString(W - 117, 64, "CONFIDENTIAL")


def draw_header_footer(c, doc, *, firm_name, client_name, report_date, advisor_name):
    """Standard header + footer for content pages."""
    c.setStrokeColor(TEAL)
    c.setLineWidth(1.5)
    c.line(54, H - 40, W - 54, H - 40)

    c.setFillColor(NAVY)
    c.setFont("Helvetica-Bold", 7)
    c.drawString(54, H - 35, firm_name.upper())

    c.setFillColor(TEXT_SEC)
    c.setFont("Helvetica", 7)
    c.drawRightString(W - 54, H - 35, client_name)

    c.setStrokeColor(BORDER)
    c.setLineWidth(0.5)
    c.line(54, 42, W - 54, 42)

    c.setFillColor(TEXT_MUTED)
    c.setFont("Helvetica", 6.5)
    c.drawString(54, 30, f"{report_date.strftime('%B %d, %Y')}  |  {advisor_name}  |  {firm_name}")
    c.drawRightString(W - 54, 30, f"Page {doc.page}")


def standard_disclaimer(firm_name, advisor_name):
    """Returns list of flowables for the standard disclaimer block."""
    return [
        section_divider(),
        Paragraph("IMPORTANT DISCLOSURES", s_section),
        Paragraph(
            "This report is provided for informational purposes only and does not constitute "
            "investment advice, a solicitation, or a recommendation to buy or sell any securities. "
            "Past performance is not indicative of future results. All forecasts and projections "
            "are based on mathematical models and historical data, which may not accurately predict "
            "future market conditions.",
            s_disclaimer,
        ),
        Paragraph(
            # No regulatory-status claims: the platform cannot know the firm's
            # registration status, and asserting one is a compliance liability.
            f"This document was prepared by {firm_name}. The information contained herein "
            f"is confidential and intended solely for the use of the named client. "
            f"For questions, contact {advisor_name}.",
            s_disclaimer,
        ),
    ]
