from odoo import _, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_is_zero
from odoo.tools.misc import format_date


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
        loan.line_ids.generated_move_ids.filtered(lambda move: move.staff_loan_line_id.due_date > self.close_date and move.state == "draft").unlink()
        loan.write({
            "state": "closed",
            "close_date": self.close_date,
            "close_remarks": self.remarks,
        })
        loan.message_post(
            body=_(
                "Closed on the %(date)s. %(remarks)s",
                date=format_date(self.env, self.close_date),
                remarks=self.remarks or "",
            )
        )
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
