from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple
import textwrap

from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas

from tools.tsrc.certificates.layout import TemplateBundle, get_by_path
from tools.tsrc.certificates.qr import draw_qr_code
from tools.tsrc.entries.model import Entry


LETTER_W, LETTER_H = letter  # 612 x 792 points


@dataclass(frozen=True)
class RenderContext:
    entry_dict: Dict[str, Any]
    template: TemplateBundle


def render_certificate_pdf(
    entry: Entry,
    template: TemplateBundle,
    out_pdf_path: Path,
) -> None:
    """
    Render a single-page Letter PDF certificate.

    Requirements enforced:
    - Letter size: 612 x 792 points
    - Full-page background image (if missing, a blank page is still produced)
    - Overlay dynamic text fields
    - QR in reserved area encoding entry.certificate.qr_url
    - Disclaimer always included (template bundle)
    """
    out_pdf_path.parent.mkdir(parents=True, exist_ok=True)

    c = Canvas(str(out_pdf_path), pagesize=letter)
    ctx = RenderContext(entry_dict=entry.to_dict(), template=template)

    _draw_background(c, template)
    _draw_blocks(c, ctx)
    _draw_qr(c, ctx)
    _draw_disclaimer(c, ctx)

    c.showPage()
    c.save()


def _draw_background(c: Canvas, template: TemplateBundle) -> None:
    # Always paint the page area (even if background image is missing).
    c.saveState()
    c.rect(0, 0, LETTER_W, LETTER_H, stroke=0, fill=0)  # no-op fill, ensures page exists

    bg_path = template.background_path
    if bg_path.exists():
        img = ImageReader(str(bg_path))
        c.drawImage(img, 0, 0, width=LETTER_W, height=LETTER_H, preserveAspectRatio=False, mask="auto")
    else:
        # Phase 1: background.jpg is expected to be provided by you.
        # We still generate the PDF if missing, but it will be plain.
        # (This is intentional: generation should never require network access.)
        pass

    c.restoreState()


def _draw_blocks(c: Canvas, ctx: RenderContext) -> None:
    layout = ctx.template.layout
    blocks = layout.get("blocks", [])
    fonts = layout.get("fonts", {})
    default_font = fonts.get("body", "Helvetica")
    default_bold = fonts.get("body_bold", "Helvetica-Bold")
    default_mono = fonts.get("mono", "Courier")

    for b in blocks:
        btype = str(b.get("type", "")).strip().lower()
        if btype == "text":
            _draw_text_block(c, b, default_font=default_font, default_bold=default_bold, default_mono=default_mono)
        elif btype == "field":
            _draw_field_block(c, ctx, b, default_font=default_font, default_bold=default_bold, default_mono=default_mono)
        elif btype == "kv":
            _draw_kv_block(c, ctx, b, default_font=default_font, default_bold=default_bold, default_mono=default_mono)
        else:
            # Unknown block types are ignored to keep templates forward-compatible.
            continue


def _font_pick(name: str, *, default_font: str, default_bold: str, default_mono: str) -> str:
    if name == "bold":
        return default_bold
    if name == "mono":
        return default_mono
    if name:
        return name
    return default_font


def _draw_text_block(c: Canvas, b: Dict[str, Any], *, default_font: str, default_bold: str, default_mono: str) -> None:
    text = str(b.get("text", ""))
    x = float(b.get("x", 72))
    y = float(b.get("y", 720))
    size = float(b.get("size", 12))
    align = str(b.get("align", "left")).lower()
    font = _font_pick(str(b.get("font", "")), default_font=default_font, default_bold=default_bold, default_mono=default_mono)

    c.saveState()
    c.setFont(font, size)

    if align == "center":
        c.drawCentredString(x, y, text)
    elif align == "right":
        c.drawRightString(x, y, text)
    else:
        c.drawString(x, y, text)

    c.restoreState()


def _draw_field_block(
    c: Canvas,
    ctx: RenderContext,
    b: Dict[str, Any],
    *,
    default_font: str,
    default_bold: str,
    default_mono: str,
) -> None:
    key = str(b.get("key", "")).strip()
    if not key:
        return

    value = get_by_path(ctx.entry_dict, key)
    value = value if value is not None else ""
    value = str(value)

    # Optional formatting:
    prefix = str(b.get("prefix", ""))
    suffix = str(b.get("suffix", ""))
    text = f"{prefix}{value}{suffix}"

    x = float(b.get("x", 72))
    y = float(b.get("y", 500))
    size = float(b.get("size", 11))
    align = str(b.get("align", "left")).lower()
    max_width = float(b.get("max_width", 0))  # 0 means no limit
    font = _font_pick(str(b.get("font", "")), default_font=default_font, default_bold=default_bold, default_mono=default_mono)

    c.saveState()
    c.setFont(font, size)

    if max_width and stringWidth(text, font, size) > max_width:
        # Simple shrink-to-fit:
        while size > 6 and stringWidth(text, font, size) > max_width:
            size -= 0.25
            c.setFont(font, size)

    if align == "center":
        c.drawCentredString(x, y, text)
    elif align == "right":
        c.drawRightString(x, y, text)
    else:
        c.drawString(x, y, text)

    c.restoreState()


