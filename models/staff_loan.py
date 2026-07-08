from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _, Command
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare, float_is_zero
from odoo.tools.misc import format_date


class StaffLoan(models.Model):
    _name = "staff.loan"
    _description = "Staff Loan"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "loan_date desc, id desc"

    name = fields.Char(
        string="Loan No.",
        required=True,
        default="/",
        copy=False,
        tracking=True,
        index="trigram",
    )
    employee_id = fields.Many2one(
        "hr.employee",
        string="Staff",
        required=True,
        tracking=True,
        domain="[('company_id', 'in', [False, company_id])]",
    )
    department_id = fields.Many2one(
        "hr.department",
        string="Department",
        related="employee_id.department_id",
        store=True,
        readonly=True,
    )
    branch_id = fields.Many2one(
        "hr.work.location",
        string="Branch",
        related="employee_id.work_location_id",
        store=True,
        readonly=True,
    )
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
        tracking=True,
    )
    currency_id = fields.Many2one(related="company_id.currency_id", store=True, readonly=True)
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("approved", "Approved"),
            ("disbursed", "Disbursed"),
            ("running", "Running"),
            ("closed", "Closed"),
            ("cancelled", "Cancelled"),
        ],
        string="Status",
        default="draft",
        required=True,
        tracking=True,
    )

    loan_amount = fields.Monetary(required=True, tracking=True)
    loan_date = fields.Date(required=True, default=fields.Date.context_today, tracking=True)
    duration = fields.Integer(string="Duration", required=True, default=12, tracking=True)
    payment_frequency = fields.Selection(
        [("monthly", "Monthly")],
        default="monthly",
        required=True,
        tracking=True,
    )
    interest_type = fields.Selection(
        [("flat", "Flat Rate"), ("emi", "EMI")],
        default="flat",
        required=True,
        tracking=True,
    )
    payment_anchor = fields.Selection(
        [("start_of_month", "Start of Month"), ("end_of_month", "End of Month")],
        default="end_of_month",
        required=True,
        tracking=True,
    )
    interest_rate = fields.Float(string="Interest Rate (%)", default=2.0, tracking=True)
    disbursement_date = fields.Date(tracking=True)
    reference = fields.Char(string="Loan Reference", tracking=True)
    notes = fields.Html()

    receivable_account_id = fields.Many2one(
        "account.account",
        string="Receivable Account",
        tracking=True,
        domain="[('account_type', 'in', ('asset_current', 'asset_receivable')), ('company_ids', 'in', company_id)]",
    )
    interest_income_account_id = fields.Many2one(
        "account.account",
        string="Income Account",
        tracking=True,
        domain="[('account_type', 'in', ('income', 'income_other')), ('company_ids', 'in', company_id)]",
    )
    disbursement_journal_id = fields.Many2one(
        "account.journal",
        string="Journal",
        tracking=True,
        domain="[('type', 'in', ('cash', 'bank', 'general')), ('company_id', '=', company_id)]",
    )
    # Backward-compatible alias so any stale metadata still resolves to the single journal field.
    collection_journal_id = fields.Many2one(
        "account.journal",
        string="Collection Journal",
        related="disbursement_journal_id",
        readonly=False,
        store=False,
    )
    disbursement_account_id = fields.Many2one(
        "account.account",
        string="Disbursement Account",
        tracking=True,
        domain="[('company_ids', 'in', company_id)]",
        help="Credit account used when posting the staff loan disbursement. This keeps the journal independent from a default account.",
    )
    collection_account_id = fields.Many2one(
        "account.account",
        string="Collection Account",
        tracking=True,
        domain="[('company_ids', 'in', company_id)]",
        help="Debit account used by generated staff loan repayment entries. This keeps the collection journal independent from a default account.",
    )
    deferred_account_id = fields.Many2one(
        "account.account",
        string="Deferred Account",
        tracking=True,
        domain="[('account_type', 'in', ('liability_current', 'liability_non_current')), ('company_ids', 'in', company_id)]",
    )

    line_ids = fields.One2many("staff.loan.line", "loan_id", string="Repayment Schedule", copy=True)
    disbursement_move_id = fields.Many2one(
        "account.move",
        string="Disbursement Entry",
        readonly=True,
        copy=False,
    )
    collection_move_ids = fields.Many2many("account.move", string="Collection Entries", compute="_compute_collection_move_ids")
    approved_by_id = fields.Many2one("res.users", string="Approved By", readonly=True, copy=False)
    approval_date = fields.Date(readonly=True, copy=False)
    approval_remarks = fields.Text(readonly=True, copy=False)
    close_date = fields.Date(readonly=True, copy=False)
    close_remarks = fields.Text(readonly=True, copy=False)
    cancel_date = fields.Date(readonly=True, copy=False)
    cancel_reason = fields.Text(readonly=True, copy=False)

    total_interest = fields.Monetary(compute="_compute_totals", store=True)
    total_payment = fields.Monetary(compute="_compute_totals", store=True)
    paid_principal = fields.Monetary(compute="_compute_totals", store=True)
    paid_interest = fields.Monetary(compute="_compute_totals", store=True)
    paid_amount = fields.Monetary(compute="_compute_totals", store=True)
    outstanding_principal = fields.Monetary(compute="_compute_totals", store=True)
    outstanding_interest = fields.Monetary(compute="_compute_totals", store=True)
    outstanding_balance = fields.Monetary(compute="_compute_totals", store=True)
    installment_count = fields.Integer(compute="_compute_counts")
    paid_installment_count = fields.Integer(compute="_compute_counts")
    remaining_installment_count = fields.Integer(compute="_compute_counts")
    posted_entry_count = fields.Integer(compute="_compute_counts")
    document_count = fields.Integer(compute="_compute_counts")
    exception_update_pending = fields.Boolean(compute="_compute_exception_update_pending")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "/") == "/":
                vals["name"] = self.env["ir.sequence"].next_by_code("staff.loan") or "/"
        return super().create(vals_list)

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        accounting_fields = {
            "receivable_account_id",
            "interest_income_account_id",
            "disbursement_journal_id",
            "disbursement_account_id",
            "collection_account_id",
            "deferred_account_id",
        }
        if not accounting_fields.intersection(fields_list):
            return values
        previous_loan = self.search([
            ("company_id", "=", self.env.company.id),
            ("receivable_account_id", "!=", False),
            ("interest_income_account_id", "!=", False),
            ("disbursement_journal_id", "!=", False),
            ("disbursement_account_id", "!=", False),
            ("collection_account_id", "!=", False),
            ("deferred_account_id", "!=", False),
        ], limit=1)
        if previous_loan:
            for field_name in accounting_fields:
                if field_name in fields_list and previous_loan[field_name]:
                    values[field_name] = previous_loan[field_name].id
        return values

    @api.constrains("loan_amount", "duration", "interest_rate")
    def _check_positive_values(self):
        for loan in self:
            if float_compare(loan.loan_amount, 0.0, precision_rounding=loan.currency_id.rounding) <= 0:
                raise ValidationError(_("Loan amount must be positive."))
            if loan.duration <= 0:
                raise ValidationError(_("Duration must be positive."))
            if loan.interest_rate < 0:
                raise ValidationError(_("Interest rate cannot be negative."))

    @api.depends(
        "line_ids.interest",
        "line_ids.payment",
        "line_ids.paid_principal",
        "line_ids.paid_interest",
        "line_ids.paid_amount",
        "line_ids.open_amount",
        "line_ids.state",
    )
    def _compute_totals(self):
        for loan in self:
            loan.total_interest = sum(loan.line_ids.mapped("interest"))
            loan.total_payment = sum(loan.line_ids.mapped("payment"))
            loan.paid_principal = sum(loan.line_ids.mapped("paid_principal"))
            loan.paid_interest = sum(loan.line_ids.mapped("paid_interest"))
            loan.paid_amount = sum(loan.line_ids.mapped("paid_amount"))
            open_lines = loan.line_ids.filtered(
                lambda line: line.state in ("unpaid", "exception")
                and not float_is_zero(line.open_amount, precision_rounding=line.currency_id.rounding)
            )
            loan.outstanding_principal = sum(
                line._get_exception_remaining_principal_value()
                if line.state == "exception" and not line.exception_schedule_updated
                else max(line.principal - line.paid_principal, 0.0)
                for line in open_lines
            )
            loan.outstanding_interest = sum(
                0.0
                if line.state == "exception" and not line.exception_schedule_updated
                else max(line.interest - line.paid_interest, 0.0)
                for line in open_lines
            )
            loan.outstanding_balance = sum(open_lines.mapped("open_amount"))

    @api.depends("line_ids.collection_move_ids", "line_ids.collection_move_ids.state", "line_ids.collection_move_ids.reversal_move_ids")
    def _compute_collection_move_ids(self):
        for loan in self:
            loan.collection_move_ids = self.env["account.move"].search([
                ("staff_loan_id", "=", loan.id),
                ("is_staff_loan_collection", "=", True),
            ])

    def _get_entry_moves(self):
        self.ensure_one()
        return self.env["account.move"].search([("staff_loan_id", "=", self.id)])

    @api.depends(
        "line_ids.state",
        "line_ids.generated_move_ids",
        "line_ids.generated_move_ids.state",
        "line_ids.collection_move_ids",
        "line_ids.collection_move_ids.state",
        "disbursement_move_id",
        "disbursement_move_id.state",
        "message_attachment_count",
    )
    def _compute_counts(self):
        for loan in self:
            loan.installment_count = len(loan.line_ids)
            loan.paid_installment_count = len(loan.line_ids.filtered(lambda line: line.state == "paid"))
            loan.remaining_installment_count = len(loan.line_ids.filtered(lambda line: line.state == "unpaid"))
            moves = loan._get_entry_moves()
            loan.posted_entry_count = len(moves.filtered(lambda move: move.state == "posted"))
            loan.document_count = loan.message_attachment_count

    @api.depends(
        "line_ids.state",
        "line_ids.due_date",
        "line_ids.exception_schedule_updated",
        "line_ids.exception_remaining_principal",
    )
    def _compute_exception_update_pending(self):
        for loan in self:
            loan.exception_update_pending = bool(loan._get_exception_anchor_line())

    def _sync_runtime_state(self):
        for loan in self:
            if loan.state == "closed" and any(line.state == "unpaid" for line in loan.line_ids):
                loan.state = "running"

    def _check_company_consistency(self):
        for loan in self:
            company = loan.company_id
            accounts = (
                loan.receivable_account_id
                | loan.interest_income_account_id
                | loan.disbursement_account_id
                | loan.collection_account_id
                | loan.deferred_account_id
            )
            for account in accounts:
                if account and company not in account.company_ids:
                    raise UserError(_("Account %(account)s is not available for %(company)s.", account=account.display_name, company=company.display_name))
            for journal in loan.disbursement_journal_id:
                if journal and journal.company_id != company:
                    raise UserError(_("Journal %(journal)s does not belong to %(company)s.", journal=journal.display_name, company=company.display_name))

    def _require_schedule(self):
        for loan in self:
            if not loan.line_ids:
                raise UserError(_("Compute the repayment schedule first."))
            principal = loan.currency_id.round(sum(loan.line_ids.mapped("principal")))
            interest = loan.currency_id.round(sum(loan.line_ids.mapped("interest")))
            if float_compare(principal, loan.loan_amount, precision_rounding=loan.currency_id.rounding) != 0:
                raise UserError(_("The schedule principal total must equal the loan amount."))
            if float_compare(interest, loan.total_interest, precision_rounding=loan.currency_id.rounding) != 0:
                raise UserError(_("The schedule interest total must equal the computed loan interest."))
            if len(loan.line_ids) != loan.duration:
                raise UserError(_("The schedule installment count must equal the loan duration."))

    def _require_accounting_settings(self):
        for loan in self:
            if not loan.receivable_account_id:
                raise UserError(_("Set the Staff Loan Receivable Account."))
            if not loan.interest_income_account_id:
                raise UserError(_("Set the Income Account."))
            if not loan.disbursement_journal_id:
                raise UserError(_("Set the Journal."))
            if not loan.disbursement_account_id:
                raise UserError(_("Set the Disbursement Account."))
            if not loan.collection_account_id:
                raise UserError(_("Set the Collection Account."))
            if not loan.deferred_account_id:
                raise UserError(_("Set the Deferred Account."))
        self._check_company_consistency()

    def _get_loan_journal(self):
        self.ensure_one()
        return self.disbursement_journal_id

    def action_compute_schedule(self):
        self.ensure_one()
        if self.state != "draft":
            raise UserError(_("Schedule can only be computed in Draft."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Compute Schedule"),
            "res_model": "staff.loan.compute.wizard",
            "target": "new",
            "views": [(False, "form")],
            "context": {"default_loan_id": self.id},
        }

    def action_reset(self):
        self.ensure_one()
        if self.state != "draft":
            raise UserError(_("Only draft loans can be reset."))
        posted_moves = (self.line_ids.generated_move_ids | self.line_ids.collection_move_ids).filtered(lambda move: move.state == "posted")
        if posted_moves:
            raise UserError(_("You cannot reset a loan with posted repayment entries."))
        (self.line_ids.generated_move_ids | self.line_ids.collection_move_ids).filtered(lambda move: move.state == "draft").unlink()
        self.line_ids.unlink()
        self.message_post(body=_("Repayment schedule reset."))

    def action_set_to_draft(self):
        self.ensure_one()
        if self.state != "cancelled":
            raise UserError(_("Only cancelled loans can be set to draft."))
        moves = self._get_entry_moves().filtered(lambda move: move.state not in ("cancel",))
        if moves.filtered(lambda move: move.state == "posted"):
            raise UserError(_("You cannot set this loan to draft while posted entries are linked. Reverse or cancel the entries first."))
        moves.filtered(lambda move: move.state == "draft").unlink()
        self.write({
            "state": "draft",
            "cancel_date": False,
            "cancel_reason": False,
        })
        self.message_post(body=_("Loan set back to draft."))

    def action_approve_wizard(self):
        self.ensure_one()
        if self.state != "draft":
            raise UserError(_("Only draft loans can be approved."))
        self._require_schedule()
        return {
            "type": "ir.actions.act_window",
            "name": _("Approve Staff Loan"),
            "res_model": "staff.loan.approve.wizard",
            "target": "new",
            "views": [(False, "form")],
            "context": {"default_loan_id": self.id},
        }

    def action_disburse_wizard(self):
        self.ensure_one()
        if self.state != "approved":
            raise UserError(_("Approve the loan before disbursement."))
        self._require_accounting_settings()
        if self.disbursement_move_id:
            raise UserError(_("This loan is already disbursed."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Disburse Staff Loan"),
            "res_model": "staff.loan.disburse.wizard",
            "target": "new",
            "views": [(False, "form")],
            "context": {"default_loan_id": self.id},
        }

    def action_full_settlement_wizard(self):
        self.ensure_one()
        if self.state not in ("running", "disbursed"):
            raise UserError(_("Full settlement is allowed only after disbursement."))
        if self.exception_update_pending:
            raise UserError(_("Update the repayment schedule for the latest exception before full settlement."))
        if float_is_zero(self.outstanding_balance, precision_rounding=self.currency_id.rounding):
            raise UserError(_("There is no outstanding balance to settle."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Full Settlement"),
            "res_model": "staff.loan.full.settlement.wizard",
            "target": "new",
            "views": [(False, "form")],
            "context": {"default_loan_id": self.id},
        }

    def action_close_wizard(self):
        self.ensure_one()
        if self.state != "running":
            raise UserError(_("Only running loans can be closed."))
        if self.exception_update_pending:
            raise UserError(_("Update the repayment schedule for the latest exception before closing the loan."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Close Staff Loan"),
            "res_model": "staff.loan.close.wizard",
            "target": "new",
            "views": [(False, "form")],
            "context": {"default_loan_id": self.id},
        }

    def action_cancel(self):
        self.ensure_one()
        if self.state != "running":
            raise UserError(_("Only running loans can be cancelled from this action."))
        return self.action_cancel_wizard()

    def action_cancel_wizard(self):
        self.ensure_one()
        if self.state not in ("draft", "approved", "running"):
            raise UserError(_("Only Draft, Approved, or Running loans can be cancelled."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Cancel Staff Loan"),
            "res_model": "staff.loan.cancel.wizard",
            "target": "new",
            "views": [(False, "form")],
            "context": {"default_loan_id": self.id},
        }

    def action_open_entries(self):
        self.ensure_one()
        moves = self._get_entry_moves()
        return {
            "type": "ir.actions.act_window",
            "name": _("Staff Loan Entries"),
            "res_model": "account.move",
            "view_mode": "list,form",
            "views": [
                (self.env.ref("tha_staff_loan.view_staff_loan_account_move_list").id, "list"),
                (False, "form"),
            ],
            "domain": [("id", "in", moves.ids)],
            "context": {"default_staff_loan_id": self.id},
        }

    def action_open_documents(self):
        self.ensure_one()
        action = self.env.ref("tha_staff_loan.action_staff_loan_attachment").read()[0]
        kanban_view = self.env.ref("tha_staff_loan.view_staff_loan_attachment_kanban")
        list_view = self.env.ref("tha_staff_loan.view_staff_loan_attachment_list")
        form_view = self.env.ref("tha_staff_loan.view_staff_loan_attachment_form")
        action["domain"] = [("res_model", "=", self._name), ("res_id", "=", self.id)]
        action["views"] = [
            (kanban_view.id, "kanban"),
            (list_view.id, "list"),
            (form_view.id, "form"),
        ]
        action["view_mode"] = "kanban,list,form"
        action["help"] = False
        action["context"] = {
            "create": True,
            "default_res_model": self._name,
            "default_res_id": self.id,
            "default_company_id": self.company_id.id,
            "default_type": "binary",
            "form_view_ref": "tha_staff_loan.view_staff_loan_attachment_form",
            "active_model": self._name,
            "active_id": self.id,
        }
        return action

    @api.model
    def create_document_from_attachment(self, attachment_ids):
        loan_id = self.env.context.get("default_loan_id")
        if not loan_id and self.env.context.get("active_model") == "staff.loan":
            loan_id = self.env.context.get("active_id")
        loan = self.browse(loan_id)
        attachments = self.env["ir.attachment"].browse(attachment_ids)
        if not loan:
            raise UserError(_("The upload must be started from a staff loan."))
        if not attachments:
            raise UserError(_("No attachment was provided."))
        attachments.write({
            "res_model": loan._name,
            "res_id": loan.id,
            "company_id": loan.company_id.id,
        })
        loan.message_post(body=_("%s document(s) uploaded.", len(attachments)))
        return loan.action_open_documents()

    def action_upload_document(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Upload Document"),
            "res_model": "staff.loan.document.wizard",
            "target": "new",
            "views": [(False, "form")],
            "context": {"default_loan_id": self.id},
        }

    def action_open_outstanding_lines(self):
        self.ensure_one()
        moves = self.collection_move_ids.filtered(lambda move: move.state == "posted")
        return {
            "type": "ir.actions.act_window",
            "name": _("Outstanding Balance"),
            "res_model": "account.move",
            "view_mode": "list,form",
            "views": [
                (self.env.ref("tha_staff_loan.view_staff_loan_outstanding_move_list").id, "list"),
                (False, "form"),
            ],
            "domain": [("id", "in", moves.ids)],
            "context": {"default_staff_loan_id": self.id, "create": False},
        }

    def _make_move_line_vals(self, account, debit=0.0, credit=0.0, name=False, partner=False):
        return Command.create({
            "name": name or self.name,
            "account_id": account.id,
            "debit": debit,
            "credit": credit,
            "partner_id": partner.id if partner else False,
        })

    def _post_disbursement_move(self, date, journal, reference, remarks):
        self.ensure_one()
        self._require_accounting_settings()
        self._require_schedule()
        partner = self.employee_id.work_contact_id or self.employee_id.user_id.partner_id
        receivable_amount = self.total_payment
        line_vals = [
            self._make_move_line_vals(
                self.receivable_account_id,
                debit=receivable_amount,
                name=_("%s - Staff Loan Disbursement") % self.name,
                partner=partner,
            ),
            self._make_move_line_vals(
                self.disbursement_account_id,
                credit=self.loan_amount,
                name=_("%s - Paid to Staff") % self.name,
                partner=partner,
            ),
        ]
        if not float_is_zero(self.total_interest, precision_rounding=self.currency_id.rounding):
            line_vals.append(
                self._make_move_line_vals(
                    self.deferred_account_id,
                    credit=self.total_interest,
                    name=_("%s - Deferred Interest") % self.name,
                    partner=partner,
                )
            )
        move = self.env["account.move"].with_company(self.company_id).create({
            "company_id": self.company_id.id,
            "date": date,
            "journal_id": journal.id,
            "ref": reference or self.name,
            "staff_loan_id": self.id,
            "is_staff_loan_disbursement": True,
            "line_ids": line_vals,
        })
        move.action_post()
        self._create_interest_recognition_moves()
        self.write({
            "disbursement_move_id": move.id,
            "disbursement_date": date,
            "state": "running",
        })
        self.message_post(body=_("Loan disbursed on %(date)s. %(remarks)s", date=date, remarks=remarks or ""))
        return move

    def _get_collectible_lines(self):
        self.ensure_one()
        return self.line_ids.filtered(lambda line: line.state == "unpaid").sorted("due_date")

    def _get_settlement_lines(self):
        self.ensure_one()
        return self.line_ids.filtered(
            lambda line: line.state == "unpaid"
            or (
                line.state == "exception"
                and not line.exception_schedule_updated
                and not float_is_zero(line.open_amount, precision_rounding=line.currency_id.rounding)
            )
        ).sorted("due_date")

    def _get_tracked_receivable_amount(self):
        self.ensure_one()
        return sum(self.line_ids.mapped("payment")) + sum(
            line._get_exception_remaining_principal_value()
            for line in self.line_ids.filtered(lambda line: line.is_exception and not line.exception_schedule_updated)
        )

    def _get_remaining_deferred_interest(self):
        self.ensure_one()
        remaining_interest = 0.0
        for line in self._get_settlement_lines():
            effective_moves = line.generated_move_ids.filtered(lambda move: move.state == "posted" and not move.reversal_move_ids)
            if not effective_moves:
                remaining_interest += line.interest
        return self.currency_id.round(remaining_interest)

    def _create_interest_recognition_moves(self):
        for loan in self:
            loan._require_accounting_settings()
            for line in loan.line_ids:
                if line.generated_move_ids.filtered(lambda move: move.state != "cancel"):
                    raise UserError(_("Generated entries already exist for installment due on %(date)s.", date=line.due_date))
            for line in loan.line_ids:
                move = line._create_interest_recognition_move(
                    line.due_date + relativedelta(day=31),
                    loan._get_loan_journal(),
                    loan.reference or loan.name,
                )
                if move and move.date <= fields.Date.context_today(self):
                    move.action_post()

    def _round_schedule_values(self, values, principal_amount, total_interest):
        self.ensure_one()
        if not values:
            return values
        principal_diff = self.currency_id.round(principal_amount - sum(item["principal"] for item in values))
        interest_diff = self.currency_id.round(total_interest - sum(item["interest"] for item in values))
        values[-1]["principal"] = self.currency_id.round(values[-1]["principal"] + principal_diff)
        values[-1]["interest"] = self.currency_id.round(values[-1]["interest"] + interest_diff)
        values[-1]["payment"] = self.currency_id.round(values[-1]["principal"] + values[-1]["interest"])
        values[-1]["balance"] = 0.0
        return values

    def _get_schedule_values_for_amount(self, principal_amount, due_dates):
        self.ensure_one()
        duration = len(due_dates)
        if duration <= 0:
            return []
        if self.interest_type == "emi":
            monthly_rate = self.interest_rate / 12.0 / 100.0
            balance = principal_amount
            if float_is_zero(monthly_rate, precision_digits=12):
                emi_amount = principal_amount / duration
            else:
                factor = (1 + monthly_rate) ** duration
                emi_amount = (principal_amount * monthly_rate * factor) / (factor - 1)
            values = []
            for index, due_date in enumerate(due_dates):
                interest = balance * monthly_rate
                principal = emi_amount - interest
                if index == duration - 1:
                    principal = balance
                    interest = emi_amount - principal if not float_is_zero(monthly_rate, precision_digits=12) else 0.0
                balance -= principal
                values.append({
                    "due_date": due_date,
                    "principal": self.currency_id.round(principal),
                    "interest": self.currency_id.round(interest),
                    "payment": self.currency_id.round(principal + interest),
                    "balance": self.currency_id.round(max(balance, 0.0)),
                })
            total_interest = sum(item["interest"] for item in values)
            return self._round_schedule_values(values, principal_amount, total_interest)

        total_interest = principal_amount * self.interest_rate / 100.0
        principal_per_line = principal_amount / duration
        interest_per_line = total_interest / duration
        balance = principal_amount
        values = []
        for index, due_date in enumerate(due_dates):
            principal = principal_per_line
            if index == duration - 1:
                principal = balance
            balance -= principal
            values.append({
                "due_date": due_date,
                "principal": self.currency_id.round(principal),
                "interest": self.currency_id.round(interest_per_line),
                "payment": self.currency_id.round(principal + interest_per_line),
                "balance": self.currency_id.round(max(balance, 0.0)),
            })
        return self._round_schedule_values(values, principal_amount, total_interest)

    def _get_exception_anchor_line(self):
        self.ensure_one()
        exception_lines = self.line_ids.filtered(
            lambda line: line.is_exception
            and not line.exception_schedule_updated
            and not float_is_zero(line._get_exception_remaining_principal_value(), precision_rounding=line.currency_id.rounding)
        )
        for line in sorted(exception_lines, key=lambda item: (item.due_date, item.id), reverse=True):
            if self.line_ids.filtered(lambda item: item.state == "unpaid" and item.due_date > line.due_date):
                return line
        return self.env["staff.loan.line"]

    def action_update_exception_schedule(self):
        self.ensure_one()
        if self.state not in ("running", "disbursed"):
            raise UserError(_("Schedule updates are allowed only after disbursement."))
        anchor_line = self._get_exception_anchor_line()
        if not anchor_line:
            raise UserError(_("There is no exception line waiting for a future schedule update."))
        future_lines = self.line_ids.filtered(lambda line: line.state == "unpaid" and line.due_date > anchor_line.due_date).sorted("due_date")
        if not future_lines:
            raise UserError(_("There are no future unpaid installments to update."))
        anchor_line._normalize_exception_values()
        posted_future_moves = future_lines.generated_move_ids.filtered(lambda move: move.state == "posted" and not move.reversal_move_ids)
        if posted_future_moves:
            raise UserError(_("Future posted interest recognition entries must be adjusted manually before updating the schedule."))
        principal_amount = anchor_line.exception_remaining_principal + sum(future_lines.mapped("principal"))
        schedule_values = self._get_schedule_values_for_amount(principal_amount, future_lines.mapped("due_date"))
        future_lines.generated_move_ids.filtered(lambda move: move.state != "posted").unlink()
        for line, values in zip(future_lines, schedule_values):
            line.write({
                "principal": values["principal"],
                "interest": values["interest"],
                "balance": values["balance"],
            })
        anchor_line.write({"exception_schedule_updated": True})
        anchor_line._sync_exception_balance()
        for line in future_lines:
            move = line._create_interest_recognition_move(
                line.due_date + relativedelta(day=31),
                self._get_loan_journal(),
                self.reference or self.name,
            )
            if move and move.date <= fields.Date.context_today(self):
                move.action_post()
        self.message_post(body=_(
            "Future repayment schedule updated from exception on %(date)s. Remaining loan principal %(amount)s redistributed across %(count)s installment(s).",
            date=anchor_line.due_date,
            amount=self.currency_id.format(principal_amount),
            count=len(future_lines),
        ))
        self.invalidate_recordset()
        return {
            "type": "ir.actions.act_window",
            "name": _("Staff Loan"),
            "res_model": "staff.loan",
            "res_id": self.id,
            "view_mode": "form",
            "views": [(False, "form")],
            "target": "current",
        }

    def action_register_collection(self):
        self.ensure_one()
        if self.state not in ("running", "disbursed"):
            raise UserError(_("Collections are allowed only after disbursement."))
        line = self._get_collectible_lines()[:1]
        if not line:
            raise UserError(_("There is no unpaid installment to collect."))
        return line.action_collect_wizard()

    def _refresh_state_after_collection(self):
        for loan in self:
            if loan.state in ("running", "disbursed") and loan.line_ids and all(line.state != "unpaid" for line in loan.line_ids):
                loan.state = "running"

    def _create_full_settlement_collection_move(self, date, journal, amount, reference, remarks):
        self.ensure_one()
        partner = self.employee_id.work_contact_id or self.employee_id.user_id.partner_id
        if float_is_zero(amount, precision_rounding=self.currency_id.rounding):
            return self.env["account.move"]
        move = self.env["account.move"].with_company(self.company_id).create({
            "company_id": self.company_id.id,
            "date": date,
            "journal_id": journal.id,
            "ref": _("%(loan)s - Full Settlement", loan=reference or self.name),
            "staff_loan_id": self.id,
            "is_staff_loan_collection": True,
            "is_staff_loan_full_settlement": True,
            "line_ids": [
                self._make_move_line_vals(
                    self.collection_account_id,
                    debit=amount,
                    name=_("%s - Full Settlement") % self.name,
                    partner=partner,
                ),
                self._make_move_line_vals(
                    self.receivable_account_id,
                    credit=amount,
                    name=_("%s - Receivable Settlement") % self.name,
                    partner=partner,
                ),
            ],
        })
        move.action_post()
        self.message_post(body=_("Full settlement posted on %(date)s. %(remarks)s", date=date, remarks=remarks or ""))
        return move

    def _create_full_settlement_recognition_move(self, date, journal, amount, reference):
        self.ensure_one()
        partner = self.employee_id.work_contact_id or self.employee_id.user_id.partner_id
        if float_is_zero(amount, precision_rounding=self.currency_id.rounding):
            return self.env["account.move"]
        move = self.env["account.move"].with_company(self.company_id).create({
            "company_id": self.company_id.id,
            "date": date,
            "journal_id": journal.id,
            "ref": _("%(loan)s - Final Interest Recognition", loan=reference or self.name),
            "staff_loan_id": self.id,
            "is_staff_loan_repayment_move": True,
            "is_staff_loan_settlement_recognition": True,
            "line_ids": [
                self._make_move_line_vals(
                    self.deferred_account_id,
                    debit=amount,
                    name=_("%s - Final Deferred Interest") % self.name,
                    partner=partner,
                ),
                self._make_move_line_vals(
                    self.interest_income_account_id,
                    credit=amount,
                    name=_("%s - Final Interest Income") % self.name,
                    partner=partner,
                ),
            ],
        })
        move.action_post()
        return move

    def _post_full_settlement(self, date, journal, reference, remarks):
        self.ensure_one()
        self._require_accounting_settings()
        if self.state not in ("running", "disbursed"):
            raise UserError(_("Full settlement is allowed only after disbursement."))
        settlement_lines = self._get_settlement_lines()
        if not settlement_lines:
            raise UserError(_("There are no unpaid installments to settle."))
        settlement_amount = self.currency_id.round(sum(settlement_lines.mapped("open_amount")))
        remaining_deferred_interest = self._get_remaining_deferred_interest()
        settlement_move = self._create_full_settlement_collection_move(date, journal, settlement_amount, reference, remarks)
        recognition_move = self._create_full_settlement_recognition_move(date, journal, remaining_deferred_interest, reference)
        settlement_lines.write({"settlement_move_id": settlement_move.id})
        settlement_lines.generated_move_ids.filtered(lambda move: move.state != "posted").unlink()
        self.write({
            "state": "closed",
            "close_date": date,
            "close_remarks": remarks,
        })
        self.message_post(body=_(
            "Loan fully settled on %(date)s. Settlement %(amount)s. Remaining deferred interest %(interest)s recognized.",
            date=date,
            amount=self.currency_id.format(settlement_amount),
            interest=self.currency_id.format(remaining_deferred_interest),
        ))
        self.invalidate_recordset()
        return settlement_move | recognition_move


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
            ("unpaid", "Unpaid"),
            ("paid", "Paid"),
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
