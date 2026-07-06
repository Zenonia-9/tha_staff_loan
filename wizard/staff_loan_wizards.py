from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _, Command
from odoo.exceptions import UserError
from odoo.tools import float_compare, float_is_zero, format_date


class StaffLoanComputeWizard(models.TransientModel):
    _name = "staff.loan.compute.wizard"
    _description = "Staff Loan Compute Wizard"

    loan_id = fields.Many2one("staff.loan")
    currency_id = fields.Many2one(related="loan_id.currency_id")
    loan_amount = fields.Monetary(required=True)
    loan_date = fields.Date(required=True)
    duration = fields.Integer(required=True)
    interest_type = fields.Selection(related="loan_id.interest_type", readonly=False)
    payment_anchor = fields.Selection(related="loan_id.payment_anchor", readonly=False)
    interest_rate = fields.Float(string="Interest Rate (%)", required=True)
    preview = fields.Text(compute="_compute_preview")

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        loan = self.env["staff.loan"].browse(self.env.context.get("default_loan_id"))
        if loan:
            res.update({
                "loan_id": loan.id,
                "loan_amount": loan.loan_amount,
                "loan_date": loan.loan_date,
                "duration": loan.duration,
                "interest_type": loan.interest_type,
                "payment_anchor": loan.payment_anchor,
                "interest_rate": loan.interest_rate,
            })
        return res

    def _get_first_due_date(self):
        self.ensure_one()
        base_date = self.loan_date + relativedelta(months=1)
        if self.payment_anchor == "start_of_month":
            return base_date.replace(day=1)
        return base_date + relativedelta(day=31)

    def _round_schedule(self, values, total_interest):
        self.ensure_one()
        principal_diff = self.currency_id.round(self.loan_amount - sum(item["principal"] for item in values))
        interest_diff = self.currency_id.round(total_interest - sum(item["interest"] for item in values))
        values[-1]["principal"] = self.currency_id.round(values[-1]["principal"] + principal_diff)
        values[-1]["interest"] = self.currency_id.round(values[-1]["interest"] + interest_diff)
        values[-1]["payment"] = self.currency_id.round(values[-1]["principal"] + values[-1]["interest"])
        values[-1]["balance"] = 0.0
        return values

    def _get_flat_schedule_values(self):
        self.ensure_one()
        if self.loan_amount <= 0:
            raise UserError(_("Loan amount must be positive."))
        if self.duration <= 0:
            raise UserError(_("Duration must be positive."))
        if self.interest_rate < 0:
            raise UserError(_("Interest rate cannot be negative."))

        total_interest = self.loan_amount * self.interest_rate / 100.0
        principal_amount = self.loan_amount / self.duration
        interest_amount = total_interest / self.duration
        balance = self.loan_amount
        first_due_date = self._get_first_due_date()
        values = []
        for index in range(self.duration):
            principal = principal_amount
            if index == self.duration - 1:
                principal = balance
            balance -= principal
            values.append({
                "due_date": first_due_date + relativedelta(months=index),
                "principal": self.currency_id.round(principal),
                "interest": self.currency_id.round(interest_amount),
                "payment": self.currency_id.round(principal + interest_amount),
                "balance": self.currency_id.round(max(balance, 0.0)),
            })
        return self._round_schedule(values, total_interest)

    def _get_emi_schedule_values(self):
        self.ensure_one()
        if self.loan_amount <= 0:
            raise UserError(_("Loan amount must be positive."))
        if self.duration <= 0:
            raise UserError(_("Duration must be positive."))
        if self.interest_rate < 0:
            raise UserError(_("Interest rate cannot be negative."))

        monthly_rate = self.interest_rate / 12.0 / 100.0
        balance = self.loan_amount
        first_due_date = self._get_first_due_date()
        if float_is_zero(monthly_rate, precision_digits=12):
            emi_amount = self.loan_amount / self.duration
        else:
            factor = (1 + monthly_rate) ** self.duration
            emi_amount = (self.loan_amount * monthly_rate * factor) / (factor - 1)

        values = []
        for index in range(self.duration):
            interest = balance * monthly_rate
            principal = emi_amount - interest
            if index == self.duration - 1:
                principal = balance
                interest = emi_amount - principal if not float_is_zero(monthly_rate, precision_digits=12) else 0.0
            balance -= principal
            values.append({
                "due_date": first_due_date + relativedelta(months=index),
                "principal": self.currency_id.round(principal),
                "interest": self.currency_id.round(interest),
                "payment": self.currency_id.round(principal + interest),
                "balance": self.currency_id.round(max(balance, 0.0)),
            })
        total_interest = sum(item["interest"] for item in values)
        return self._round_schedule(values, total_interest)

    def _get_schedule_values(self):
        self.ensure_one()
        if self.interest_type == "emi":
            return self._get_emi_schedule_values()
        return self._get_flat_schedule_values()

    @api.depends("loan_amount", "loan_date", "duration", "interest_rate", "interest_type", "payment_anchor")
    def _compute_preview(self):
        for wizard in self:
            if not wizard.loan_amount or not wizard.duration or not wizard.loan_date:
                wizard.preview = ""
                continue
            lines = wizard._get_schedule_values()
            preview = "{:<12} {:>15} {:>15} {:>15} {:>15}\n".format(_("Due Date"), _("Principal"), _("Interest"), _("Payment"), _("Balance"))
            for item in lines[:5]:
                preview += "{:<12} {:>15} {:>15} {:>15} {:>15}\n".format(
                    fields.Date.to_string(item["due_date"]),
                    wizard.currency_id.format(item["principal"]),
                    wizard.currency_id.format(item["interest"]),
                    wizard.currency_id.format(item["payment"]),
                    wizard.currency_id.format(item["balance"]),
                )
            if len(lines) > 10:
                preview += "{:<12} {:>15} {:>15} {:>15} {:>15}\n".format("...", "...", "...", "...", "...")
            for item in lines[-5:] if len(lines) > 5 else []:
                preview += "{:<12} {:>15} {:>15} {:>15} {:>15}\n".format(
                    fields.Date.to_string(item["due_date"]),
                    wizard.currency_id.format(item["principal"]),
                    wizard.currency_id.format(item["interest"]),
                    wizard.currency_id.format(item["payment"]),
                    wizard.currency_id.format(item["balance"]),
                )
            wizard.preview = preview

    def action_compute(self):
        self.ensure_one()
        loan = self.loan_id
        if loan.state != "draft":
            raise UserError(_("Schedule can only be computed in Draft."))
        lines = self._get_schedule_values()
        loan.line_ids.unlink()
        loan.write({
            "loan_amount": self.loan_amount,
            "loan_date": self.loan_date,
            "duration": self.duration,
            "interest_type": self.interest_type,
            "payment_anchor": self.payment_anchor,
            "interest_rate": self.interest_rate,
            "line_ids": [
                Command.create({
                    "due_date": item["due_date"],
                    "principal": item["principal"],
                    "interest": item["interest"],
                    "balance": item["balance"],
                }) for item in lines
            ],
        })
        loan.message_post(body=_("Repayment schedule computed."))
        return {"type": "ir.actions.act_window_close"}


