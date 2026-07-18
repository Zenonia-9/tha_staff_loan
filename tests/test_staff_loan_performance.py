from odoo import Command, fields
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestStaffLoanPerformance(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.employee = cls.env["hr.employee"].create({
            "name": "Batch Compute Employee",
            "company_id": cls.company.id,
        })
        cls.journal = cls.env["account.journal"].search([
            ("company_id", "=", cls.company.id),
            ("type", "=", "general"),
        ], limit=1)
        cls.accounts = cls.env["account.account"].search([
            ("company_ids", "in", cls.company.id),
        ], limit=2)
        if len(cls.accounts) < 2:
            cls.accounts = cls.env["account.account"].create([
                {
                    "name": "Staff Loan Batch Debit",
                    "code": "SLBATCHD",
                    "account_type": "asset_current",
                    "company_ids": [Command.set(cls.company.ids)],
                },
                {
                    "name": "Staff Loan Batch Credit",
                    "code": "SLBATCHC",
                    "account_type": "liability_current",
                    "company_ids": [Command.set(cls.company.ids)],
                },
            ])

    def _create_loan(self, name):
        return self.env["staff.loan"].create({
            "name": name,
            "employee_id": self.employee.id,
            "company_id": self.company.id,
            "loan_amount": 1000.0,
            "loan_date": fields.Date.today(),
            "duration": 1,
        })

    def _create_move(self, loan, *, collection=False, posted=False):
        move = self.env["account.move"].create({
            "move_type": "entry",
            "date": fields.Date.today(),
            "journal_id": self.journal.id,
            "staff_loan_id": loan.id,
            "is_staff_loan_collection": collection,
            "line_ids": [
                Command.create({"account_id": self.accounts[0].id, "debit": 100.0}),
                Command.create({"account_id": self.accounts[1].id, "credit": 100.0}),
            ],
        })
        if posted:
            move.action_post()
        return move

    def test_collection_moves_and_posted_counts_are_batched(self):
        loan_with_moves = self._create_loan("SL/BATCH/1")
        loan_without_moves = self._create_loan("SL/BATCH/2")
        posted_collection = self._create_move(loan_with_moves, collection=True, posted=True)
        draft_collection = self._create_move(loan_with_moves, collection=True)
        self._create_move(loan_with_moves, collection=False)

        loans = loan_with_moves | loan_without_moves
        loans.mapped("collection_move_ids")
        loans._compute_counts()

        self.assertEqual(
            set(loan_with_moves.collection_move_ids.ids),
            {posted_collection.id, draft_collection.id},
        )
        self.assertFalse(loan_without_moves.collection_move_ids)
        self.assertEqual(loan_with_moves.posted_entry_count, 1)
        self.assertEqual(loan_without_moves.posted_entry_count, 0)

    def test_query_count_does_not_scale_per_loan(self):
        loans = self.env["staff.loan"]
        for index in range(10):
            loan = self._create_loan("SL/QUERY/%s" % index)
            loans |= loan

        self.env.invalidate_all()
        start = self.env.cr.sql_log_count
        loans.mapped("collection_move_ids")
        batch_query_count = self.env.cr.sql_log_count - start

        self.env.invalidate_all()
        start = self.env.cr.sql_log_count
        loans[:1].mapped("collection_move_ids")
        single_query_count = self.env.cr.sql_log_count - start

        self.assertLessEqual(batch_query_count, single_query_count + 2)
