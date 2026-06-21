from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare


class StaffLoanDisburseWizard(models.TransientModel):
    _name = "staff.loan.disburse.wizard"
    _description = "Staff Loan Disbursement Wizard"

    loan_id = fields.Many2one("staff.loan", required=True)
    disbursement_date = fields.Date(default=fields.Date.context_today, required=True)
    journal_id = fields.Many2one("account.journal", required=True)
    reference = fields.Char()
    remarks = fields.Text()
    preview = fields.Text(compute="_compute_preview")

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        loan = self.env["staff.loan"].browse(self.env.context.get("default_loan_id"))
        if loan:
            values.update({
                "loan_id": loan.id,
                "journal_id": loan._get_loan_journal().id,
                "reference": loan.reference or loan.name,
            })
        return values

    @api.depends("loan_id", "journal_id")
    def _compute_preview(self):
        for wizard in self:
            loan = wizard.loan_id
            account = loan.disbursement_account_id
            if loan and account:
                wizard.preview = (
                    f"Dr {loan.receivable_account_id.display_name}: {loan.currency_id.format(loan.loan_amount)}\n"
                    f"Cr {account.display_name}: {loan.currency_id.format(loan.loan_amount)}"
                )
            else:
                wizard.preview = ""

    def action_disburse(self):
        self.ensure_one()
        self.loan_id._post_disbursement_move(self.disbursement_date, self.journal_id, self.reference, self.remarks)
        return {"type": "ir.actions.act_window_close"}


class StaffLoanCollectionWizard(models.TransientModel):
    _name = "staff.loan.collection.wizard"
    _description = "Staff Loan Collection Wizard"

    loan_id = fields.Many2one("staff.loan", required=True)
    line_id = fields.Many2one("staff.loan.line", required=True)
    currency_id = fields.Many2one(related="loan_id.currency_id")
    collection_date = fields.Date(default=fields.Date.context_today, required=True)
    journal_id = fields.Many2one("account.journal", required=True)
    amount = fields.Monetary(required=True)
    reference = fields.Char()
    remarks = fields.Text()

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        loan = self.env["staff.loan"].browse(self.env.context.get("default_loan_id"))
        line = self.env["staff.loan.line"].browse(self.env.context.get("default_line_id"))
        if loan:
            values.update({
                "loan_id": loan.id,
                "journal_id": loan._get_loan_journal().id,
                "reference": loan.reference or loan.name,
            })
        if line:
            values.update({
                "line_id": line.id,
                "amount": line.open_amount,
            })
        return values

    def action_collect(self):
        self.ensure_one()
        if self.line_id.loan_id != self.loan_id:
            raise UserError(_("The selected installment does not belong to this loan."))
        if float_compare(self.amount, self.line_id.open_amount, precision_rounding=self.currency_id.rounding) > 0:
            raise UserError(_("Collection amount cannot exceed the installment open amount."))
        self.line_id._post_collection_move(self.collection_date, self.journal_id, self.amount, self.reference, self.remarks)
        return {"type": "ir.actions.act_window_close"}
