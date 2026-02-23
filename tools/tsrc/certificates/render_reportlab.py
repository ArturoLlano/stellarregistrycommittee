from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple

from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas

from tools.tsrc.config import get_paths
from tools.tsrc.certificates.layout import TemplateBundle, get_by_path
from tools.tsrc.certificates.qr import draw_qr_code
from tools.tsrc.entries.model import Entry
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont


MM_TO_PT = 72.0 / 25.4  # 1 mm = 2.834645669... pt


@dataclass(frozen=True)
class RenderContext:
    entry_dict: Dict[str, Any]
    template: TemplateBundle
    page_w_pt: float
    page_h_pt: float
    units: str  # "pt" or "mm"


def _register_template_fonts(template: TemplateBundle) -> None:
    fonts = template.manifest.get("fonts", {})
    if not isinstance(fonts, dict):
        return

    for font_name, rel_path in fonts.items():
        if not font_name or not rel_path:
            continue

        # Already registered?
        try:
            pdfmetrics.getFont(font_name)
            continue
        except Exception:
            pass

        font_path = (template.root_dir / str(rel_path)).resolve()
        pdfmetrics.registerFont(TTFont(str(font_name), str(font_path)))

def render_certificate_pdf(
    entry: Entry,
    template: TemplateBundle,
    out_pdf_path: Path,
) -> None:
    """
    Render a single-page certificate.

    Render flow (order matters):
      1) background
      2) layout blocks (in order, including the two legend paragraphs if present)
      3) QR
      4) disclaimer

    This design lets layout.json control placement/order of "before name" / "after name".
    """
    _register_template_fonts(template)
    units = _get_units(template)
    page_w_pt, page_h_pt = _get_template_pagesize_pt(template, units)

    out_pdf_path.parent.mkdir(parents=True, exist_ok=True)
    c = Canvas(str(out_pdf_path), pagesize=(page_w_pt, page_h_pt))

    # Base dictionary derived from Entry model
    entry_dict = entry.to_dict()

    # Merge additional certificate fields from the original JSON file if present.
    # This is critical for nested fields like certificate.legend_en (not represented in the Entry model).
    entry_dict = _merge_raw_entry_json_certificate_fields(entry_id=entry.id, entry_dict=entry_dict)

    ctx = RenderContext(
        entry_dict=entry_dict,
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


# -----------------------------
# Core helpers
# -----------------------------

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


def _merge_raw_entry_json_certificate_fields(entry_id: str, entry_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Merge nested certificate.* fields from the original entry JSON file into entry_dict["certificate"].

    Why:
    - Entry model currently only includes template_id and qr_url, so fields like:
        certificate.legend_en, certificate.lang
      would otherwise be lost for rendering.

    Graceful behavior:
    - If file missing or unreadable: return entry_dict unchanged.
    - If no certificate block in raw: unchanged.
    """
    try:
        paths = get_paths()
        p = (paths.entries_dir / f"{entry_id}.json").resolve()
        if not p.exists():
            return entry_dict

        raw = json.loads(p.read_text(encoding="utf-8"))
        raw_cert = raw.get("certificate")
        if not isinstance(raw_cert, dict):
            return entry_dict

        out = dict(entry_dict)
        out_cert = dict(out.get("certificate") or {})
        for k, v in raw_cert.items():
            if k not in out_cert:
                out_cert[k] = v
        out["certificate"] = out_cert
        return out
    except Exception:
        return entry_dict


def _font_pick(name: str, default_font: str, default_bold: str, default_mono: str) -> str:
    if name == "bold":
        return default_bold
    if name == "mono":
        return default_mono
    # Allow explicit font names too
    return name or default_font


def _draw_aligned_string(c: Canvas, text: str, x: float, y: float, align: str) -> None:
    a = (align or "left").strip().lower()
    if a == "center":
        c.drawCentredString(x, y, text)
    elif a == "right":
        c.drawRightString(x, y, text)
    else:
        c.drawString(x, y, text)


def _wrap_lines(text: str, *, font: str, size_pt: float, max_width_pt: float) -> List[str]:
    """
    Greedy word wrap to a max width using ReportLab stringWidth.
    """
    if not text:
        return [""]

    if max_width_pt <= 0:
        return [text]

    words = text.split()
    if not words:
        return [""]

    lines: List[str] = []
    cur: List[str] = []

    for w in words:
        trial = (" ".join(cur + [w])).strip()
        if stringWidth(trial, font, size_pt) <= max_width_pt or not cur:
            cur.append(w)
        else:
            lines.append(" ".join(cur))
            cur = [w]

    if cur:
        lines.append(" ".join(cur))

    return lines


def _ellipsize_line(text: str, *, font: str, size_pt: float, max_width_pt: float) -> str:
    """
    Truncate a single line with ellipsis to fit width.
    """
    if max_width_pt <= 0:
        return text

    ell = "…"
    if stringWidth(text, font, size_pt) <= max_width_pt:
        return text

    t = text
    while t and stringWidth(t + ell, font, size_pt) > max_width_pt:
        t = t[:-1]

    return (t + ell) if t else ell


def _layout_paragraph(
    text: str,
    *,
    font: str,
    size_pt_start: float,
    leading_pt: float,
    max_width_pt: float,
    max_lines: int,
    shrink_on_overflow: bool,
    shrink_step_pt: float,
    min_size_pt: float,
) -> Tuple[float, List[str], float]:
    """
    Wrap paragraph to max_width/max_lines. If overflow:
      - optionally shrink font in steps until it fits (down to min_size_pt)
      - if still overflow, ellipsize the last line

    Returns: (final_size_pt, lines_to_draw, final_leading_pt)
    """
    size_pt = size_pt_start

    def lines_for(sz: float) -> List[str]:
        return _wrap_lines(text, font=font, size_pt=sz, max_width_pt=max_width_pt)

    lines = lines_for(size_pt)

    if shrink_on_overflow and max_lines > 0 and max_width_pt > 0:
        while len(lines) > max_lines and (size_pt - shrink_step_pt) >= min_size_pt:
            size_pt -= shrink_step_pt
            lines = lines_for(size_pt)

    if max_lines > 0 and len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = _ellipsize_line(lines[-1], font=font, size_pt=size_pt, max_width_pt=max_width_pt)

    # If caller didn't explicitly set leading, keep it proportional when shrinking.
    if leading_pt <= 0:
        leading_pt = size_pt + 2

    return size_pt, lines, leading_pt


# -----------------------------
# Drawing primitives
# -----------------------------

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
        elif btype in ("paragraph", "para"):
            _draw_paragraph_block(c, ctx, b, default_font, default_bold, default_mono)


def _draw_text_block(c: Canvas, ctx: RenderContext, b: Dict[str, Any], default_font: str, default_bold: str, default_mono: str) -> None:
    text = str(b.get("text", ""))
    x = _to_pt(b.get("x", 25), ctx.units)
    y = _to_pt(b.get("y", 200), ctx.units)
    size_pt = float(b.get("size", 12))  # font sizes stay in pt
    align = str(b.get("align", "left")).lower()
    font = _font_pick(str(b.get("font", "")), default_font, default_bold, default_mono)

    c.saveState()
    c.setFont(font, size_pt)
    _draw_aligned_string(c, text, x, y, align)
    c.restoreState()


def _draw_field_block(c: Canvas, ctx: RenderContext, b: Dict[str, Any], default_font: str, default_bold: str, default_mono: str) -> None:
    key = str(b.get("key", "")).strip()
    if not key:
        return

    value = get_by_path(ctx.entry_dict, key)
    prefix = str(b.get("prefix", ""))
    suffix = str(b.get("suffix", ""))
    text = f"{prefix}{value}{suffix}".strip()

    x = _to_pt(b.get("x", 25), ctx.units)
    y = _to_pt(b.get("y", 150), ctx.units)
    size_pt = float(b.get("size", 11))  # font size in pt
    align = str(b.get("align", "left")).lower()
    max_width = b.get("max_width", 0)
    max_width_pt = _to_pt(max_width, ctx.units) if float(max_width or 0) else 0.0
    font = _font_pick(str(b.get("font", "")), default_font, default_bold, default_mono)

    if not text:
        return

    c.saveState()
    c.setFont(font, size_pt)

    # Optional shrink-to-fit for single-line field
    if max_width_pt and stringWidth(text, font, size_pt) > max_width_pt:
        while size_pt > 6 and stringWidth(text, font, size_pt) > max_width_pt:
            size_pt -= 0.25
            c.setFont(font, size_pt)

    _draw_aligned_string(c, text, x, y, align)
    c.restoreState()


def _draw_kv_block(c: Canvas, ctx: RenderContext, b: Dict[str, Any], default_font: str, default_bold: str, default_mono: str) -> None:
    """
    Key/value block:
      - optional label line (small)
      - value line (single-line with optional shrink-to-fit)
    """
    label = str(b.get("label", "")).strip()
    key = str(b.get("key", "")).strip()

    x = _to_pt(b.get("x", 25), ctx.units)
    y = _to_pt(b.get("y", 150), ctx.units)

    label_size_pt = float(b.get("label_size", 8))   # pt
    value_size_pt = float(b.get("value_size", 11))  # pt
    gap_pt = float(b.get("gap", 2))                 # pt

    max_width = b.get("max_width", 0)
    max_width_pt = _to_pt(max_width, ctx.units) if float(max_width or 0) else 0.0

    label_font = _font_pick(str(b.get("label_font", "bold")), default_font, default_bold, default_mono)
    value_font = _font_pick(str(b.get("value_font", "")), default_font, default_bold, default_mono)

    value = get_by_path(ctx.entry_dict, key) if key else ""
    value = str(value).strip()
    # Optional quoting for motto (or any kv value)
    if value:
        if bool(b.get("quote", False)):
            # Avoid double quoting if it already looks quoted
            if not (value.startswith(("“", '"', "'")) and value.endswith(("”", '"', "'"))):
                value = f"“{value}”"
    fmt = str(b.get("format", "")).strip()
    if fmt:
        value = _format_value(value, fmt)
    if not value and not label:
        return

    # Alignment (optional; backward-compatible defaults)
    label_align = str(b.get("label_align", b.get("align", "left"))).strip().lower()
    value_align = str(b.get("value_align", b.get("align", "left"))).strip().lower()

    # Optional: hide label without deleting it from layout
    show_label = bool(b.get("show_label", True))

    c.saveState()

    if show_label and label:
        c.setFont(label_font, label_size_pt)
        _draw_aligned_string(c, label, x, y, label_align)
        y -= (label_size_pt + gap_pt)

    c.setFont(value_font, value_size_pt)

    # Single-line shrink-to-fit for value
    if value and max_width_pt and stringWidth(value, value_font, value_size_pt) > max_width_pt:
        while value_size_pt > 6 and stringWidth(value, value_font, value_size_pt) > max_width_pt:
            value_size_pt -= 0.25
            c.setFont(value_font, value_size_pt)

    if value:
        _draw_aligned_string(c, value, x, y, value_align)

    c.restoreState()


def _draw_paragraph_block(c: Canvas, ctx: RenderContext, b: Dict[str, Any], default_font: str, default_bold: str, default_mono: str) -> None:
    """
    Wrapped paragraph block for legends (and other body text).

    Supports:
      - source: "entry" (default) or "manifest"
      - require: dotted path in entry_dict; if missing/empty => skip
      - max_lines + shrink_on_overflow + ellipsis fallback
    """
    source = str(b.get("source", "entry")).strip().lower()
    key = str(b.get("key", "")).strip()
    if not key:
        return

    require = str(b.get("require", "")).strip()
    if require:
        if not str(get_by_path(ctx.entry_dict, require)).strip():
            return

    if source == "manifest":
        text = str(get_by_path(ctx.template.manifest, key)).strip()
    else:
        text = str(get_by_path(ctx.entry_dict, key)).strip()

    # If missing, omit gracefully.
    if not text:
        return

    x = _to_pt(b.get("x", 25), ctx.units)
    y = _to_pt(b.get("y", 150), ctx.units)
    width_pt = _to_pt(b.get("width", 170), ctx.units)

    font = _font_pick(str(b.get("font", "")), default_font, default_bold, default_mono)
    size_pt = float(b.get("size", 10))
    leading_pt = float(b.get("leading", size_pt + 2))
    align = str(b.get("align", "left")).strip().lower()

    max_lines = int(b.get("max_lines", 0))  # 0 => unlimited
    shrink_on_overflow = bool(b.get("shrink_on_overflow", False))
    shrink_step_pt = float(b.get("shrink_step_pt", 1.0))
    min_size_pt = float(b.get("min_size_pt", 7.0))

    final_size_pt, lines, final_leading = _layout_paragraph(
        text,
        font=font,
        size_pt_start=size_pt,
        leading_pt=leading_pt,
        max_width_pt=width_pt,
        max_lines=max_lines,
        shrink_on_overflow=shrink_on_overflow,
        shrink_step_pt=shrink_step_pt,
        min_size_pt=min_size_pt,
    )

    c.saveState()
    c.setFont(font, final_size_pt)

    ty = y
    for ln in lines:
        _draw_aligned_string(c, ln, x, ty, align)
        ty -= final_leading

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
    # Kept for disclaimer (backward-compatible simple wrapping).
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