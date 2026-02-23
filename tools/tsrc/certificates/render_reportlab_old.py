from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple

from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas

from tools.tsrc.certificates.layout import TemplateBundle, get_by_path
from tools.tsrc.certificates.qr import draw_qr_code
from tools.tsrc.entries.model import Entry


MM_TO_PT = 72.0 / 25.4  # 1 mm = 2.834645669... pt


@dataclass(frozen=True)
class RenderContext:
    entry_dict: Dict[str, Any]
    template: TemplateBundle
    page_w_pt: float
    page_h_pt: float
    units: str  # "pt" or "mm"


def render_certificate_pdf(
    entry: Entry,
    template: TemplateBundle,
    out_pdf_path: Path,
) -> None:
    """
    Single-page certificate.

    - Page size can be defined in pt OR mm (layout.json controls units).
    - All geometric coordinates can be in mm when units="mm".
    - Font sizes remain in points (pt), because fonts are naturally specified in pt.
    """
    units = _get_units(template)
    page_w_pt, page_h_pt = _get_template_pagesize_pt(template, units)

    out_pdf_path.parent.mkdir(parents=True, exist_ok=True)
    c = Canvas(str(out_pdf_path), pagesize=(page_w_pt, page_h_pt))

    ctx = RenderContext(
        entry_dict=entry.to_dict(),
        template=template,
        page_w_pt=page_w_pt,
        page_h_pt=page_h_pt,
        units=units,
    )

    _draw_background(c, ctx)
    _draw_blocks(c, ctx)
    _draw_qr(c, ctx)
    _draw_disclaimer(c, ctx)

    c.showPage()
    c.save()


def _get_units(template: TemplateBundle) -> str:
    u = str(template.layout.get("units", "pt")).strip().lower()
    return "mm" if u == "mm" else "pt"


def _to_pt(value: Any, units: str) -> float:
    v = float(value)
    return v * MM_TO_PT if units == "mm" else v


def _get_template_pagesize_pt(template: TemplateBundle, units: str) -> Tuple[float, float]:
    # Prefer layout.json "page", then manifest.json "page_size", else fallback Letter portrait.
    lay = template.layout.get("page", {})
    if isinstance(lay, dict):
        w = lay.get("width")
        h = lay.get("height")
        # Back-compat: also accept width_pt/height_pt
        if w is None and h is None:
            w = lay.get("width_pt")
            h = lay.get("height_pt")

        if isinstance(w, (int, float)) and isinstance(h, (int, float)) and w > 0 and h > 0:
            # If units="mm" then page is in mm; convert to pt.
            return _to_pt(w, units), _to_pt(h, units)

    man = template.manifest.get("page_size", {})
    if isinstance(man, dict):
        w = man.get("width_pt")
        h = man.get("height_pt")
        if isinstance(w, (int, float)) and isinstance(h, (int, float)) and w > 0 and h > 0:
            return float(w), float(h)

    w, h = letter  # fallback
    return float(w), float(h)


def _draw_background(c: Canvas, ctx: RenderContext) -> None:
    """
    Draw background full-page WITHOUT distortion.
    Uses "cover" scaling: fills the page while preserving aspect ratio (may crop edges slightly).
    """
    c.saveState()

    bg_path = ctx.template.background_path
    if bg_path.exists():
        try:
            img = ImageReader(str(bg_path))
            iw, ih = img.getSize()

            page_w, page_h = ctx.page_w_pt, ctx.page_h_pt

            # "cover" scale (fills page, may crop)
            scale = max(page_w / iw, page_h / ih)
            dw = iw * scale
            dh = ih * scale

            x = (page_w - dw) / 2.0
            y = (page_h - dh) / 2.0

            c.drawImage(img, x, y, width=dw, height=dh, mask="auto")
        except Exception as e:
            print(f"WARNING: background could not be loaded: {bg_path} ({e})")

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
            _draw_text_block(c, ctx, b, default_font, default_bold, default_mono)
        elif btype == "field":
            _draw_field_block(c, ctx, b, default_font, default_bold, default_mono)
        elif btype == "kv":
            _draw_kv_block(c, ctx, b, default_font, default_bold, default_mono)


def _font_pick(name: str, default_font: str, default_bold: str, default_mono: str) -> str:
    if name == "bold":
        return default_bold
    if name == "mono":
        return default_mono
    return name or default_font


def _draw_text_block(c: Canvas, ctx: RenderContext, b: Dict[str, Any], default_font: str, default_bold: str, default_mono: str) -> None:
    text = str(b.get("text", ""))
    x = _to_pt(b.get("x", 25), ctx.units)
    y = _to_pt(b.get("y", 200), ctx.units)
    size_pt = float(b.get("size", 12))  # font sizes stay in pt
    align = str(b.get("align", "left")).lower()
    font = _font_pick(str(b.get("font", "")), default_font, default_bold, default_mono)

    c.saveState()
    c.setFont(font, size_pt)

    if align == "center":
        c.drawCentredString(x, y, text)
    elif align == "right":
        c.drawRightString(x, y, text)
    else:
        c.drawString(x, y, text)

    c.restoreState()


