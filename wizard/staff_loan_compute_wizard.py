from dateutil.relativedelta import relativedelta

from odoo import _, Command, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_is_zero


class StaffLoanComputeWizard(models.TransientModel):
    _name = "staff.loan.compute.wizard"
    _description = "Staff Loan Compute Wizard"

    loan_id = fields.Many2one("staff.loan")
    currency_id = fields.Many2one(related="loan_id.currency_id")
    loan_amount = fields.Monetary(required=True)
    loan_date = fields.Date(required=True)
    skip_until = fields.Date()
    duration = fields.Integer(required=True)
    interest_type = fields.Selection(related="loan_id.interest_type", readonly=False)
    payment_anchor = fields.Selection(related="loan_id.payment_anchor", readonly=False)
    interest_rate = fields.Float(string="Interest Rate (%)", required=True)
    round_up = fields.Boolean(related="loan_id.round_up", readonly=False)
    rounding_decimal_places = fields.Integer(related="loan_id.rounding_decimal_places", readonly=False)
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
                "skip_until": loan.skip_until,
                "duration": loan.duration,
                "interest_type": loan.interest_type,
                "payment_anchor": loan.payment_anchor,
                "interest_rate": loan.interest_rate,
                "round_up": loan.round_up,
                "rounding_decimal_places": loan.rounding_decimal_places,
            })
        return res

    def _get_first_due_date(self):
        self.ensure_one()
        base_date = self.skip_until or self.loan_date
        if self.payment_anchor == "start_of_month":
            return base_date.replace(day=1)
        return base_date + relativedelta(day=31)

    def _round_schedule(self, values, total_interest):
        self.ensure_one()
        principal_diff = self.loan_amount - sum(item["principal"] for item in values)
        interest_diff = total_interest - sum(item["interest"] for item in values)
        values[-1]["principal"] += principal_diff
        values[-1]["interest"] += interest_diff
        values[-1]["payment"] = values[-1]["principal"] + values[-1]["interest"]
        values[-1]["balance"] = 0.0
        return values

    def _round_schedule_amount(self, amount):
        self.ensure_one()
        return self.loan_id._round_schedule_amount(amount)

    def _get_flat_schedule_values(self):
        self.ensure_one()
        if self.loan_amount <= 0:
            raise UserError(_("Loan amount must be positive."))
        if self.duration <= 0:
            raise UserError(_("Duration must be positive."))
        if self.interest_rate < 0:
            raise UserError(_("Interest rate cannot be negative."))

        total_interest = self._round_schedule_amount(self.loan_amount * self.interest_rate / 100.0)
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
                "principal": self._round_schedule_amount(principal),
                "interest": self._round_schedule_amount(interest_amount),
                "payment": self._round_schedule_amount(principal + interest_amount),
                "balance": self._round_schedule_amount(max(balance, 0.0)),
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
                "principal": self._round_schedule_amount(principal),
                "interest": self._round_schedule_amount(interest),
                "payment": self._round_schedule_amount(principal + interest),
                "balance": self._round_schedule_amount(max(balance, 0.0)),
            })
        total_interest = sum(item["interest"] for item in values)
        return self._round_schedule(values, total_interest)

    def _get_schedule_values(self):
        self.ensure_one()
        if self.interest_type == "emi":
            return self._get_emi_schedule_values()
        return self._get_flat_schedule_values()

    @api.depends("loan_amount", "loan_date", "skip_until", "duration", "interest_rate", "interest_type", "payment_anchor", "round_up", "rounding_decimal_places")
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
            "skip_until": self.skip_until,
            "duration": self.duration,
            "interest_type": self.interest_type,
            "payment_anchor": self.payment_anchor,
            "interest_rate": self.interest_rate,
            "round_up": self.round_up,
            "rounding_decimal_places": self.rounding_decimal_places,
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
