"""Reusable vector payment verification stamp for receipt PDFs."""

import math

from reportlab.graphics import renderPDF
from reportlab.lib import colors
from reportlab.platypus import Flowable

FULL_PAYMENT_COLOR = colors.HexColor("#102A83")
PARTIAL_PAYMENT_COLOR = colors.HexColor("#B00000")


def _apply_ink(node, ink):
    if getattr(node, "fillColor", None) is not None:
        node.fillColor = ink
    if getattr(node, "strokeColor", None) is not None:
        node.strokeColor = ink
    for child in getattr(node, "contents", []):
        _apply_ink(child, ink)


def _draw_logo(canvas_obj, logo_path, center_x, center_y, height, ink):
    if not logo_path:
        return

    try:
        from svglib.svglib import svg2rlg

        drawing = svg2rlg(logo_path)
        if not drawing or not drawing.height:
            return
        _apply_ink(drawing, ink)
        scale = height / float(drawing.height)
        drawing.scale(scale, scale)
        renderPDF.draw(
            drawing,
            canvas_obj,
            center_x - (drawing.width * scale) / 2,
            center_y - height / 2,
        )
    except Exception:
        return


def _draw_star(canvas_obj, center_x, center_y, radius):
    points = []
    for index in range(10):
        angle = math.radians(90 + index * 36)
        point_radius = radius if index % 2 == 0 else radius * 0.34
        points.append(
            (
                center_x + point_radius * math.cos(angle),
                center_y + point_radius * math.sin(angle),
            )
        )

    path = canvas_obj.beginPath()
    path.moveTo(*points[0])
    for point in points[1:]:
        path.lineTo(*point)
    path.close()
    canvas_obj.drawPath(path, fill=1, stroke=0)


def _draw_ring_impression(canvas_obj, center_x, center_y, radius, stamp_size):
    canvas_obj.saveState()
    if hasattr(canvas_obj, "setStrokeAlpha"):
        canvas_obj.setStrokeAlpha(0.18)
    canvas_obj.setLineWidth(stamp_size * 0.004)
    canvas_obj.circle(
        center_x + stamp_size * 0.004,
        center_y - stamp_size * 0.003,
        radius - stamp_size * 0.006,
        fill=0,
        stroke=1,
    )
    canvas_obj.setLineWidth(stamp_size * 0.008)
    for start_angle, extent in ((18, 14), (146, 10), (254, 16)):
        canvas_obj.arc(
            center_x - radius,
            center_y - radius,
            center_x + radius,
            center_y + radius,
            start_angle,
            extent,
        )
    canvas_obj.restoreState()


def _draw_curved_text(
    canvas_obj,
    text,
    center_x,
    center_y,
    radius,
    font_size,
    stroke_width=0,
    tracking_ratio=0.015,
    ink_stamp=False,
):
    tracking = font_size * tracking_ratio
    character_widths = [
        canvas_obj.stringWidth(character, "Helvetica-Bold", font_size)
        for character in text
    ]
    total_width = sum(character_widths) + tracking * (len(text) - 1)
    travelled = 0
    canvas_obj.setFont("Helvetica-Bold", font_size)

    for index, (character, character_width) in enumerate(zip(text, character_widths)):
        character_center = travelled + character_width / 2
        angle = 90 + math.degrees((total_width / 2 - character_center) / radius)
        radians = math.radians(angle)
        character_x = center_x + radius * math.cos(radians)
        character_y = center_y + radius * math.sin(radians)
        canvas_obj.saveState()
        canvas_obj.translate(character_x, character_y)
        canvas_obj.rotate(angle - 90)
        if character != " ":
            if stroke_width:
                canvas_obj.setLineWidth(stroke_width)
                text_object = canvas_obj.beginText()
                text_object.setTextOrigin(
                    -character_width / 2,
                    -font_size * 0.32,
                )
                text_object.setFont("Helvetica-Bold", font_size)
                text_object.setTextRenderMode(2)
                text_object.textOut(character)
                canvas_obj.drawText(text_object)
                if ink_stamp:
                    canvas_obj.saveState()
                    if hasattr(canvas_obj, "setFillAlpha"):
                        canvas_obj.setFillAlpha(0.2 + (index % 3) * 0.04)
                    canvas_obj.setFont("Helvetica-Bold", font_size)
                    offset = font_size * (0.012 if index % 2 else -0.01)
                    canvas_obj.drawCentredString(
                        offset,
                        -font_size * 0.32 + abs(offset) * 0.35,
                        character,
                    )
                    canvas_obj.restoreState()
            else:
                canvas_obj.drawCentredString(0, -font_size * 0.32, character)
        canvas_obj.restoreState()
        travelled += character_width + tracking

    return total_width


