from odoo import fields, models, _


class AccountMove(models.Model):
    _inherit = "account.move"

    staff_loan_id = fields.Many2one(
        "staff.loan",
        string="Staff Loan",
        readonly=True,
        copy=False,
        index=True,
        ondelete="restrict",
    )
    staff_loan_line_id = fields.Many2one(
        "staff.loan.line",
        string="Staff Loan Installment",
        readonly=True,
        copy=False,
        index=True,
        ondelete="restrict",
    )
    is_staff_loan_disbursement = fields.Boolean(readonly=True, copy=False)
    is_staff_loan_repayment_move = fields.Boolean(readonly=True, copy=False)
    is_staff_loan_collection = fields.Boolean(readonly=True, copy=False)

    def open_staff_loan(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Staff Loan"),
            "res_model": "staff.loan",
            "res_id": self.staff_loan_id.id,
            "views": [(False, "form")],
        }
