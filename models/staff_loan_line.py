from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare, float_is_zero
from odoo.tools.misc import format_date


class StaffLoanLine(models.Model):
    _name = "staff.loan.line"
    _description = "Staff Loan Installment"
    _order = "due_date, id"

    loan_id = fields.Many2one("staff.loan", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer(compute="_compute_sequence")
    due_date = fields.Date(required=True)
    company_id = fields.Many2one(related="loan_id.company_id", store=True)
    currency_id = fields.Many2one(related="loan_id.currency_id")
    employee_id = fields.Many2one(related="loan_id.employee_id", store=True)
    principal = fields.Monetary(required=True)
    interest = fields.Monetary(required=True)
    payment = fields.Monetary(compute="_compute_amounts", store=True)
    balance = fields.Monetary(string="Remaining Balance")
    paid_principal = fields.Monetary(compute="_compute_paid_amounts", store=True)
    paid_interest = fields.Monetary(compute="_compute_paid_amounts", store=True)
    paid_amount = fields.Monetary(compute="_compute_paid_amounts", store=True)
    open_amount = fields.Monetary(compute="_compute_paid_amounts", store=True)
    state = fields.Selection(
        [
            ("open", "Open"),
            ("partial", "Partial"),
            ("paid", "Paid"),
            ("overdue", "Overdue"),
        ],
        string="Status",
        compute="_compute_state",
        store=True,
        readonly=False,
        default="open",
    )
    collection_move_ids = fields.One2many(
        "account.move",
        "staff_loan_line_id",
        string="Collection Entries",
        readonly=True,
        domain=[("is_staff_loan_collection", "=", True)],
    )
    generated_move_ids = fields.One2many(
        "account.move",
        "staff_loan_line_id",
        string="Generated Entries",
        readonly=True,
        domain=[("is_staff_loan_repayment_move", "=", True)],
        help="Draft and posted journal entries generated from this repayment schedule line.",
    )
    is_repayment_move_posted = fields.Boolean(compute="_compute_is_repayment_move_posted")

    @api.depends("loan_id.name", "sequence", "due_date", "open_amount", "currency_id")
    def _compute_display_name(self):
        for line in self:
            date = format_date(self.env, line.due_date) if line.due_date else ""
            amount = line.currency_id.format(line.open_amount) if line.currency_id else line.open_amount
            line.display_name = _(
                "%(loan)s - Installment #%(sequence)s - %(date)s - Open %(amount)s",
                loan=line.loan_id.name or "",
                sequence=line.sequence or 0,
                date=date,
                amount=amount,
            )

    @api.depends("loan_id.line_ids", "due_date")
    def _compute_sequence(self):
        for loan in self.mapped("loan_id"):
            for index, line in enumerate(loan.line_ids.sorted("due_date"), start=1):
                line.sequence = index

    @api.depends("principal", "interest")
    def _compute_amounts(self):
        for line in self:
            line.payment = line.principal + line.interest

    def _get_posted_payment_moves(self):
        self.ensure_one()
        return (self.generated_move_ids | self.collection_move_ids).filtered(lambda move: move.state == "posted")

    @api.depends(
        "generated_move_ids.state",
        "generated_move_ids.line_ids.debit",
        "generated_move_ids.line_ids.credit",
        "collection_move_ids.state",
        "collection_move_ids.line_ids.debit",
        "collection_move_ids.line_ids.credit",
    )
    def _compute_paid_amounts(self):
        for line in self:
            paid_principal = 0.0
            paid_interest = 0.0
            for move in line._get_posted_payment_moves():
                paid_principal += sum(move.line_ids.filtered(lambda item: item.account_id == line.loan_id.receivable_account_id).mapped("credit"))
                paid_interest += sum(move.line_ids.filtered(lambda item: item.account_id == line.loan_id.interest_income_account_id).mapped("credit"))
            line.paid_principal = paid_principal
            line.paid_interest = paid_interest
            line.paid_amount = paid_principal + paid_interest
            line.open_amount = max(line.payment - line.paid_amount, 0.0)

    @api.depends("generated_move_ids.state")
    def _compute_is_repayment_move_posted(self):
        for line in self:
            line.is_repayment_move_posted = any(move.state == "posted" for move in line.generated_move_ids)

    @api.depends("paid_amount", "payment", "due_date")
    def _compute_state(self):
        today = fields.Date.context_today(self)
        for line in self:
            rounding = line.currency_id.rounding or 0.01
            if float_is_zero(line.open_amount, precision_rounding=rounding):
                line.state = "paid"
            elif line.paid_amount:
                line.state = "partial"
            elif line.due_date and line.due_date < today:
                line.state = "overdue"
            else:
                line.state = "open"

    def action_collect_wizard(self):
        self.ensure_one()
        if self.loan_id.state not in ("running", "disbursed"):
            raise UserError(_("Collections are allowed only after disbursement."))
        if self.state == "paid":
            raise UserError(_("This installment is already paid."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Register Collection"),
            "res_model": "staff.loan.collection.wizard",
            "target": "new",
            "views": [(False, "form")],
            "context": {
                "default_loan_id": self.loan_id.id,
                "default_line_id": self.id,
                "default_amount": self.open_amount,
            },
        }

    def _post_collection_move(self, date, journal, amount, reference, remarks):
        self.ensure_one()
        loan = self.loan_id
        loan._require_accounting_settings()
        if amount <= 0:
            raise UserError(_("Collection amount must be positive."))
        if float_compare(amount, self.open_amount, precision_rounding=self.currency_id.rounding) > 0:
            raise UserError(_("Collection amount cannot exceed the installment open amount."))
        principal_amount, interest_amount = self._split_collection_amount(amount)
        partner = loan.employee_id.work_contact_id or loan.employee_id.user_id.partner_id

        draft_moves = self.generated_move_ids.filtered(lambda move: move.state == "draft")
        for draft_move in draft_moves:
            draft_move.unlink()

        move = self._create_repayment_move(
            date,
            journal,
            principal_amount,
            interest_amount,
            reference or loan.name,
            collection=True,
            partner=partner,
        )
        move.action_post()
        self.invalidate_recordset()

        remaining_principal = max(self.principal - self.paid_principal, 0.0)
        remaining_interest = max(self.interest - self.paid_interest, 0.0)
        if not float_is_zero(remaining_principal + remaining_interest, precision_rounding=self.currency_id.rounding):
            # Rebuild the remaining draft entry so the unpaid amount stays visible in posted entries and future collection flow.
            self._create_repayment_move(
                self.due_date + relativedelta(day=31),
                loan._get_loan_journal(),
                remaining_principal,
                remaining_interest,
                loan.reference or loan.name,
            )

        loan.invalidate_recordset()
        loan.message_post(
            body=_(
                "Collected %(amount)s for installment due on %(date)s. %(remarks)s",
                amount=loan.currency_id.format(amount),
                date=self.due_date,
                remarks=remarks or "",
            )
        )
        loan._refresh_state_after_collection()
        return move

    def _split_collection_amount(self, amount):
        self.ensure_one()
        remaining = amount
        principal_due = max(self.principal - self.paid_principal, 0.0)
        principal_amount = min(remaining, principal_due)
        remaining -= principal_amount
        interest_due = max(self.interest - self.paid_interest, 0.0)
        interest_amount = min(remaining, interest_due)
        return self.currency_id.round(principal_amount), self.currency_id.round(interest_amount)

    def _create_repayment_move(self, date, journal, principal_amount, interest_amount, reference, collection=False, partner=False):
        self.ensure_one()
        loan = self.loan_id
        amount = principal_amount + interest_amount
        if float_is_zero(amount, precision_rounding=self.currency_id.rounding):
            return self.env["account.move"]

        partner = partner or loan.employee_id.work_contact_id or loan.employee_id.user_id.partner_id
        date_label = format_date(self.env, self.due_date, date_format="MM/y")
        lines = [
            loan._make_move_line_vals(
                loan.collection_account_id,
                debit=amount,
                name=_("%s - Staff Loan Collection %s") % (loan.name, date_label),
                partner=partner,
            )
        ]
        if principal_amount:
            lines.append(
                loan._make_move_line_vals(
                    loan.receivable_account_id,
                    credit=principal_amount,
                    name=_("%s - Principal %s") % (loan.name, date_label),
                    partner=partner,
                )
            )
        if interest_amount:
            lines.append(
                loan._make_move_line_vals(
                    loan.interest_income_account_id,
                    credit=interest_amount,
                    name=_("%s - Interest %s") % (loan.name, date_label),
                    partner=partner,
                )
            )
        return self.env["account.move"].with_company(loan.company_id).create({
            "company_id": loan.company_id.id,
            "date": date,
            "journal_id": journal.id,
            "ref": _("%(loan)s - Principal & Interest %(date)s", loan=reference or loan.name, date=date_label),
            "staff_loan_id": loan.id,
            "staff_loan_line_id": self.id,
            "is_staff_loan_repayment_move": True,
            "is_staff_loan_collection": collection,
            "line_ids": lines,
        })
