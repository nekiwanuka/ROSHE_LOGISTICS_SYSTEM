"""Frozen PDF renderers for documents created before migration 0033."""

# The public views import this module lazily, after logistics.views has finished loading.
# Reusing that namespace keeps the frozen renderer bodies independent of import order.
from . import views as _current_views

globals().update(
    {
        name: value
        for name, value in vars(_current_views).items()
        if not name.startswith("__")
    }
)


def payment_invoice(request, pk):
    payment = get_object_or_404(
        Payment.objects.select_related("loading__client"), pk=pk
    )
    preview_param = (request.GET.get("preview") or "").strip().lower()
    preview = preview_param in {"1", "true", "yes", "y"}
    buffer = BytesIO()
    loading = payment.loading
    client = loading.client
    is_air_cargo = getattr(loading, "cargo_type", None) == "air_cargo"

    issue_date = payment.created_at if payment.created_at else timezone.now()
    due_date = issue_date + timedelta(days=7)
    amount_due = payment.balance
    fee = (
        loading.handling_fees if is_air_cargo else payment.document_handling_fee
    ) or 0
    pvoc_fee = Decimal("0") if is_air_cargo else (payment.pvoc_fee or Decimal("0"))

    primary = colors.HexColor("#003366")
    accent = colors.HexColor("#f2cb3f")

    styles = getSampleStyleSheet()
    normal = styles["Normal"]
    normal.fontName = "Helvetica"
    normal.fontSize = 9
    normal.leading = 12

    heading = styles["Heading4"]
    heading.fontName = "Helvetica-Bold"
    heading.fontSize = 10
    heading.leading = 12
    heading.textColor = primary

    small = styles["BodyText"]
    small.fontName = "Helvetica"
    small.fontSize = 8
    small.leading = 10

    table_text = normal.clone("InvoiceTableText")
    table_text.fontSize = 8.5
    table_text.leading = 10.5
    table_text.wordWrap = "CJK"

    table_number = table_text.clone("InvoiceTableNumber")
    table_number.alignment = TA_RIGHT

    def table_cell(value, style=table_text):
        return Paragraph(escape(str(value)), style)

    def table_markup(markup, style=table_text):
        return Paragraph(markup, style)

    def draw_header(canvas_obj, doc):
        width, height = A4
        left = doc.leftMargin
        right = width - doc.rightMargin
        top = height - doc.topMargin + 95

        # Logo with blue background (only behind the logo)
        _draw_svg_logo_in_box(
            canvas_obj=canvas_obj, left=left, top=top, primary=primary
        )

        # Company block
        company_x = left + 60
        canvas_obj.setFillColor(colors.black)
        canvas_obj.setFont("Helvetica-Bold", 12)
        canvas_obj.drawString(company_x, top, "ROSHE LOGISTICS")
        canvas_obj.setFont("Helvetica", 8.5)
        canvas_obj.setFillColor(colors.black)
        canvas_obj.drawString(
            company_x,
            top - 12,
            "Plot 13 Mukwano Courts, Buganda Road · Floor 2 · Rooms 201–202",
        )
        canvas_obj.drawString(
            company_x,
            top - 24,
            "+256 788 239000 · +86 134 1613 7544 · info@roshegroup.com",
        )
        canvas_obj.drawString(company_x, top - 36, "www.roshegroup.com")

        # Invoice label (yellow background, black text)
        label_text = (
            f"AIR CARGO INVOICE {payment.invoice_number}"
            if is_air_cargo
            else f"OCEAN FREIGHT INVOICE {payment.invoice_number}"
        )
        canvas_obj.setFont("Helvetica-Bold", 12)
        label_w = canvas_obj.stringWidth(label_text, "Helvetica-Bold", 12) + 16
        label_h = 20
        label_x = right - label_w
        label_y = top - 2
        canvas_obj.setFillColor(accent)
        canvas_obj.roundRect(
            label_x, label_y - label_h + 4, label_w, label_h, 6, fill=1, stroke=0
        )
        canvas_obj.setFillColor(colors.black)
        canvas_obj.drawString(label_x + 8, label_y - 10, label_text)

        # Accent separator line
        canvas_obj.setStrokeColor(accent)
        canvas_obj.setLineWidth(2)
        canvas_obj.line(left, top - 52, right, top - 52)

    def draw_footer(canvas_obj, doc):
        _draw_brand_footer(canvas_obj, doc, primary=primary, accent=accent)

    def draw_page(canvas_obj, doc):
        draw_header(canvas_obj, doc)
        draw_footer(canvas_obj, doc)

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=40,
        rightMargin=40,
        topMargin=150,
        bottomMargin=45,
        title=f"{'Air Cargo Invoice' if is_air_cargo else 'Ocean Freight Invoice'} {payment.invoice_number}",
    )

    bill_to_lines = [
        "<b>BILL TO</b>",
        f"{client.name}",
        f"Phone: {client.phone}",
    ]
    if client.email:
        bill_to_lines.append(f"Email: {client.email}")
    if client.address:
        bill_to_lines.append(client.address)
    bill_to = Paragraph("<br/>".join(bill_to_lines), normal)

    invoice_meta_lines = [
        f"<b>{'Air Cargo Invoice No' if is_air_cargo else 'Ocean Freight Invoice No'}:</b> {payment.invoice_number}",
        f"<b>Invoice Date:</b> {issue_date.strftime('%Y-%m-%d')}",
        f"<b>Payment Due:</b> {due_date.strftime('%Y-%m-%d')}",
        f"<b>Amount Due (USD):</b> ${amount_due:,.2f}",
    ]
    invoice_meta = Paragraph("<br/>".join(invoice_meta_lines), normal)

    flow = getattr(loading, "flow_type", None)

    def display_date(value):
        return value.strftime("%Y-%m-%d") if value else ""

    if is_air_cargo:
        cargo_detail_rows = [
            ["AIR CARGO DETAILS", "", "", ""],
            [
                "Origin",
                loading.origin or "",
                "Destination",
                loading.destination or "",
            ],
            [
                "Package Count",
                loading.ctns if loading.ctns is not None else "",
                "Gross Weight",
                (
                    f"{loading.gross_weight:.2f} KGS"
                    if loading.gross_weight is not None
                    else ""
                ),
            ],
        ]
        cargo_detail_spans = [("SPAN", (0, 0), (-1, 0))]
        cargo_detail_col_widths = [
            doc.width * 0.18,
            doc.width * 0.32,
            doc.width * 0.18,
            doc.width * 0.32,
        ]
        cargo_detail_label_columns = [0, 2]
    else:
        cargo_detail_rows = [
            ["SHIPMENT DETAILS", "", "", ""],
            [
                "Route",
                f"{loading.origin or '—'} to {loading.destination or '—'}",
                "Flow",
                loading.get_flow_type_display() if flow else "—",
            ],
            [
                "Container Number",
                loading.container_number or "—",
                "Container Size",
                loading.get_container_size_display() if loading.container_size else "—",
            ],
            [
                "Loading Date",
                display_date(loading.loading_date),
                "CBM",
                (
                    f"{loading.weight:.2f}"
                    if flow == "lcl" and loading.weight is not None
                    else "—"
                ),
            ],
        ]
        cargo_detail_spans = [("SPAN", (0, 0), (-1, 0))]
        cargo_detail_col_widths = [
            doc.width * 0.16,
            doc.width * 0.34,
            doc.width * 0.16,
            doc.width * 0.34,
        ]
        cargo_detail_label_columns = [0, 2]

    cargo_detail_styles = [
        ("BACKGROUND", (0, 0), (-1, 0), primary),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOX", (0, 0), (-1, -1), 0.7, colors.black),
        ("INNERGRID", (0, 0), (-1, -1), 0.45, colors.HexColor("#444444")),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        *cargo_detail_spans,
    ]
    for label_column in cargo_detail_label_columns:
        cargo_detail_styles.extend(
            [
                (
                    "BACKGROUND",
                    (label_column, 1),
                    (label_column, -1),
                    colors.HexColor("#F7F7F7"),
                ),
                ("FONTNAME", (label_column, 1), (label_column, -1), "Helvetica-Bold"),
            ]
        )

    cargo_details_table = Table(
        cargo_detail_rows,
        colWidths=cargo_detail_col_widths,
        hAlign="LEFT",
    )
    cargo_details_table.setStyle(TableStyle(cargo_detail_styles))

    info_table = Table(
        [[bill_to, invoice_meta]],
        colWidths=[doc.width * 0.55, doc.width * 0.45],
        hAlign="LEFT",
    )
    info_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOX", (0, 0), (-1, -1), 0.7, colors.black),
                ("INNERGRID", (0, 0), (-1, -1), 0.7, colors.black),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )

    if is_air_cargo:
        qty_label = (
            f"{loading.gross_weight:.2f}" if loading.gross_weight is not None else "—"
        )
        rate_label = (
            f"{loading.rate_per_kg:,.2f}" if loading.rate_per_kg is not None else "—"
        )
        freight_amount = (
            (loading.gross_weight * loading.rate_per_kg)
            if (loading.gross_weight is not None and loading.rate_per_kg is not None)
            else None
        )
    elif flow == "lcl":
        qty_label = f"{loading.weight:.2f}" if loading.weight is not None else "—"
        rate_label = (
            f"{payment.rate_per_cbm:,.2f}" if payment.rate_per_cbm is not None else "—"
        )
        freight_amount = (
            (loading.weight * payment.rate_per_cbm)
            if (loading.weight is not None and payment.rate_per_cbm is not None)
            else None
        )
    else:
        qty_label = "1"
        rate_label = (
            f"{payment.rate_per_container:,.2f}"
            if payment.rate_per_container is not None
            else "—"
        )
        freight_amount = (
            payment.rate_per_container
            if payment.rate_per_container is not None
            else None
        )

    freight_amount_label = (
        f"{freight_amount:,.2f}" if freight_amount is not None else "—"
    )

    if is_air_cargo:
        freight_item_cell = table_markup("<b>Air Cargo Freight Charges</b>")
        qty_header = "Gross Weight (KGS)"
        rate_header = "Rate (per kg)"
    else:
        freight_item_cell = table_cell("Ocean Freight Charges")
        qty_header = "Quantity" if flow == "fcl" else "CBM"
        rate_header = "Rate"

    items = [
        ["Description", qty_header, rate_header, "Amount"],
        [
            freight_item_cell,
            table_cell(qty_label, table_number),
            table_cell(rate_label, table_number),
            table_cell(freight_amount_label, table_number),
        ],
    ]
    if fee and fee > 0:
        items.append(
            [
                table_cell(
                    "Handling Fees" if is_air_cargo else "Document & Handling Fees"
                ),
                "",
                "",
                table_cell(f"{fee:,.2f}", table_number),
            ]
        )
    if pvoc_fee and pvoc_fee > 0:
        pvoc_label = "PVOC"
        if flow == "lcl" and loading.weight is not None:
            per_cbm = pvoc_fee / loading.weight if loading.weight else pvoc_fee
            pvoc_label = f"PVOC ({loading.weight:.2f} CBM x {per_cbm:,.2f} / CBM)"
        elif flow == "fcl":
            pvoc_label = f"PVOC ({pvoc_fee:,.2f} / Container)"
        items.append(
            [
                table_cell(pvoc_label),
                "",
                "",
                table_cell(f"{pvoc_fee:,.2f}", table_number),
            ]
        )

    items_table = Table(
        items,
        colWidths=[
            doc.width * 0.46,
            doc.width * 0.18,
            doc.width * 0.18,
            doc.width * 0.18,
        ],
        hAlign="LEFT",
    )
    items_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F2F2F2")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ALIGN", (1, 1), (1, -1), "RIGHT"),
                ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BOX", (0, 0), (-1, -1), 0.7, colors.black),
                ("INNERGRID", (0, 0), (-1, -1), 0.7, colors.black),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )

    total_amount = payment.amount_charged
    totals_table = Table(
        [
            ["", "", "Total", f"{total_amount:,.2f}"],
            ["", "", "Amount Due (USD)", f"{amount_due:,.2f}"],
        ],
        colWidths=[
            doc.width * 0.46,
            doc.width * 0.18,
            doc.width * 0.18,
            doc.width * 0.18,
        ],
        hAlign="LEFT",
    )
    totals_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
                ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
                ("LINEABOVE", (2, 0), (-1, 0), 0.7, colors.black),
                ("LINEBELOW", (2, -1), (-1, -1), 0.7, colors.black),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )

    notes = [
        Paragraph("<b>Notes / Terms</b>", heading),
        Paragraph(
            (
                "1. Air Cargo charges are payable before release unless otherwise agreed."
                if is_air_cargo
                else "1. Freight charges are to be paid when the container arrives at Mombasa port."
            ),
            small,
        ),
        Paragraph("2. A Surcharge of 5% will be charged on late payment", small),
        Paragraph(
            "3. Partial payments are recorded; outstanding balance must be cleared before release.",
            small,
        ),
        Paragraph("4. Thank you for choosing ROSHE LOGISTICS.", small),
        Spacer(1, 6),
        Paragraph("<b>Bank Details</b>", heading),
        Paragraph(
            "Bank details are available on request. Please contact ROSHE LOGISTICS.",
            small,
        ),
    ]

    story = [
        info_table,
        Spacer(1, 12),
        cargo_details_table,
        Spacer(1, 10),
        items_table,
        Spacer(1, 8),
        totals_table,
        Spacer(1, 14),
        *notes,
    ]

    # Header + branded footer on all pages
    doc.build(
        story,
        onFirstPage=draw_page,
        onLaterPages=draw_page,
        canvasmaker=_paid_invoice_canvasmaker(payment, doc),
    )

    buffer.seek(0)
    response = HttpResponse(buffer.read(), content_type="application/pdf")
    disposition = "inline" if preview else "attachment"
    client_id = getattr(client, "client_id", None) or "NOCLIENT"
    response["Content-Disposition"] = (
        f'{disposition}; filename="{client_id}_INV_{payment.invoice_number}.pdf"'
    )
    return response


