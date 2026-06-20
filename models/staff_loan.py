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
    first_payment_date = fields.Date(required=True, tracking=True)
    duration = fields.Integer(string="Duration", required=True, default=12, tracking=True)
    payment_frequency = fields.Selection(
        [("monthly", "Monthly")],
        default="monthly",
        required=True,
        tracking=True,
    )
    interest_type = fields.Selection(
        [("flat", "Flat Rate")],
        default="flat",
        required=True,
        tracking=True,
    )
    interest_rate = fields.Float(string="Interest Rate (%)", default=2.0, tracking=True)
    payment_method = fields.Selection(
        [("cash", "Cash"), ("bank", "Bank"), ("other", "Other")],
        string="Payment Method",
        default="cash",
        required=True,
        tracking=True,
    )
    disbursement_date = fields.Date(tracking=True)
    reference = fields.Char(string="Loan Reference", tracking=True)
    notes = fields.Html()

    receivable_account_id = fields.Many2one(
        "account.account",
        string="Staff Loan Receivable Account",
        tracking=True,
        domain="[('account_type', 'in', ('asset_current', 'asset_receivable')), ('company_ids', 'in', company_id)]",
    )
    interest_income_account_id = fields.Many2one(
        "account.account",
        string="Interest Income Account",
        tracking=True,
        domain="[('account_type', 'in', ('income', 'income_other')), ('company_ids', 'in', company_id)]",
    )
    disbursement_journal_id = fields.Many2one(
        "account.journal",
        string="Disbursement Journal",
        tracking=True,
        domain="[('type', 'in', ('cash', 'bank', 'general')), ('company_id', '=', company_id)]",
    )
    collection_journal_id = fields.Many2one(
        "account.journal",
        string="Collection Journal",
        tracking=True,
        domain="[('type', 'in', ('cash', 'bank', 'general')), ('company_id', '=', company_id)]",
    )
    disbursement_account_id = fields.Many2one(
        "account.account",
        string="Disbursement Credit Account",
        tracking=True,
        domain="[('company_ids', 'in', company_id)]",
        help="Credit account used when posting the staff loan disbursement. This keeps the journal independent from a default account.",
    )
    collection_account_id = fields.Many2one(
        "account.account",
        string="Collection Debit Account",
        tracking=True,
        domain="[('company_ids', 'in', company_id)]",
        help="Debit account used by generated staff loan repayment entries. This keeps the collection journal independent from a default account.",
    )
    writeoff_account_id = fields.Many2one(
        "account.account",
        string="Write-Off Account",
        tracking=True,
        domain="[('account_type', 'in', ('expense', 'expense_other')), ('company_ids', 'in', company_id)]",
    )

    line_ids = fields.One2many("staff.loan.line", "loan_id", string="Repayment Schedule", copy=True)
    disbursement_move_id = fields.Many2one(
        "account.move",
        string="Disbursement Entry",
        readonly=True,
        copy=False,
    )
    collection_move_ids = fields.Many2many(
        "account.move",
        string="Collection Entries",
        compute="_compute_collection_move_ids",
    )

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
            "collection_journal_id",
            "disbursement_account_id",
            "collection_account_id",
            "writeoff_account_id",
        }
        if not accounting_fields.intersection(fields_list):
            return values
        previous_loan = self.search([
            ("company_id", "=", self.env.company.id),
            ("receivable_account_id", "!=", False),
            ("interest_income_account_id", "!=", False),
            ("disbursement_journal_id", "!=", False),
            ("collection_journal_id", "!=", False),
            ("disbursement_account_id", "!=", False),
            ("collection_account_id", "!=", False),
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

    @api.depends("line_ids.interest", "line_ids.payment", "line_ids.paid_principal", "line_ids.paid_interest")
    def _compute_totals(self):
        for loan in self:
            loan.total_interest = sum(loan.line_ids.mapped("interest"))
            loan.total_payment = sum(loan.line_ids.mapped("payment"))
            loan.paid_principal = sum(loan.line_ids.mapped("paid_principal"))
            loan.paid_interest = sum(loan.line_ids.mapped("paid_interest"))
            loan.paid_amount = loan.paid_principal + loan.paid_interest
            loan.outstanding_principal = max(loan.loan_amount - loan.paid_principal, 0.0)
            loan.outstanding_interest = max(loan.total_interest - loan.paid_interest, 0.0)
            loan.outstanding_balance = loan.outstanding_principal + loan.outstanding_interest

    @api.depends("line_ids.collection_move_ids")
    def _compute_collection_move_ids(self):
        for loan in self:
            loan.collection_move_ids = loan.line_ids.collection_move_ids

    def _get_entry_moves(self):
        self.ensure_one()
        return self.disbursement_move_id | self.line_ids.generated_move_ids | self.line_ids.collection_move_ids

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
            loan.remaining_installment_count = len(loan.line_ids.filtered(lambda line: line.state != "paid"))
            moves = loan._get_entry_moves()
            loan.posted_entry_count = len(moves.filtered(lambda move: move.state == "posted"))
            loan.document_count = loan.message_attachment_count

    def _check_company_consistency(self):
        for loan in self:
            company = loan.company_id
            accounts = (
                loan.receivable_account_id
                | loan.interest_income_account_id
                | loan.disbursement_account_id
                | loan.collection_account_id
                | loan.writeoff_account_id
            )
            for account in accounts:
                if account and company not in account.company_ids:
                    raise UserError(_("Account %(account)s is not available for %(company)s.", account=account.display_name, company=company.display_name))
            for journal in loan.disbursement_journal_id | loan.collection_journal_id:
                if journal and journal.company_id != company:
                    raise UserError(_("Journal %(journal)s does not belong to %(company)s.", journal=journal.display_name, company=company.display_name))

    def _require_schedule(self):
        for loan in self:
            if not loan.line_ids:
                raise UserError(_("Compute the repayment schedule first."))
            principal = loan.currency_id.round(sum(loan.line_ids.mapped("principal")))
            if float_compare(principal, loan.loan_amount, precision_rounding=loan.currency_id.rounding) != 0:
                raise UserError(_("The schedule principal total must equal the loan amount."))

    def _require_accounting_settings(self):
        for loan in self:
            if not loan.receivable_account_id:
                raise UserError(_("Set the Staff Loan Receivable Account."))
            if not loan.interest_income_account_id:
                raise UserError(_("Set the Interest Income Account."))
            if not loan.disbursement_journal_id:
                raise UserError(_("Set the Disbursement Journal."))
            if not loan.collection_journal_id:
                raise UserError(_("Set the Collection Journal."))
            if not loan.disbursement_account_id:
                raise UserError(_("Set the Disbursement Credit Account."))
            if not loan.collection_account_id:
                raise UserError(_("Set the Collection Debit Account."))
        self._check_company_consistency()

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

    def action_close_wizard(self):
        self.ensure_one()
        if self.state != "running":
            raise UserError(_("Only running loans can be closed."))
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
            raise UserError(_("Only running loans can be cancelled directly."))
        (
            self.disbursement_move_id
            | self.line_ids.generated_move_ids
            | self.line_ids.collection_move_ids
        ).filtered(lambda move: move.state != "cancel")._unlink_or_reverse()
        self.state = "cancelled"
        self.message_post(body=_("Loan cancelled."))

    def action_cancel_wizard(self):
        self.ensure_one()
        if self.state not in ("draft", "approved"):
            raise UserError(_("Only Draft or Approved loans can be cancelled directly."))
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
        return {
            "type": "ir.actions.act_window",
            "name": _("Documents"),
            "res_model": "ir.attachment",
            "view_mode": "kanban,list,form",
            "domain": [("res_model", "=", self._name), ("res_id", "=", self.id)],
            "context": {"default_res_model": self._name, "default_res_id": self.id},
        }

    def action_open_outstanding_lines(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Outstanding Installments"),
            "res_model": "staff.loan.line",
            "view_mode": "list,form",
            "domain": [("loan_id", "=", self.id), ("state", "in", ("open", "partial", "overdue"))],
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
        move = self.env["account.move"].with_company(self.company_id).create({
            "company_id": self.company_id.id,
            "date": date,
            "journal_id": journal.id,
            "ref": reference or self.name,
            "staff_loan_id": self.id,
            "is_staff_loan_disbursement": True,
            "line_ids": [
                self._make_move_line_vals(
                    self.receivable_account_id,
                    debit=self.loan_amount,
                    name=_("%s - Staff Loan Disbursement") % self.name,
                    partner=partner,
                ),
                self._make_move_line_vals(
                    self.disbursement_account_id,
                    credit=self.loan_amount,
                    name=_("%s - Paid to Staff") % self.name,
                    partner=partner,
                ),
            ],
        })
        move.action_post()
        self._create_repayment_schedule_moves()
        self.write({
            "disbursement_move_id": move.id,
            "disbursement_date": date,
            "state": "running",
        })
        self.message_post(body=_("Loan disbursed on %(date)s. %(remarks)s", date=date, remarks=remarks or ""))
        return move

    def _create_repayment_schedule_moves(self):
        for loan in self:
            loan._require_accounting_settings()
            for line in loan.line_ids:
                if line.generated_move_ids.filtered(lambda move: move.state != "cancel"):
                    raise UserError(_("Repayment entries already exist for installment due on %(date)s.", date=line.due_date))
            for line in loan.line_ids:
                line._create_repayment_move(
                    line.due_date + relativedelta(day=31),
                    loan.collection_journal_id,
                    line.principal,
                    line.interest,
                    loan.reference or loan.name,
                )

    def action_register_collection(self):
        self.ensure_one()
        if self.state not in ("running", "disbursed"):
            raise UserError(_("Collections are allowed only after disbursement."))
        line = self.line_ids.filtered(lambda item: item.state in ("overdue", "partial", "open"))[:1]
        if not line:
            raise UserError(_("There is no open installment to collect."))
        return line.action_collect_wizard()

    def _refresh_state_after_collection(self):
        for loan in self:
            if loan.state in ("running", "disbursed") and loan.line_ids and all(line.state == "paid" for line in loan.line_ids):
                loan.state = "running"


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
            self._create_repayment_move(
                self.due_date + relativedelta(day=31),
                loan.collection_journal_id,
                remaining_principal,
                remaining_interest,
                loan.reference or loan.name,
            )
        loan.invalidate_recordset()
        loan.message_post(body=_(
            "Collected %(amount)s for installment due on %(date)s. %(remarks)s",
            amount=loan.currency_id.format(amount),
            date=self.due_date,
            remarks=remarks or "",
        ))
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
            lines.append(loan._make_move_line_vals(
                loan.receivable_account_id,
                credit=principal_amount,
                name=_("%s - Principal %s") % (loan.name, date_label),
                partner=partner,
            ))
        if interest_amount:
            lines.append(loan._make_move_line_vals(
                loan.interest_income_account_id,
                credit=interest_amount,
                name=_("%s - Interest %s") % (loan.name, date_label),
                partner=partner,
            ))
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
