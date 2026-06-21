from urllib.parse import quote

from odoo import api, fields, models


class IrAttachment(models.Model):
    _inherit = "ir.attachment"

    staff_loan_is_pdf = fields.Boolean(compute="_compute_staff_loan_preview", string="Is PDF")
    staff_loan_preview_html = fields.Html(
        compute="_compute_staff_loan_preview",
        sanitize=False,
        string="Preview",
    )

    @api.depends("type", "mimetype")
    def _compute_staff_loan_preview(self):
        for attachment in self:
            is_pdf = attachment.type == "binary" and (attachment.mimetype or "").startswith("application/pdf") and bool(attachment.id)
            attachment.staff_loan_is_pdf = is_pdf
            if not is_pdf:
                attachment.staff_loan_preview_html = ""
                continue
            file_url = f"/web/content/{attachment.id}?download=false"
            viewer_url = "/web/static/lib/pdfjs/web/viewer.html?file=%s" % quote(file_url, safe="")
            attachment.staff_loan_preview_html = (
                '<iframe src="%s" style="width:100%%; height:720px; border:0;" title="PDF Preview"></iframe>'
                % viewer_url
            )