def payment_receipt(request, transaction_id):
    transaction = get_object_or_404(
        PaymentTransaction.objects.select_related(
            "payment__loading__client", "created_by", "verified_by"
        ),
        pk=transaction_id,
    )
    preview_param = (request.GET.get("preview") or "").strip().lower()
    preview = preview_param in {"1", "true", "yes", "y"}
    payment = transaction.payment
    if getattr(transaction, "is_voided", False):
        messages.error(request, "This receipt has been voided.")
        return redirect("payment_detail", pk=payment.pk)
    if transaction.verification_status != "approved":
        messages.error(request, "This payment has not been verified yet.")
        return redirect("payment_detail", pk=payment.pk)
    paid_up_to = (
        payment.transactions.filter(
            pk__lte=transaction.pk, verification_status="approved", is_voided=False
        ).aggregate(total=Sum("amount"))["total"]
        or transaction.amount
    )
    balance_after = payment.amount_charged - paid_up_to

    buffer = BytesIO()
    loading = payment.loading
    client = loading.client

    primary = colors.HexColor("#003366")
    accent = colors.HexColor("#f2cb3f")

    styles = getSampleStyleSheet()
    normal = styles["Normal"]
    normal.fontName = "Helvetica"
    normal.fontSize = 9
    normal.leading = 12

    heading = styles["Heading4"]
    heading.fontName = "Helvetica-Bold"
    heading.fontSize = 10
    heading.leading = 12
    heading.textColor = primary

    small = styles["BodyText"]
    small.fontName = "Helvetica"
    small.fontSize = 8
    small.leading = 10

    def draw_header(canvas_obj, doc):
        width, height = A4
        left = doc.leftMargin
        right = width - doc.rightMargin
        top = height - doc.topMargin + 95

        # Logo with blue background (only behind the logo)
        _draw_svg_logo_in_box(
            canvas_obj=canvas_obj, left=left, top=top, primary=primary
        )

        # Company block
        company_x = left + 60
        canvas_obj.setFillColor(colors.black)
        canvas_obj.setFont("Helvetica-Bold", 12)
        canvas_obj.drawString(company_x, top, "ROSHE LOGISTICS")
        canvas_obj.setFont("Helvetica", 8.5)
        canvas_obj.drawString(
            company_x,
            top - 12,
            "Plot 13 Mukwano Courts, Buganda Road · Floor 2 · Rooms 201–202",
        )
        canvas_obj.drawString(
            company_x,
            top - 24,
            "+256 788 239000 · +86 134 1613 7544 · info@roshegroup.com",
        )
        canvas_obj.drawString(company_x, top - 36, "www.roshegroup.com")

        # Receipt label (yellow background, black text)
        label_text = f"PAYMENT RECEIPT {transaction.receipt_number}"
        canvas_obj.setFont("Helvetica-Bold", 12)
        label_w = canvas_obj.stringWidth(label_text, "Helvetica-Bold", 12) + 16
        label_h = 20
        label_x = right - label_w
        label_y = top - 2
        canvas_obj.setFillColor(accent)
        canvas_obj.roundRect(
            label_x, label_y - label_h + 4, label_w, label_h, 6, fill=1, stroke=0
        )
        canvas_obj.setFillColor(colors.black)
        canvas_obj.drawString(label_x + 8, label_y - 10, label_text)

        canvas_obj.setStrokeColor(accent)
        canvas_obj.setLineWidth(2)
        canvas_obj.line(left, top - 52, right, top - 52)

    def draw_footer(canvas_obj, doc):
        _draw_brand_footer(canvas_obj, doc, primary=primary, accent=accent)

    def draw_page(canvas_obj, doc):
        draw_header(canvas_obj, doc)
        draw_footer(canvas_obj, doc)

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=40,
        rightMargin=40,
        topMargin=150,
        bottomMargin=55,
        title=f"Payment Receipt {transaction.receipt_number}",
    )

    received_from = Paragraph(
        "<b>RECEIVED FROM</b><br/>" f"{client.name}<br/>" f"Phone: {client.phone}",
        normal,
    )

    is_air_cargo = getattr(loading, "cargo_type", None) == "air_cargo"
    payment_lines = [
        "<b>PAYMENT DETAILS</b>",
        f"{'Air Cargo' if is_air_cargo else 'Ocean Freight'} Invoice No: {payment.invoice_number}",
        f"Payment Date: {transaction.payment_date.strftime('%Y-%m-%d %H:%M')}",
        f"Method: {transaction.get_payment_method_display()}",
    ]
    if not is_air_cargo:
        payment_lines.insert(2, f"Container Number: {loading.container_number or '—'}")
    if transaction.reference:
        payment_lines.append(f"Reference: {transaction.reference}")
    payment_details = Paragraph("<br/>".join(payment_lines), normal)

    top_table = Table(
        [[received_from, payment_details]],
        colWidths=[doc.width * 0.55, doc.width * 0.45],
        hAlign="LEFT",
    )
    top_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOX", (0, 0), (-1, -1), 0.7, colors.black),
                ("INNERGRID", (0, 0), (-1, -1), 0.7, colors.black),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )

    flow = getattr(loading, "flow_type", None)
    if is_air_cargo:
        shipment_lines = [
            "<b>SHIPMENT</b>",
            f"Origin: {loading.origin or '—'}",
            f"Destination: {loading.destination or '—'}",
            f"Package Count: {loading.ctns if loading.ctns is not None else '—'}",
            f"Gross Weight: {f'{loading.gross_weight:.2f} KGS' if loading.gross_weight is not None else '—'}",
        ]
    else:
        shipment_lines = [
            "<b>SHIPMENT</b>",
            f"Route: {loading.origin} to {loading.destination}",
            f"Loading Date: {loading.loading_date.strftime('%Y-%m-%d') if loading.loading_date else '—'}",
        ]
    if not is_air_cargo and flow == "fcl":
        if loading.container_size:
            shipment_lines.append(
                f"Container Size: {loading.get_container_size_display()}"
            )
    elif not is_air_cargo:
        cbm_value = f"{loading.weight:.2f} CBM" if loading.weight is not None else "—"
        shipment_lines.append(f"CBM: {cbm_value}")
    shipment_details = Paragraph("<br/>".join(shipment_lines), normal)

    summary_rows = [
        ["Summary", "Amount (USD)"],
        ["Amount Paid (this receipt)", f"{transaction.amount:,.2f}"],
        ["Paid Up To", f"{paid_up_to:,.2f}"],
        ["Outstanding After Payment", f"{balance_after:,.2f}"],
    ]
    summary_table = Table(
        summary_rows,
        colWidths=[doc.width * 0.65, doc.width * 0.35],
        hAlign="LEFT",
    )
    summary_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F2F2F2")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ALIGN", (1, 1), (1, -1), "RIGHT"),
                ("BOX", (0, 0), (-1, -1), 0.7, colors.black),
                ("INNERGRID", (0, 0), (-1, -1), 0.7, colors.black),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )

    verification_note = "Verified"
    if transaction.verified_by:
        verification_note = (
            f"Verified by {transaction.verified_by.username} on "
            f"{transaction.verified_at.strftime('%Y-%m-%d %H:%M') if transaction.verified_at else '—'}"
        )

    audit = [
        Paragraph("<b>Notes</b>", heading),
        Paragraph(verification_note, small),
        Paragraph(
            f"Recorded by {transaction.created_by.username} on {transaction.created_at.strftime('%Y-%m-%d %H:%M')}",
            small,
        ),
    ]

    story = [
        top_table,
        Spacer(1, 12),
        shipment_details,
        Spacer(1, 10),
        summary_table,
        Spacer(1, 14),
        *audit,
    ]

    doc.build(
        story,
        onFirstPage=draw_page,
        onLaterPages=draw_page,
        canvasmaker=_paid_receipt_canvasmaker(payment, transaction, doc),
    )
    buffer.seek(0)
    response = HttpResponse(buffer.read(), content_type="application/pdf")
    disposition = "inline" if preview else "attachment"
    client_id = getattr(client, "client_id", None) or "NOCLIENT"
    receipt_digits = _numeric_part(
        transaction.receipt_number, default=f"{transaction.pk:05d}"
    )
    response["Content-Disposition"] = (
        f'{disposition}; filename="{client_id}_RCT_{receipt_digits}.pdf"'
    )
    return response


