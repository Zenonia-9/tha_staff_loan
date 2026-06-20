from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _, Command
from odoo.exceptions import UserError
from odoo.tools import float_compare, format_date


class StaffLoanComputeWizard(models.TransientModel):
    _name = "staff.loan.compute.wizard"
    _description = "Staff Loan Compute Wizard"

    loan_id = fields.Many2one("staff.loan", required=True)
    currency_id = fields.Many2one(related="loan_id.currency_id")
    loan_amount = fields.Monetary(required=True)
    loan_date = fields.Date(required=True)
    first_payment_date = fields.Date(required=True)
    duration = fields.Integer(required=True)
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
                "first_payment_date": loan.first_payment_date,
                "duration": loan.duration,
                "interest_rate": loan.interest_rate,
            })
        return res

    def _get_schedule_values(self):
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
        values = []
        for index in range(self.duration):
            principal = principal_amount
            if index == self.duration - 1:
                principal = balance
            balance -= principal
            values.append({
                "due_date": self.first_payment_date + relativedelta(months=index),
                "principal": self.currency_id.round(principal),
                "interest": self.currency_id.round(interest_amount),
                "balance": self.currency_id.round(max(balance, 0.0)),
            })
        principal_diff = self.currency_id.round(self.loan_amount - sum(item["principal"] for item in values))
        interest_diff = self.currency_id.round(total_interest - sum(item["interest"] for item in values))
        values[-1]["principal"] = self.currency_id.round(values[-1]["principal"] + principal_diff)
        values[-1]["interest"] = self.currency_id.round(values[-1]["interest"] + interest_diff)
        values[-1]["balance"] = 0.0
        return values

    @api.depends("loan_amount", "first_payment_date", "duration", "interest_rate")
    def _compute_preview(self):
        for wizard in self:
            if not wizard.loan_amount or not wizard.duration or not wizard.first_payment_date:
                wizard.preview = ""
                continue
            lines = wizard._get_schedule_values()
            preview = "{:<12} {:>15} {:>15} {:>15} {:>15}\n".format(_("Due Date"), _("Principal"), _("Interest"), _("Payment"), _("Balance"))
            for item in lines[:5]:
                payment = item["principal"] + item["interest"]
                preview += "{:<12} {:>15} {:>15} {:>15} {:>15}\n".format(
                    fields.Date.to_string(item["due_date"]),
                    wizard.currency_id.format(item["principal"]),
                    wizard.currency_id.format(item["interest"]),
                    wizard.currency_id.format(payment),
                    wizard.currency_id.format(item["balance"]),
                )
            if len(lines) > 10:
                preview += "{:<12} {:>15} {:>15} {:>15} {:>15}\n".format("...", "...", "...", "...", "...")
            for item in lines[-5:] if len(lines) > 5 else []:
                payment = item["principal"] + item["interest"]
                preview += "{:<12} {:>15} {:>15} {:>15} {:>15}\n".format(
                    fields.Date.to_string(item["due_date"]),
                    wizard.currency_id.format(item["principal"]),
                    wizard.currency_id.format(item["interest"]),
                    wizard.currency_id.format(payment),
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
            "first_payment_date": self.first_payment_date,
            "duration": self.duration,
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
                "journal_id": loan.disbursement_journal_id.id,
                "reference": loan.reference or loan.name,
            })
        return res

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
        res = super().default_get(fields_list)
        loan = self.env["staff.loan"].browse(self.env.context.get("default_loan_id"))
        line = self.env["staff.loan.line"].browse(self.env.context.get("default_line_id"))
        if loan:
            res.update({
                "loan_id": loan.id,
                "journal_id": loan.collection_journal_id.id,
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
    close_date = fields.Date(default=fields.Date.context_today, required=True)
    remarks = fields.Text()

    def action_close(self):
        self.ensure_one()
        loan = self.loan_id
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
