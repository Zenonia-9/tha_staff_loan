from odoo import api, fields, models, _


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
    staff_loan_due_date = fields.Date(
        related="staff_loan_line_id.due_date",
        string="Due Date",
        store=True,
        readonly=True,
    )
    is_staff_loan_disbursement = fields.Boolean(readonly=True, copy=False)
    is_staff_loan_repayment_move = fields.Boolean(readonly=True, copy=False)
    is_staff_loan_collection = fields.Boolean(readonly=True, copy=False)
    is_staff_loan_full_settlement = fields.Boolean(readonly=True, copy=False)
    is_staff_loan_settlement_recognition = fields.Boolean(readonly=True, copy=False)
    staff_loan_settlement_amount = fields.Monetary(
        string="Settlement",
        currency_field="staff_loan_currency_id",
        compute="_compute_staff_loan_settlement",
    )
    staff_loan_outstanding_balance = fields.Monetary(
        string="Outstanding Balance",
        currency_field="staff_loan_currency_id",
        compute="_compute_staff_loan_settlement",
    )
    staff_loan_currency_id = fields.Many2one(related="staff_loan_id.currency_id", string="Staff Loan Currency")

    @api.depends(
        "staff_loan_id",
        "staff_loan_id.total_payment",
        "staff_loan_id.line_ids.collection_move_ids",
        "staff_loan_id.line_ids.is_exception",
        "staff_loan_id.line_ids.exception_amount",
        "staff_loan_id.line_ids.exception_remaining_principal",
        "staff_loan_id.line_ids.exception_schedule_updated",
        "line_ids.debit",
        "line_ids.credit",
        "line_ids.account_id",
    )
    def _compute_staff_loan_settlement(self):
        for move in self:
            move.staff_loan_settlement_amount = 0.0
            move.staff_loan_outstanding_balance = 0.0
        for loan in self.mapped("staff_loan_id"):
            outstanding = loan._get_tracked_receivable_amount()
            moves = loan.collection_move_ids.filtered(lambda move: move.state == "posted" and not move.reversal_move_ids).sorted(
                lambda move: (move.date, move.id)
            )
            for move in moves:
                settlement = move._get_staff_loan_settlement_amount()
                outstanding = max(outstanding - settlement, 0.0)
                move.staff_loan_settlement_amount = settlement
                move.staff_loan_outstanding_balance = outstanding

    def _get_staff_loan_settlement_amount(self):
        self.ensure_one()
        loan = self.staff_loan_id
        if not loan or not self.is_staff_loan_collection:
            return 0.0
        settlement_lines = self.line_ids.filtered(lambda line: line.account_id == loan.receivable_account_id)
        return sum(settlement_lines.mapped("credit"))

    def _sync_staff_loan_state(self):
        loans = self.mapped("staff_loan_id") | self.mapped("reversed_entry_id.staff_loan_id") | self.mapped("reversal_move_ids.staff_loan_id")
        loans._sync_runtime_state()

    @api.model_create_multi
    def create(self, vals_list):
        moves = super().create(vals_list)
        moves._sync_staff_loan_state()
        return moves

    def write(self, vals):
        res = super().write(vals)
        if {"state", "reversed_entry_id", "staff_loan_id", "staff_loan_line_id"} & set(vals):
            self._sync_staff_loan_state()
        return res

    def open_staff_loan(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Staff Loan"),
            "res_model": "staff.loan",
            "res_id": self.staff_loan_id.id,
            "views": [(False, "form")],
        }
