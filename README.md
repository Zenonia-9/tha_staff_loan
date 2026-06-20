# Staff Loan Management

`tha_staff_loan` manages staff loans in Odoo Accounting with approval, flat-rate repayment schedules, disbursement entries, manual collections, documents, notes, and reports.

## Main Flow

1. Create a staff loan in Draft.
2. Compute the repayment schedule.
3. Approve the loan.
4. Disburse the loan and post the accounting entry.
5. Register installment collections.
6. Close the loan after all principal and interest are settled.

## Accounting

Disbursement:

```text
Dr Staff Loan Receivable
    Cr Cash / Bank
```

Collection:

```text
Dr Cash / Bank
    Cr Staff Loan Receivable
    Cr Staff Loan Interest Income
```

## Scope

This beta version supports manual collection only. Payroll deduction integration is intentionally left for a later extension.
