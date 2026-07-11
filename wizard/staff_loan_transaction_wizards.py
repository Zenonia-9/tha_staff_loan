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
        res = super().default_get(fields_list)
        loan = self.env["staff.loan"].browse(self.env.context.get("default_loan_id"))
        if loan:
            res.update({
                "loan_id": loan.id,
                "journal_id": loan._get_loan_journal().id,
                "reference": loan.reference or loan.name,
            })
        return res

    @api.depends("loan_id", "journal_id")
    def _compute_preview(self):
        for wizard in self:
            loan = wizard.loan_id
            if loan and loan.disbursement_account_id and loan.deferred_account_id:
                receivable_amount = loan.total_payment
                wizard.preview = (
                    f"Dr {loan.receivable_account_id.display_name}: {loan.currency_id.format(receivable_amount)}\n"
                    f"Cr {loan.disbursement_account_id.display_name}: {loan.currency_id.format(loan.loan_amount)}\n"
                    f"Cr {loan.deferred_account_id.display_name}: {loan.currency_id.format(loan.total_interest)}"
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
        res = super().default_get(fields_list)
        loan = self.env["staff.loan"].browse(self.env.context.get("default_loan_id"))
        line = self.env["staff.loan.line"].browse(self.env.context.get("default_line_id"))
        if loan:
            res.update({
                "loan_id": loan.id,
                "journal_id": loan._get_loan_journal().id,
                "reference": loan.reference or loan.name,
            })
        if line:
            res.update({
                "line_id": line.id,
                "amount": line.open_amount,
            })
        return res

    def action_collect(self):
        self.ensure_one()
        if self.line_id.loan_id != self.loan_id:
            raise UserError(_("The selected installment does not belong to this loan."))
        if float_compare(self.amount, self.line_id.open_amount, precision_rounding=self.currency_id.rounding) != 0:
            raise UserError(_("Collection amount must equal the full scheduled amount."))
        self.line_id._post_collection_move(self.collection_date, self.journal_id, self.amount, self.reference, self.remarks)
        return {"type": "ir.actions.act_window_close"}


class StaffLoanFullSettlementWizard(models.TransientModel):
    _name = "staff.loan.full.settlement.wizard"
    _description = "Staff Loan Full Settlement Wizard"

    loan_id = fields.Many2one("staff.loan", required=True)
    currency_id = fields.Many2one(related="loan_id.currency_id")
    settlement_date = fields.Date(default=fields.Date.context_today, required=True)
    journal_id = fields.Many2one("account.journal", required=True)
    reference = fields.Char()
    remarks = fields.Text()
    outstanding_balance = fields.Monetary(related="loan_id.outstanding_balance", currency_field="currency_id")
    remaining_deferred_interest = fields.Monetary(compute="_compute_remaining_deferred_interest", currency_field="currency_id")
    affected_line_count = fields.Integer(compute="_compute_affected_line_count")

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        loan = self.env["staff.loan"].browse(self.env.context.get("default_loan_id"))
        if loan:
            res.update({
                "loan_id": loan.id,
                "journal_id": loan._get_loan_journal().id,
                "reference": loan.reference or loan.name,
            })
        return res

    @api.depends("loan_id")
    def _compute_remaining_deferred_interest(self):
        for wizard in self:
            wizard.remaining_deferred_interest = wizard.loan_id._get_remaining_deferred_interest()

    @api.depends("loan_id")
    def _compute_affected_line_count(self):
        for wizard in self:
            wizard.affected_line_count = len(wizard.loan_id._get_settlement_lines())

    def action_settle(self):
        self.ensure_one()
        self.loan_id._post_full_settlement(self.settlement_date, self.journal_id, self.reference, self.remarks)
        return {"type": "ir.actions.act_window_close"}


class StaffLoanExceptionWizard(models.TransientModel):
    _name = "staff.loan.exception.wizard"
    _description = "Staff Loan Exception Wizard"

    loan_id = fields.Many2one("staff.loan", required=True)
    line_id = fields.Many2one("staff.loan.line", required=True)
    currency_id = fields.Many2one(related="loan_id.currency_id")
    exception_date = fields.Date(default=fields.Date.context_today, required=True)
    journal_id = fields.Many2one("account.journal", required=True)
    exception_amount = fields.Monetary(required=True)
    scheduled_interest = fields.Monetary(related="line_id.interest", currency_field="currency_id")
    principal_paid = fields.Monetary(compute="_compute_exception_split", currency_field="currency_id")
    remaining_principal = fields.Monetary(compute="_compute_exception_split", currency_field="currency_id")
    reference = fields.Char()
    reason = fields.Text(required=True)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        loan = self.env["staff.loan"].browse(self.env.context.get("default_loan_id"))
        line = self.env["staff.loan.line"].browse(self.env.context.get("default_line_id"))
        if loan:
            res.update({
                "loan_id": loan.id,
                "journal_id": loan._get_loan_journal().id,
                "reference": loan.reference or loan.name,
            })
        if line:
            res.update({
                "line_id": line.id,
                "exception_amount": line.open_amount,
            })
        return res

    @api.depends("line_id", "exception_amount")
    def _compute_exception_split(self):
        for wizard in self:
            principal_paid = max(wizard.exception_amount - wizard.line_id.interest, 0.0)
            wizard.principal_paid = wizard.currency_id.round(min(principal_paid, wizard.line_id.principal))
            wizard.remaining_principal = wizard.currency_id.round(max(wizard.line_id.principal - wizard.principal_paid, 0.0))

    def action_apply_exception(self):
        self.ensure_one()
        if self.line_id.loan_id != self.loan_id:
            raise UserError(_("The selected installment does not belong to this loan."))
        self.line_id._apply_exception(
            self.exception_date,
            self.journal_id,
            self.exception_amount,
            self.reference,
            self.reason,
        )
        return {"type": "ir.actions.act_window_close"}
