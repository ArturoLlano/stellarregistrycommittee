from __future__ import annotations

from reportlab.graphics.barcode import qr
from reportlab.graphics.shapes import Drawing
from reportlab.graphics import renderPDF


def draw_qr_code(canvas, value: str, x: float, y: float, size: float) -> None:
    """
    Draw a QR code onto a ReportLab canvas.

    Deterministic: uses ReportLab's built-in QR widget (no external dependencies).
    """
    widget = qr.QrCodeWidget(value)
    bounds = widget.getBounds()
    w = bounds[2] - bounds[0]
    h = bounds[3] - bounds[1]

    # Scale widget to the requested size:
    d = Drawing(size, size, transform=[size / w, 0, 0, size / h, 0, 0])
    d.add(widget)

    renderPDF.draw(d, canvas, x, y)
