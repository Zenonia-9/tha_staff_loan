from dateutil.relativedelta import relativedelta

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError


class StaffLoanComputeWizard(models.TransientModel):
    _name = "staff.loan.compute.wizard"
    _description = "Staff Loan Compute Wizard"

    loan_id = fields.Many2one("staff.loan")
    currency_id = fields.Many2one(related="loan_id.currency_id")
    loan_amount = fields.Monetary(required=True)
    loan_date = fields.Date(required=True)
    first_payment_date = fields.Date(required=True)
    duration = fields.Integer(required=True)
    interest_rate = fields.Float(string="Interest Rate (%)", required=True)
    preview = fields.Text(compute="_compute_preview")

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        loan = self.env["staff.loan"].browse(self.env.context.get("default_loan_id"))
        if loan:
            values.update({
                "loan_id": loan.id,
                "loan_amount": loan.loan_amount,
                "loan_date": loan.loan_date,
                "first_payment_date": loan.first_payment_date,
                "duration": loan.duration,
                "interest_rate": loan.interest_rate,
            })
        return values

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
                })
                for item in lines
            ],
        })
        loan.message_post(body=_("Repayment schedule computed."))
        return {"type": "ir.actions.act_window_close"}