class StaffLoanApproveWizard(models.TransientModel):
    _name = "staff.loan.approve.wizard"
    _description = "Staff Loan Approval Wizard"

    loan_id = fields.Many2one("staff.loan", required=True)
    approval_date = fields.Date(default=fields.Date.context_today, required=True)
    remarks = fields.Text()

    def action_approve(self):
        self.ensure_one()
        loan = self.loan_id
        if loan.state != "draft":
            raise UserError(_("Only draft loans can be approved."))
        loan._require_schedule()
        loan.write({
            "state": "approved",
            "approved_by_id": self.env.user.id,
            "approval_date": self.approval_date,
            "approval_remarks": self.remarks,
        })
        loan.message_post(body=_("Loan approved on %(date)s. %(remarks)s", date=self.approval_date, remarks=self.remarks or ""))
        return {"type": "ir.actions.act_window_close"}


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
                "journal_id": loan.collection_journal_id.id or loan._get_loan_journal().id,
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
        if float_compare(self.amount, self.line_id.open_amount, precision_rounding=self.currency_id.rounding) > 0:
            raise UserError(_("Collection amount cannot exceed the installment open amount."))
        self.line_id._post_collection_move(self.collection_date, self.journal_id, self.amount, self.reference, self.remarks)
        return {"type": "ir.actions.act_window_close"}


