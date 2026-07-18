from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare, float_is_zero, format_date


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
    is_exception = fields.Boolean(default=False, copy=False)
    exception_amount = fields.Monetary(copy=False)
    exception_reference = fields.Char(copy=False)
    exception_reason = fields.Text(copy=False)
    exception_date = fields.Date(copy=False)
    exception_interest_paid = fields.Monetary(copy=False)
    exception_principal_paid = fields.Monetary(copy=False)
    exception_remaining_principal = fields.Monetary(copy=False)
    exception_schedule_updated = fields.Boolean(copy=False, default=False)
    settlement_move_id = fields.Many2one("account.move", copy=False, readonly=True)
    is_overdue = fields.Boolean(compute="_compute_is_overdue")
    paid_principal = fields.Monetary(compute="_compute_paid_amounts", store=True)
    paid_interest = fields.Monetary(compute="_compute_paid_amounts", store=True)
    paid_amount = fields.Monetary(compute="_compute_paid_amounts", store=True)
    open_amount = fields.Monetary(compute="_compute_paid_amounts", store=True)
    state = fields.Selection(
        [
            ("unpaid", "Receivable"),
            ("paid", "Received"),
            ("exception", "Exception"),
        ],
        string="Status",
        compute="_compute_state",
        store=True,
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
        return self.collection_move_ids.filtered(lambda move: move.state == "posted" and not move.reversal_move_ids)

    def _get_effective_settlement_move(self):
        self.ensure_one()
        if self.settlement_move_id and self.settlement_move_id.state == "posted" and not self.settlement_move_id.reversal_move_ids:
            return self.settlement_move_id
        return self.env["account.move"]

    def _get_exception_interest_paid_value(self):
        self.ensure_one()
        if self.exception_interest_paid:
            return self.exception_interest_paid
        return min(self.interest, self.exception_amount)

    def _get_exception_principal_paid_value(self):
        self.ensure_one()
        if self.exception_principal_paid:
            return self.exception_principal_paid
        interest_paid = self._get_exception_interest_paid_value()
        return min(max(self.exception_amount - interest_paid, 0.0), self.principal)

    def _get_exception_remaining_principal_value(self):
        self.ensure_one()
        if self.exception_remaining_principal:
            return self.exception_remaining_principal
        return max(self.principal - self._get_exception_principal_paid_value(), 0.0)

    def _get_exception_outstanding_balance_value(self):
        self.ensure_one()
        future_principal = sum(
            self.loan_id.line_ids.filtered(lambda line: line.due_date > self.due_date and line.state == "unpaid").mapped("principal")
        )
        if self.exception_schedule_updated:
            return self.currency_id.round(future_principal)
        return self.currency_id.round(future_principal + self._get_exception_remaining_principal_value())

    def _sync_exception_balance(self):
        self.ensure_one()
        if not self.is_exception:
            return
        self.write({"balance": self._get_exception_outstanding_balance_value()})

    def _normalize_exception_values(self):
        self.ensure_one()
        if not self.is_exception:
            return
        vals = {}
        if not self.exception_principal_paid or not self.exception_remaining_principal:
            interest_paid = self.currency_id.round(self._get_exception_interest_paid_value())
            principal_paid = self.currency_id.round(self._get_exception_principal_paid_value())
            remaining_principal = self.currency_id.round(max(self.principal - principal_paid, 0.0))
            vals.update({
                "exception_interest_paid": interest_paid,
                "exception_principal_paid": principal_paid,
                "exception_remaining_principal": remaining_principal,
                "principal": principal_paid,
            })
        if vals:
            self.write(vals)
        self._sync_exception_balance()

    @api.depends(
        "is_exception",
        "exception_amount",
        "exception_interest_paid",
        "exception_principal_paid",
        "exception_remaining_principal",
        "exception_schedule_updated",
        "collection_move_ids.state",
        "collection_move_ids.reversal_move_ids",
        "collection_move_ids.line_ids.debit",
        "collection_move_ids.line_ids.credit",
        "settlement_move_id.state",
        "settlement_move_id.reversal_move_ids",
    )
    def _compute_paid_amounts(self):
        for line in self:
            if line.is_exception:
                paid_principal = line._get_exception_principal_paid_value()
                paid_interest = line._get_exception_interest_paid_value()
                paid_amount = paid_principal + paid_interest
                open_amount = 0.0 if line.exception_schedule_updated else line._get_exception_remaining_principal_value()
            elif line._get_effective_settlement_move():
                paid_amount = line.payment
                open_amount = 0.0
                paid_principal = min(paid_amount, line.principal)
                paid_interest = min(max(paid_amount - paid_principal, 0.0), line.interest)
            else:
                paid_amount = 0.0
                for move in line._get_posted_payment_moves():
                    paid_amount += sum(move.line_ids.filtered(lambda item: item.account_id == line.loan_id.receivable_account_id).mapped("credit"))
                paid_amount = min(paid_amount, line.payment)
                open_amount = max(line.payment - paid_amount, 0.0)
                paid_principal = min(paid_amount, line.principal)
                paid_interest = min(max(paid_amount - paid_principal, 0.0), line.interest)
            line.paid_principal = line.currency_id.round(paid_principal)
            line.paid_interest = line.currency_id.round(paid_interest)
            line.paid_amount = line.currency_id.round(paid_amount)
            line.open_amount = line.currency_id.round(open_amount)

    @api.depends("generated_move_ids.state")
    def _compute_is_repayment_move_posted(self):
        for line in self:
            line.is_repayment_move_posted = any(move.state == "posted" for move in line.generated_move_ids)

    @api.depends(
        "is_exception",
        "open_amount",
        "collection_move_ids.state",
        "collection_move_ids.reversal_move_ids",
        "settlement_move_id.state",
        "settlement_move_id.reversal_move_ids",
    )
    def _compute_state(self):
        for line in self:
            rounding = line.currency_id.rounding or 0.01
            if line.is_exception:
                line.state = "exception"
            elif float_is_zero(line.open_amount, precision_rounding=rounding):
                line.state = "paid"
            else:
                line.state = "unpaid"

    @api.depends("due_date", "state")
    def _compute_is_overdue(self):
        today = fields.Date.context_today(self)
        for line in self:
            line.is_overdue = bool(line.due_date and line.state == "unpaid" and line.due_date < today)

    def action_collect_wizard(self):
        self.ensure_one()
        if self.loan_id.state not in ("running", "disbursed"):
            raise UserError(_("Collections are allowed only after disbursement."))
        if self.state != "unpaid":
            raise UserError(_("Only unpaid installments can be collected."))
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

    def action_manual_exception_wizard(self):
        self.ensure_one()
        if self.loan_id.state not in ("running", "disbursed"):
            raise UserError(_("Manual exceptions are allowed only after disbursement."))
        if self.state != "unpaid":
            raise UserError(_("Only unpaid installments can be marked as exception."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Manual Exception"),
            "res_model": "staff.loan.exception.wizard",
            "target": "new",
            "views": [(False, "form")],
            "context": {
                "default_loan_id": self.loan_id.id,
                "default_line_id": self.id,
                "default_exception_amount": self.open_amount,
            },
        }

    def _post_collection_move(self, date, journal, amount, reference, remarks):
        self.ensure_one()
        loan = self.loan_id
        loan._require_accounting_settings()
        if self.state != "unpaid":
            raise UserError(_("Only unpaid installments can be collected."))
        if amount <= 0:
            raise UserError(_("Collection amount must be positive."))
        if float_compare(amount, self.open_amount, precision_rounding=self.currency_id.rounding) != 0:
            raise UserError(_("Collection amount must exactly match the full scheduled amount."))
        partner = loan.employee_id.work_contact_id or loan.employee_id.user_id.partner_id
        move = self._create_collection_move(
            date,
            journal,
            amount,
            reference or loan.name,
            partner=partner,
        )
        move.action_post()
        self._post_interest_recognition_on_collection(date, journal, reference or loan.name, partner=partner)
        self.invalidate_recordset()
        loan.invalidate_recordset()
        loan.message_post(body=_(
            "Collected %(amount)s for installment due on %(date)s. %(remarks)s",
            amount=loan.currency_id.format(amount),
            date=self.due_date,
            remarks=remarks or "",
        ))
        loan._refresh_state_after_collection()
        return move

    def _apply_exception(self, date, journal, amount, reference, reason):
        self.ensure_one()
        loan = self.loan_id
        loan._require_accounting_settings()
        if self.state != "unpaid":
            raise UserError(_("Only unpaid installments can be marked as exception."))
        if amount <= 0:
            raise UserError(_("Exception amount must be positive."))
        if float_compare(amount, self.open_amount, precision_rounding=self.currency_id.rounding) >= 0:
            raise UserError(_("Use Collect for the full scheduled amount. Exception is only for partial payment."))
        if float_compare(amount, self.interest, precision_rounding=self.currency_id.rounding) < 0:
            raise UserError(_("Exception amount must cover the full scheduled interest for the installment."))
        partner = loan.employee_id.work_contact_id or loan.employee_id.user_id.partner_id
        exception_principal_paid = self.currency_id.round(min(max(amount - self.interest, 0.0), self.principal))
        remaining_principal = self.currency_id.round(max(self.principal - exception_principal_paid, 0.0))
        future_principal = sum(
            loan.line_ids.filtered(lambda line: line.due_date > self.due_date and line.state == "unpaid").mapped("principal")
        )
        move = self._create_collection_move(
            date,
            journal,
            amount,
            reference or loan.name,
            partner=partner,
        )
        move.action_post()
        self._post_interest_recognition_on_collection(date, journal, reference or loan.name, partner=partner)
        self.write({
            "is_exception": True,
            "exception_amount": amount,
            "exception_reference": reference,
            "exception_reason": reason,
            "exception_date": date or fields.Date.context_today(self),
            "exception_interest_paid": self.interest,
            "exception_principal_paid": exception_principal_paid,
            "exception_remaining_principal": remaining_principal,
            "exception_schedule_updated": False,
            "principal": exception_principal_paid,
            "balance": self.currency_id.round(future_principal + remaining_principal),
        })
        loan.message_post(body=_(
            "Installment due on %(date)s posted as exception. Paid %(amount)s, principal paid %(principal)s, remaining principal %(remaining)s. Ref %(reference)s. %(reason)s",
            date=self.due_date,
            amount=loan.currency_id.format(amount),
            principal=loan.currency_id.format(exception_principal_paid),
            remaining=loan.currency_id.format(remaining_principal),
            reference=reference or "-",
            reason=reason or "",
        ))
        self.invalidate_recordset()
        loan.invalidate_recordset()
        return move

    def _post_interest_recognition_on_collection(self, date, journal, reference, partner=False):
        self.ensure_one()
        loan = self.loan_id
        recognition_move = self.generated_move_ids.filtered(
            lambda move: move.state != "cancel" and not move.reversal_move_ids
        )[:1]
        if recognition_move and recognition_move.state == "posted":
            return recognition_move
        if not recognition_move:
            recognition_move = self._create_interest_recognition_move(date, journal, reference, partner=partner)
        else:
            recognition_move.write({
                "date": date,
                "auto_post": "no",
            })
        self.invalidate_recordset(["open_amount", "state"])
        loan.line_ids.invalidate_recordset(["open_amount", "state"])
        if all(
            float_is_zero(line.open_amount, precision_rounding=line.currency_id.rounding)
            for line in loan.line_ids
        ):
            loan._add_exception_adjustment_to_move(recognition_move)
        recognition_move.action_post()
        return recognition_move

    def _create_interest_recognition_move(self, date, journal, reference, partner=False):
        self.ensure_one()
        loan = self.loan_id
        if float_is_zero(self.interest, precision_rounding=self.currency_id.rounding):
            return self.env["account.move"]
        partner = partner or loan.employee_id.work_contact_id or loan.employee_id.user_id.partner_id
        date_label = format_date(self.env, self.due_date, date_format="MM/y")
        return self.env["account.move"].with_company(loan.company_id).create({
            "company_id": loan.company_id.id,
            "date": date,
            "auto_post": "at_date",
            "journal_id": journal.id,
            "ref": _("%(loan)s - Interest Recognition %(date)s", loan=reference or loan.name, date=date_label),
            "staff_loan_id": loan.id,
            "staff_loan_line_id": self.id,
            "is_staff_loan_repayment_move": True,
            "line_ids": [
                loan._make_move_line_vals(
                    loan.deferred_account_id,
                    debit=self.interest,
                    name=_("%s - Deferred Interest %s") % (loan.name, date_label),
                    partner=partner,
                ),
                loan._make_move_line_vals(
                    loan.interest_income_account_id,
                    credit=self.interest,
                    name=_("%s - Interest Income %s") % (loan.name, date_label),
                    partner=partner,
                ),
            ],
        })

    def _create_collection_move(self, date, journal, amount, reference, partner=False):
        self.ensure_one()
        loan = self.loan_id
        if float_is_zero(amount, precision_rounding=self.currency_id.rounding):
            return self.env["account.move"]
        partner = partner or loan.employee_id.work_contact_id or loan.employee_id.user_id.partner_id
        date_label = format_date(self.env, self.due_date, date_format="MM/y")
        return self.env["account.move"].with_company(loan.company_id).create({
            "company_id": loan.company_id.id,
            "date": date,
            "journal_id": journal.id,
            "ref": _("%(loan)s - Collection %(date)s", loan=reference or loan.name, date=date_label),
            "staff_loan_id": loan.id,
            "staff_loan_line_id": self.id,
            "is_staff_loan_collection": True,
            "line_ids": [
                loan._make_move_line_vals(
                    loan.collection_account_id,
                    debit=amount,
                    name=_("%s - Staff Loan Collection %s") % (loan.name, date_label),
                    partner=partner,
                ),
                loan._make_move_line_vals(
                    loan.receivable_account_id,
                    credit=amount,
                    name=_("%s - Receivable Settlement %s") % (loan.name, date_label),
                    partner=partner,
                ),
            ],
        })
