# Staff Loan Management

`tha_staff_loan` manages staff loans in Odoo Accounting with approval, repayment schedules, disbursement entries, installment collections, linked documents, notes, and reports.

## Main Flow

1. Create a staff loan in Draft.
2. Compute the repayment schedule.
3. Approve the loan.
4. Disburse the loan and post the disbursement entry.
5. Generate and track repayment schedule journal entries.
6. Register installment collections against the repayment schedule.
7. Close the loan after all principal and interest are settled.

## Accounting

Disbursement:

```text
Dr Staff Loan Receivable
    Cr Cash / Bank
```

Repayment schedule / collection entries:

```text
Dr Collection / Clearing Account
    Cr Staff Loan Receivable
    Cr Staff Loan Interest Income
```

## Scope

- Native-style repayment schedule lines with linked journal entries
- Manual collection workflow from repayment schedule lines
- Document workspace with kanban, list, custom form, and PDF preview
- Close and cancel controls aligned with the current staff-loan lifecycle

## Out of Scope

- Payroll deduction integration
- Automatic payment integration through `account.payment`