def _draw_fitted_text(
    canvas_obj,
    text,
    center_x,
    baseline_y,
    *,
    font_size,
    max_width,
    stroke_width=0,
):
    while (
        font_size > 5
        and canvas_obj.stringWidth(text, "Helvetica-Bold", font_size) > max_width
    ):
        font_size -= 0.25
    if stroke_width:
        canvas_obj.setLineWidth(stroke_width)
        text_object = canvas_obj.beginText()
        text_object.setTextOrigin(
            center_x - canvas_obj.stringWidth(text, "Helvetica-Bold", font_size) / 2,
            baseline_y,
        )
        text_object.setFont("Helvetica-Bold", font_size)
        text_object.setTextRenderMode(2)
        text_object.textOut(text)
        canvas_obj.drawText(text_object)
    else:
        canvas_obj.setFont("Helvetica-Bold", font_size)
        canvas_obj.drawCentredString(center_x, baseline_y, text)


def _draw_condensed_text(
    canvas_obj,
    text,
    center_x,
    baseline_y,
    *,
    font_size,
    max_width,
):
    native_width = canvas_obj.stringWidth(text, "Helvetica-Bold", font_size)
    horizontal_scale = min(100, (max_width / native_width) * 100)
    rendered_width = native_width * horizontal_scale / 100
    canvas_obj.saveState()
    text_object = canvas_obj.beginText()
    text_object.setTextOrigin(center_x - rendered_width / 2, baseline_y)
    text_object.setFont("Helvetica-Bold", font_size)
    text_object.setHorizScale(horizontal_scale)
    text_object.textOut(text)
    canvas_obj.drawText(text_object)
    canvas_obj.restoreState()