def _draw_field_block(c: Canvas, ctx: RenderContext, b: Dict[str, Any], default_font: str, default_bold: str, default_mono: str) -> None:
    key = str(b.get("key", "")).strip()
    if not key:
        return

    value = get_by_path(ctx.entry_dict, key)
    prefix = str(b.get("prefix", ""))
    suffix = str(b.get("suffix", ""))
    text = f"{prefix}{value}{suffix}"

    x = _to_pt(b.get("x", 25), ctx.units)
    y = _to_pt(b.get("y", 150), ctx.units)
    size_pt = float(b.get("size", 11))  # font size in pt
    align = str(b.get("align", "left")).lower()
    max_width = b.get("max_width", 0)
    max_width_pt = _to_pt(max_width, ctx.units) if float(max_width or 0) else 0.0
    font = _font_pick(str(b.get("font", "")), default_font, default_bold, default_mono)

    c.saveState()
    c.setFont(font, size_pt)

    if max_width_pt and stringWidth(text, font, size_pt) > max_width_pt:
        while size_pt > 6 and stringWidth(text, font, size_pt) > max_width_pt:
            size_pt -= 0.25
            c.setFont(font, size_pt)

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
    default_font: str,
    default_bold: str,
    default_mono: str,
) -> None:
    label = str(b.get("label", "")).strip()
    key = str(b.get("key", "")).strip()

    # Geometric coords are in ctx.units (mm or pt)
    x = _to_pt(b.get("x", 25), ctx.units)
    y = _to_pt(b.get("y", 150), ctx.units)

    # Typography sizes are in points (pt)
    label_size_pt = float(b.get("label_size", 8))
    value_size_pt0 = float(b.get("value_size", 11))
    gap_pt = float(b.get("gap", 2))  # pt

    max_width = b.get("max_width", 0)
    max_width_pt = _to_pt(max_width, ctx.units) if float(max_width or 0) else 0.0

    label_font = _font_pick(str(b.get("label_font", "bold")), default_font, default_bold, default_mono)
    value_font = _font_pick(str(b.get("value_font", "")), default_font, default_bold, default_mono)

    value = get_by_path(ctx.entry_dict, key) if key else ""
    value = str(value)
    fmt = str(b.get("format", "")).strip()
    if fmt:
        value = _format_value(value, fmt)

    # Alignment:
    label_align = str(b.get("label_align", b.get("align", "left"))).strip().lower()
    value_align = str(b.get("value_align", b.get("align", "left"))).strip().lower()

    # Wrap / overflow behavior
    wrap = bool(b.get("wrap", False))
    max_lines = int(b.get("max_lines", 1)) if wrap else 1

    # leading in pt (typographic)
    value_leading_pt = float(b.get("value_leading", value_size_pt0 + 2))

    # Combined strategy controls
    shrink_on_overflow = bool(b.get("shrink_on_overflow", False))
    shrink_step_pt = float(b.get("shrink_step_pt", 1))
    min_value_size_pt = float(b.get("min_value_size_pt", 6))

    def _draw_aligned(text: str, xx: float, yy: float, align: str) -> None:
        if align == "center":
            c.drawCentredString(xx, yy, text)
        elif align == "right":
            c.drawRightString(xx, yy, text)
        else:
            c.drawString(xx, yy, text)

    def _wrap_lines(text: str, font: str, size_pt: float, width_pt: float) -> list[str]:
        """
        Greedy word-wrap to width_pt. Falls back to char splitting for long tokens.
        """
        if width_pt <= 0:
            return [text]

        words = text.split()
        if not words:
            return [""]

        lines: list[str] = []
        cur: list[str] = []

        def fits(s: str) -> bool:
            return stringWidth(s, font, size_pt) <= width_pt

        for w in words:
            trial = (" ".join(cur + [w])).strip()
            if not cur:
                # Single word too long: split into chunks by char
                if not fits(trial):
                    chunk = ""
                    for ch in w:
                        t2 = chunk + ch
                        if fits(t2) or chunk == "":
                            chunk = t2
                        else:
                            lines.append(chunk)
                            chunk = ch
                    if chunk:
                        cur = [chunk]
                    else:
                        cur = []
                else:
                    cur = [w]
            else:
                if fits(trial):
                    cur.append(w)
                else:
                    lines.append(" ".join(cur))
                    cur = [w]

        if cur:
            lines.append(" ".join(cur))

        return lines

    def _ellipsize(text: str, font: str, size_pt: float, width_pt: float) -> str:
        """
        Truncate with ellipsis so it fits width_pt.
        """
        if width_pt <= 0:
            return text
        ell = "…"
        if stringWidth(text, font, size_pt) <= width_pt:
            return text
        t = text
        while t and stringWidth(t + ell, font, size_pt) > width_pt:
            t = t[:-1]
        return (t + ell) if t else ell

    c.saveState()

    # Label line
    if label:
        c.setFont(label_font, label_size_pt)
        _draw_aligned(label, x, y, label_align)
        y -= (label_size_pt + gap_pt)

    # Value rendering
    if wrap:
        # Combined strategy:
        # 1) wrap to max_lines
        # 2) if overflow, shrink by 1pt steps until it fits or min reached
        # 3) if still overflow, ellipsize last line
        size_pt = value_size_pt0

        def layout_lines(sz: float) -> list[str]:
            return _wrap_lines(value, value_font, sz, max_width_pt)

        lines = layout_lines(size_pt)

        if shrink_on_overflow and max_width_pt > 0:
            while len(lines) > max_lines and size_pt - shrink_step_pt >= min_value_size_pt:
                size_pt -= shrink_step_pt
                lines = layout_lines(size_pt)

        # Now enforce max_lines; if still too many, ellipsize last line.
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            lines[-1] = _ellipsize(lines[-1], value_font, size_pt, max_width_pt)

        c.setFont(value_font, size_pt)

        # If caller didn’t specify leading, keep it proportional when size shrinks
        leading_pt = float(b.get("value_leading", size_pt + 2))

        for i, ln in enumerate(lines):
            _draw_aligned(ln, x, y - i * leading_pt, value_align)

    else:
        # Single-line behavior (existing): shrink-to-fit if max_width is set
        size_pt = value_size_pt0
        c.setFont(value_font, size_pt)

        if max_width_pt and stringWidth(value, value_font, size_pt) > max_width_pt:
            while size_pt > min_value_size_pt and stringWidth(value, value_font, size_pt) > max_width_pt:
                size_pt -= 0.25
                c.setFont(value_font, size_pt)

        _draw_aligned(value, x, y, value_align)

    c.restoreState()