def _draw_kv_block(
    c: Canvas,
    ctx: RenderContext,
    b: Dict[str, Any],
    *,
    default_font: str,
    default_bold: str,
    default_mono: str,
) -> None:
    label = str(b.get("label", "")).strip()
    key = str(b.get("key", "")).strip()

    x = float(b.get("x", 72))
    y = float(b.get("y", 500))
    label_size = float(b.get("label_size", 8))
    value_size = float(b.get("value_size", 11))
    gap = float(b.get("gap", 2))
    max_width = float(b.get("max_width", 0))

    label_font = _font_pick(str(b.get("label_font", "bold")), default_font=default_font, default_bold=default_bold, default_mono=default_mono)
    value_font = _font_pick(str(b.get("value_font", "")), default_font=default_font, default_bold=default_bold, default_mono=default_mono)

    value = get_by_path(ctx.entry_dict, key) if key else ""
    value = str(value)

    c.saveState()

    # Label (small)
    if label:
        c.setFont(label_font, label_size)
        c.drawString(x, y, label)
        y -= (label_size + gap)

    # Value (larger)
    c.setFont(value_font, value_size)
    text = value

    if max_width and stringWidth(text, value_font, value_size) > max_width:
        while value_size > 6 and stringWidth(text, value_font, value_size) > max_width:
            value_size -= 0.25
            c.setFont(value_font, value_size)

    c.drawString(x, y, text)
    c.restoreState()


def _draw_qr(c: Canvas, ctx: RenderContext) -> None:
    layout = ctx.template.layout
    qr_box = layout.get("qr", {})
    x = float(qr_box.get("x", 450))
    y = float(qr_box.get("y", 72))
    size = float(qr_box.get("size", 110))

    qr_url = get_by_path(ctx.entry_dict, "certificate.qr_url")
    draw_qr_code(c, qr_url, x, y, size)

    # Optional label under QR
    label = str(qr_box.get("label", "")).strip()
    if label:
        font = str(qr_box.get("label_font", "Helvetica"))
        fsize = float(qr_box.get("label_size", 8))
        c.saveState()
        c.setFont(font, fsize)
        c.drawCentredString(x + size / 2, y - (fsize + 4), label)
        c.restoreState()


def _draw_disclaimer(c: Canvas, ctx: RenderContext) -> None:
    layout = ctx.template.layout
    box = layout.get("disclaimer", {})

    x = float(box.get("x", 72))
    y = float(box.get("y", 55))
    width = float(box.get("width", 468))
    font = str(box.get("font", "Helvetica"))
    size = float(box.get("size", 7))
    leading = float(box.get("leading", 9))

    text = ctx.template.disclaimer_text.strip()
    lines = _wrap_text_to_width(text, font=font, size=size, max_width=width)

    c.saveState()
    c.setFont(font, size)

    # Draw upward from y (so disclaimer stays in the bottom margin region).
    # We'll draw line-by-line downward.
    ty = y
    for ln in lines:
        c.drawString(x, ty, ln)
        ty -= leading

    c.restoreState()


def _wrap_text_to_width(text: str, *, font: str, size: float, max_width: float) -> List[str]:
    # Conservative wrapping: wrap words and measure with reportlab stringWidth.
    words = text.split()
    if not words:
        return [""]

    lines: List[str] = []
    cur: List[str] = []

    for w in words:
        trial = (" ".join(cur + [w])).strip()
        if stringWidth(trial, font, size) <= max_width or not cur:
            cur.append(w)
        else:
            lines.append(" ".join(cur))
            cur = [w]

    if cur:
        lines.append(" ".join(cur))

    # Preserve paragraph breaks if provided as blank lines
    # (simple approach: also split original text by \n\n and re-wrap each paragraph)
    if "\n" in text:
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        out: List[str] = []
        for p in paragraphs:
            out.extend(_wrap_text_to_width(p.replace("\n", " "), font=font, size=size, max_width=max_width))
            out.append("")  # blank line
        if out and out[-1] == "":
            out.pop()
        return out

    return lines