def draw_payment_verification_stamp(
    canvas_obj,
    *,
    center_x,
    center_y,
    diameter,
    receipt_number,
    invoice_number,
    payment_date,
    fully_paid,
    logo_path=None,
    width=None,
    height=None,
):
    """Draw a circular payment seal using live receipt data."""
    stamp_size = min(width or diameter, height or diameter)
    ink = FULL_PAYMENT_COLOR if fully_paid else PARTIAL_PAYMENT_COLOR
    status = "PAID" if fully_paid else "PARTIAL PAYMENT"

    canvas_obj.saveState()
    canvas_obj.setFillColor(ink)
    canvas_obj.setStrokeColor(ink)
    canvas_obj.setLineCap(1)
    canvas_obj.setLineJoin(1)
    if hasattr(canvas_obj, "setFillAlpha"):
        canvas_obj.setFillAlpha(0.72)
    if hasattr(canvas_obj, "setStrokeAlpha"):
        canvas_obj.setStrokeAlpha(0.72)

    outer_radius = stamp_size * 0.475
    canvas_obj.setLineWidth(stamp_size * 0.016)
    canvas_obj.circle(center_x, center_y, outer_radius, fill=0, stroke=1)
    _draw_ring_impression(
        canvas_obj,
        center_x,
        center_y,
        outer_radius,
        stamp_size,
    )

    inner_radius = stamp_size * 0.425
    canvas_obj.setLineWidth(stamp_size * 0.007)
    canvas_obj.setDash(stamp_size * 0.001, stamp_size * 0.018)
    canvas_obj.circle(center_x, center_y, inner_radius, fill=0, stroke=1)
    canvas_obj.setDash()

    _draw_logo(
        canvas_obj,
        logo_path,
        center_x,
        center_y + stamp_size * 0.185,
        stamp_size * 0.125,
        ink,
    )
    canvas_obj.saveState()
    if hasattr(canvas_obj, "setFillAlpha"):
        canvas_obj.setFillAlpha(0.92)
    brand_radius = stamp_size * 0.365
    brand_font_size = stamp_size * 0.092
    brand_width = _draw_curved_text(
        canvas_obj,
        "ROSHE LOGISTICS",
        center_x,
        center_y,
        brand_radius,
        brand_font_size,
        stroke_width=stamp_size * 0.002,
        tracking_ratio=0.11,
        ink_stamp=True,
    )
    canvas_obj.restoreState()
    star_offset = brand_width / 2 + brand_font_size * 0.72
    star_angle = star_offset / brand_radius
    _draw_star(
        canvas_obj,
        center_x - brand_radius * math.sin(star_angle),
        center_y + brand_radius * math.cos(star_angle),
        stamp_size * 0.034,
    )
    _draw_star(
        canvas_obj,
        center_x + brand_radius * math.sin(star_angle),
        center_y + brand_radius * math.cos(star_angle),
        stamp_size * 0.034,
    )

    divider_half_width = stamp_size * 0.34
    divider_gap = stamp_size * 0.018
    upper_divider_y = center_y + stamp_size * 0.07
    lower_divider_y = center_y - stamp_size * 0.11
    canvas_obj.setLineWidth(stamp_size * 0.006)
    for divider_y in (upper_divider_y, lower_divider_y):
        canvas_obj.line(
            center_x - divider_half_width,
            divider_y,
            center_x - divider_gap,
            divider_y,
        )
        canvas_obj.circle(center_x, divider_y, stamp_size * 0.008, fill=1, stroke=0)
        canvas_obj.line(
            center_x + divider_gap,
            divider_y,
            center_x + divider_half_width,
            divider_y,
        )

    status_font_size = stamp_size * (0.16 if fully_paid else 0.075)
    status_baseline = center_y - status_font_size * 0.34
    if hasattr(canvas_obj, "setFillAlpha"):
        canvas_obj.setFillAlpha(1)
    canvas_obj.setFillColor(PARTIAL_PAYMENT_COLOR if fully_paid else FULL_PAYMENT_COLOR)
    if fully_paid:
        _draw_fitted_text(
            canvas_obj,
            status,
            center_x,
            status_baseline,
            font_size=status_font_size,
            max_width=stamp_size * 0.48,
        )
    else:
        _draw_condensed_text(
            canvas_obj,
            status,
            center_x,
            status_baseline,
            font_size=status_font_size,
            max_width=stamp_size * 0.62,
        )
    if hasattr(canvas_obj, "setFillAlpha"):
        canvas_obj.setFillAlpha(0.72)
    canvas_obj.setFillColor(ink)

    invoice_y = center_y - stamp_size * 0.19
    _draw_condensed_text(
        canvas_obj,
        str(invoice_number),
        center_x,
        invoice_y,
        font_size=stamp_size * 0.06,
        max_width=stamp_size * 0.48,
    )

    date_y = center_y - stamp_size * 0.29
    _draw_condensed_text(
        canvas_obj,
        payment_date.strftime("%Y-%m-%d %H:%M"),
        center_x,
        date_y,
        font_size=stamp_size * 0.06,
        max_width=stamp_size * 0.58,
    )
    _draw_fitted_text(
        canvas_obj,
        "D A T E",
        center_x,
        center_y - stamp_size * 0.365,
        font_size=stamp_size * 0.036,
        max_width=stamp_size * 0.24,
        stroke_width=stamp_size * 0.0025,
    )
    canvas_obj.restoreState()


class PaymentVerificationStamp(Flowable):
    """Platypus flowable that places the verification stamp in receipt content."""

    def __init__(
        self,
        *,
        receipt_number,
        invoice_number,
        payment_date,
        fully_paid,
        logo_path=None,
        diameter=165,
        width=None,
        height=None,
        rotation_degrees=0,
        horizontal_offset=0,
    ):
        super().__init__()
        self.width = width or diameter
        self.height = height or diameter
        self.diameter = diameter
        self.rotation_degrees = rotation_degrees
        self.horizontal_offset = horizontal_offset
        self.receipt_number = receipt_number
        self.invoice_number = invoice_number
        self.payment_date = payment_date
        self.fully_paid = fully_paid
        self.logo_path = logo_path

    def draw(self):
        self.canv.saveState()
        self.canv.translate(
            self.width / 2 + self.horizontal_offset,
            self.height / 2,
        )
        self.canv.rotate(self.rotation_degrees)
        draw_payment_verification_stamp(
            self.canv,
            center_x=0,
            center_y=0,
            diameter=self.height,
            width=self.width,
            height=self.height,
            receipt_number=self.receipt_number,
            invoice_number=self.invoice_number,
            payment_date=self.payment_date,
            fully_paid=self.fully_paid,
            logo_path=self.logo_path,
        )
        self.canv.restoreState()