class StaffLoanCloseWizard(models.TransientModel):
    _name = "staff.loan.close.wizard"
    _description = "Staff Loan Close Wizard"

    loan_id = fields.Many2one("staff.loan", required=True)
    currency_id = fields.Many2one(related="loan_id.currency_id")
    loan_amount = fields.Monetary(related="loan_id.loan_amount", currency_field="currency_id")
    total_interest = fields.Monetary(related="loan_id.total_interest", currency_field="currency_id")
    total_payment = fields.Monetary(related="loan_id.total_payment", currency_field="currency_id")
    paid_amount = fields.Monetary(related="loan_id.paid_amount", currency_field="currency_id")
    outstanding_balance = fields.Monetary(related="loan_id.outstanding_balance", currency_field="currency_id")
    close_date = fields.Date(default=fields.Date.context_today, required=True)
    remarks = fields.Text()

    def action_close(self):
        self.ensure_one()
        loan = self.loan_id
        if not float_is_zero(loan.outstanding_balance, precision_rounding=loan.currency_id.rounding):
            raise UserError(_("You can close the staff loan only when the outstanding balance is zero."))
        loan.line_ids.generated_move_ids.filtered(
            lambda move: move.staff_loan_line_id.due_date > self.close_date and move.state == "draft"
        ).unlink()
        loan.write({
            "state": "closed",
            "close_date": self.close_date,
            "close_remarks": self.remarks,
        })
        loan.message_post(body=_(
            "Closed on the %(date)s. %(remarks)s",
            date=format_date(self.env, self.close_date),
            remarks=self.remarks or "",
        ))
        return {"type": "ir.actions.act_window_close"}


class StaffLoanCancelWizard(models.TransientModel):
    _name = "staff.loan.cancel.wizard"
    _description = "Staff Loan Cancel Wizard"

    loan_id = fields.Many2one("staff.loan", required=True)
    cancel_date = fields.Date(default=fields.Date.context_today, required=True)
    reason = fields.Text(required=True)

    def action_cancel(self):
        self.ensure_one()
        loan = self.loan_id
        if loan.state not in ("draft", "approved"):
            raise UserError(_("Only Draft or Approved loans can be cancelled directly."))
        loan.write({
            "state": "cancelled",
            "cancel_date": self.cancel_date,
            "cancel_reason": self.reason,
        })
        loan.message_post(body=_("Loan cancelled on %(date)s. %(reason)s", date=self.cancel_date, reason=self.reason))
        return {"type": "ir.actions.act_window_close"}


class StaffLoanDocumentWizard(models.TransientModel):
    _name = "staff.loan.document.wizard"
    _description = "Staff Loan Document Upload Wizard"

    loan_id = fields.Many2one("staff.loan", required=True)
    file = fields.Binary(required=True, attachment=False)
    file_name = fields.Char(required=True)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        loan_id = self.env.context.get("default_loan_id")
        if not loan_id and self.env.context.get("active_model") == "staff.loan":
            loan_id = self.env.context.get("active_id")
        loan = self.env["staff.loan"].browse(loan_id)
        if loan:
            res["loan_id"] = loan.id
        return res

    def action_upload(self):
        self.ensure_one()
        loan = self.loan_id
        if not loan and self.env.context.get("active_model") == "staff.loan":
            loan = self.env["staff.loan"].browse(self.env.context.get("active_id"))
        if not loan:
            raise UserError(_("The upload must be opened from a staff loan."))
        name = self.file_name
        self.env["ir.attachment"].create({
            "name": name,
            "datas": self.file,
            "res_model": "staff.loan",
            "res_id": loan.id,
            "company_id": loan.company_id.id,
        })
        loan.message_post(body=_("Document uploaded: %s", name))
        return {"type": "ir.actions.act_window_close"}