def quote_pdf(request, quote_id):
    quote = get_object_or_404(Quote.objects.select_related("client"), pk=quote_id)
    client = quote.client
    client_id = getattr(client, "client_id", None) or "NOCLIENT"
    preview = request.GET.get("preview") == "1"
    quote_no = _quote_number(quote)

    primary = colors.HexColor("#003366")
    accent = colors.HexColor("#f2cb3f")

    styles = getSampleStyleSheet()
    normal = styles["BodyText"]
    normal.fontName = "Helvetica"
    normal.fontSize = 9
    normal.leading = 12

    heading = styles["Heading4"]
    heading.fontName = "Helvetica-Bold"
    heading.fontSize = 10
    heading.leading = 12
    heading.textColor = primary

    small = styles["BodyText"]
    small.fontName = "Helvetica"
    small.fontSize = 8
    small.leading = 10

    def draw_header(canvas_obj, doc):
        width, height = A4
        left = doc.leftMargin
        right = width - doc.rightMargin
        top = height - doc.topMargin + 95

        logo_box = 44
        canvas_obj.setFillColor(primary)
        canvas_obj.rect(left, top - logo_box + 8, logo_box, logo_box, fill=1, stroke=0)

        logo_path = finders.find("images/roshe_logo.svg")
        if logo_path:
            try:
                from svglib.svglib import svg2rlg
                from reportlab.graphics import renderPDF

                drawing = svg2rlg(logo_path)
                desired_h = 34
                if drawing and drawing.height:
                    scale = desired_h / float(drawing.height)
                    drawing.scale(scale, scale)
                    renderPDF.draw(drawing, canvas_obj, left + 5, top - desired_h + 10)
            except Exception:
                pass

        company_x = left + 60
        canvas_obj.setFillColor(colors.black)
        canvas_obj.setFont("Helvetica-Bold", 12)
        canvas_obj.drawString(company_x, top, "ROSHE LOGISTICS")
        canvas_obj.setFont("Helvetica", 8.5)
        canvas_obj.drawString(
            company_x,
            top - 12,
            "Plot 13 Mukwano Courts, Buganda Road · Floor 2 · Rooms 201–202",
        )
        canvas_obj.drawString(
            company_x,
            top - 24,
            "+256 788 239000 · +86 134 1613 7544 · info@roshegroup.com",
        )
        canvas_obj.drawString(company_x, top - 36, "www.roshegroup.com")

        label_text = (
            f"AIR CARGO QUOTATION {quote_no}"
            if quote.cargo_type == "air_cargo"
            else f"FREIGHT QUOTATION {quote_no}"
        )
        canvas_obj.setFont("Helvetica-Bold", 12)
        label_w = canvas_obj.stringWidth(label_text, "Helvetica-Bold", 12) + 16
        label_h = 20
        label_x = right - label_w
        label_y = top - 2
        canvas_obj.setFillColor(accent)
        canvas_obj.roundRect(
            label_x, label_y - label_h + 4, label_w, label_h, 6, fill=1, stroke=0
        )
        canvas_obj.setFillColor(colors.black)
        canvas_obj.drawString(label_x + 8, label_y - 10, label_text)

        canvas_obj.setStrokeColor(accent)
        canvas_obj.setLineWidth(2)
        canvas_obj.line(left, top - 52, right, top - 52)

    def draw_page(canvas_obj, doc):
        draw_header(canvas_obj, doc)
        _draw_brand_footer(canvas_obj, doc, primary=primary, accent=accent)

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=40,
        rightMargin=40,
        topMargin=150,
        bottomMargin=55,
        title=f"{'Air Cargo' if quote.cargo_type == 'air_cargo' else 'Freight'} Quotation {quote_no}",
    )

    bill_to_lines = [
        "<b>BILL TO</b>",
        f"{client.name if client else '—'}",
        f"Client ID: {client_id}",
    ]
    if client and client.phone:
        bill_to_lines.append(f"Phone: {client.phone}")
    if client and client.email:
        bill_to_lines.append(f"Email: {client.email}")
    if client and client.address:
        bill_to_lines.append(client.address)
    bill_to = Paragraph("<br/>".join(bill_to_lines), normal)

    meta_lines = [
        f"<b>Quotation No:</b> {quote_no}",
        f"<b>Status:</b> {quote.get_status_display()}",
        f"<b>Date:</b> {_fmt_dt(quote.created_at) or '—'}",
        f"<b>Cargo Type:</b> {quote.get_cargo_type_display()}",
        f"<b>Route:</b> {(quote.origin or '—')} to {(quote.destination or '—')}",
    ]
    meta = Paragraph("<br/>".join(meta_lines), normal)

    info_table = Table(
        [[bill_to, meta]],
        colWidths=[doc.width * 0.55, doc.width * 0.45],
        hAlign="LEFT",
    )
    info_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOX", (0, 0), (-1, -1), 0.7, colors.black),
                ("INNERGRID", (0, 0), (-1, -1), 0.7, colors.black),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )

    is_air_cargo = quote.cargo_type == "air_cargo"
    fee = (
        quote.handling_fees if is_air_cargo else quote.document_handling_fee
    ) or Decimal("0")
    if is_air_cargo:
        qty_label = (
            _fmt_number(quote.gross_weight, decimals=2)
            if quote.gross_weight is not None
            else "—"
        )
        rate_label = (
            _fmt_number(quote.rate_per_kg, decimals=2)
            if quote.rate_per_kg is not None
            else "—"
        )
        freight_amount = (
            (quote.gross_weight * quote.rate_per_kg)
            if (quote.gross_weight is not None and quote.rate_per_kg is not None)
            else None
        )
        unit_label = "KGS"
    elif quote.flow_type == "lcl":
        qty_label = _fmt_number(quote.cbm, decimals=2) if quote.cbm is not None else "—"
        rate_label = (
            _fmt_number(quote.rate_per_cbm, decimals=2)
            if quote.rate_per_cbm is not None
            else "—"
        )
        freight_amount = (
            (quote.cbm * quote.rate_per_cbm)
            if (quote.cbm is not None and quote.rate_per_cbm is not None)
            else None
        )
        unit_label = "CBM"
    else:
        qty_label = "1"
        rate_label = (
            _fmt_number(quote.rate_per_container, decimals=2)
            if quote.rate_per_container is not None
            else "—"
        )
        freight_amount = (
            quote.rate_per_container if quote.rate_per_container is not None else None
        )
        unit_label = "Container"

    freight_amount_label = (
        _fmt_number(freight_amount, decimals=2) if freight_amount is not None else "—"
    )
    route = f"{quote.origin or '—'} to {quote.destination or '—'}"
    charge_label = "AIR CARGO" if is_air_cargo else "FREIGHT CHARGE"
    description_lines = [f"<b>{charge_label}</b>"]
    if quote.item_description and not is_air_cargo:
        description_lines.append(
            f"Description of Items: {escape(quote.item_description)}"
        )
    freight_item = Paragraph("<br/>".join(description_lines), normal)

    if is_air_cargo:
        freight_basis = (
            f"{qty_label} KGS x {_fmt_number(quote.rate_per_kg, decimals=2)} / KG"
            if quote.rate_per_kg is not None
            else "Per KG"
        )
    elif quote.flow_type == "lcl":
        freight_basis = (
            f"{qty_label} CBM x {_fmt_number(quote.rate_per_cbm, decimals=2)} / CBM"
            if quote.rate_per_cbm is not None
            else "Per CBM"
        )
    else:
        freight_basis = (
            f"{_fmt_number(quote.rate_per_container, decimals=2)} / Container"
            if quote.rate_per_container is not None
            else "Per Container"
        )

    items = [["NO.", "DETAILS", "RATE BASIS", "TOTAL"]]
    charge_rows = [[freight_item, freight_basis, freight_amount_label]]
    if fee and fee > 0:
        fee_label = "HANDLING FEES" if is_air_cargo else "DOCUMENTS FEE"
        charge_rows.append([fee_label, "Flat charge", _fmt_number(fee, decimals=2)])
    pvoc_rate = Decimal("0") if is_air_cargo else (quote.pvoc_fee or Decimal("0"))
    pvoc_total = Decimal("0")
    if pvoc_rate and quote.flow_type == "lcl" and quote.cbm is not None:
        pvoc_total = quote.cbm * pvoc_rate
    elif pvoc_rate and quote.flow_type == "fcl":
        pvoc_total = pvoc_rate
    if pvoc_total and pvoc_total > 0:
        pvoc_label = "PVOC"
        pvoc_basis = "Per container"
        if quote.flow_type == "lcl" and quote.cbm is not None:
            pvoc_basis = f"{_fmt_number(quote.cbm, decimals=2)} CBM x {_fmt_number(pvoc_rate, decimals=2)} / CBM"
        elif quote.flow_type == "fcl":
            pvoc_basis = f"{_fmt_number(pvoc_rate, decimals=2)} / Container"
        charge_rows.append(
            [pvoc_label, pvoc_basis, _fmt_number(pvoc_total, decimals=2)]
        )

    for index, (detail, basis, amount) in enumerate(charge_rows, start=1):
        items.append([str(index), detail, basis, amount])

    items_table = Table(
        items,
        colWidths=[
            doc.width * 0.16,
            doc.width * 0.46,
            doc.width * 0.22,
            doc.width * 0.16,
        ],
        hAlign="LEFT",
    )
    items_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F2F2F2")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ALIGN", (0, 1), (0, -1), "CENTER"),
                ("ALIGN", (2, 1), (2, -1), "RIGHT"),
                ("ALIGN", (3, 1), (3, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BOX", (0, 0), (-1, -1), 0.7, colors.black),
                ("INNERGRID", (0, 0), (-1, -1), 0.7, colors.black),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )

    totals_table = Table(
        [
            [
                "Grand Total (USD)",
                "",
                "",
                _fmt_number(quote.amount_quoted, decimals=2),
            ],
        ],
        colWidths=[
            doc.width * 0.16,
            doc.width * 0.46,
            doc.width * 0.22,
            doc.width * 0.16,
        ],
        hAlign="LEFT",
    )
    totals_table.setStyle(
        TableStyle(
            [
                ("SPAN", (0, 0), (2, 0)),
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
                ("ALIGN", (0, 0), (2, 0), "RIGHT"),
                ("ALIGN", (3, 0), (3, 0), "RIGHT"),
                ("BOX", (0, 0), (-1, -1), 0.7, colors.black),
                ("INNERGRID", (0, 0), (-1, -1), 0.7, colors.black),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )

    notes = [
        Paragraph("<b>Notes / Terms</b>", heading),
        Paragraph("1. Quotation valid for 7 days from date of issue.", small),
        Paragraph("2. Prices may change due to carrier / customs adjustments.", small),
        Paragraph("3. Thank you for choosing ROSHE LOGISTICS.", small),
    ]

    story = [
        info_table,
        Spacer(1, 12),
        items_table,
        Spacer(1, 8),
        totals_table,
        Spacer(1, 14),
        *notes,
    ]

    doc.build(story, onFirstPage=draw_page, onLaterPages=draw_page)

    buffer.seek(0)
    response = HttpResponse(buffer.read(), content_type="application/pdf")
    disposition = "inline" if preview else "attachment"
    response["Content-Disposition"] = (
        f'{disposition}; filename="{client_id}_QTN_{quote.pk:05d}.pdf"'
    )
    return response