def _draw_qr(c: Canvas, ctx: RenderContext) -> None:
    qr_box = ctx.template.layout.get("qr", {})
    x = _to_pt(qr_box.get("x", 240), ctx.units)
    y = _to_pt(qr_box.get("y", 20), ctx.units)
    size = _to_pt(qr_box.get("size", 35), ctx.units)

    qr_url = get_by_path(ctx.entry_dict, "certificate.qr_url")
    level = str(qr_box.get("level", "L")).strip().upper()
    version = qr_box.get("version", None)  # null/None = auto
    border = int(qr_box.get("border", 4))

    draw_qr_code(c, qr_url, x, y, size, level=level, version=version, border=border)

    label = str(qr_box.get("label", "")).strip()
    if label:
        font = str(qr_box.get("label_font", "Helvetica"))
        fsize_pt = float(qr_box.get("label_size", 8))
        c.saveState()
        c.setFont(font, fsize_pt)
        c.drawCentredString(x + size / 2, y - (fsize_pt + 4), label)
        c.restoreState()


def _draw_disclaimer(c: Canvas, ctx: RenderContext) -> None:
    box = ctx.template.layout.get("disclaimer", {})
    x = _to_pt(box.get("x", 20), ctx.units)
    y = _to_pt(box.get("y", 12), ctx.units)
    width = _to_pt(box.get("width", 170), ctx.units)

    font = str(box.get("font", "Helvetica"))
    size_pt = float(box.get("size", 7))
    leading_pt = float(box.get("leading", 9))

    text = ctx.template.disclaimer_text.strip()
    lines = _wrap_text_to_width(text, font=font, size=size_pt, max_width=width)

    c.saveState()
    c.setFont(font, size_pt)

    ty = y
    for ln in lines:
        c.drawString(x, ty, ln)
        ty -= leading_pt

    c.restoreState()


def _wrap_text_to_width(text: str, *, font: str, size: float, max_width: float) -> List[str]:
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

    return lines

from datetime import datetime

_MONTHS_EN = [
    "January","February","March","April","May","June",
    "July","August","September","October","November","December"
]

def _format_value(raw: str, fmt: str) -> str:
    fmt = (fmt or "").strip()

    if fmt == "date_long_en":
        # Expect ISO 8601, e.g. "2026-02-20T17:41:45.998137Z"
        # or "2026-02-20T11:41:45-06:00"
        try:
            s = raw.strip()
            s2 = s.replace("Z", "+00:00")
            dt = datetime.fromisoformat(s2)
            month = _MONTHS_EN[dt.month - 1]
            return f"{month} {dt.day}, {dt.year}"
        except Exception:
            return raw  # fallback: show original

    return raw