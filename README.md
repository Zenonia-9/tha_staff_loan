# Staff Loan Management

![Odoo 19](https://img.shields.io/badge/Odoo-19.0-875A7B?style=flat-square)
![License](https://img.shields.io/badge/License-LGPL--3-blue?style=flat-square)
![Category](https://img.shields.io/badge/Category-Accounting-4ECDC4?style=flat-square)

Native-style staff loan workflow for Odoo 19 Accounting with repayment schedules, journal entries, collections, and linked documents.

This module adds a staff loan flow inside Accounting so users can create and approve loans, compute repayment schedules, post disbursements, track repayment journal entries, register collections, and manage supporting documents from the loan record.

## Highlights

- Adds a dedicated **Staff Loans** flow in Accounting.
- Supports **draft, approved, disbursed, running, closed, and cancelled** loan states.
- Computes a **flat-rate repayment schedule** with installment lines and outstanding balances.
- Creates a **posted disbursement entry** and **draft repayment schedule entries**.
- Registers installment collections against the **repayment schedule line**.
- Keeps a linked **document workspace** with kanban, list, custom form, and PDF preview.
- Includes **loan agreement, schedule, statement, outstanding, collection, and closure** reports.

## Workflow

1. Create a staff loan in Draft.
2. Compute the repayment schedule.
3. Approve the loan.
4. Disburse the loan and post the disbursement entry.
5. Review the generated repayment schedule journal entries.
6. Register installment collections from the repayment schedule.
7. Close the loan after the outstanding balance reaches zero.

## Technical Notes

- `models/staff_loan.py`
  Holds the main `staff.loan` business flow, state actions, entry actions, and document workspace action.
- `models/staff_loan_line.py`
  Holds repayment schedule line logic, paid/open amount computation, and collection posting behavior.
- `models/account_move.py`
  Extends journal entries with staff loan links, settlement totals, running outstanding balance, and the related smart button.
- `models/ir_attachment.py`
  Adds staff-loan-specific attachment helpers including PDF preview support.
- `wizard/staff_loan_compute_wizard.py`
  Builds the repayment schedule preview and writes the schedule lines.
- `wizard/staff_loan_lifecycle_wizards.py`
  Handles approval, closing, and cancellation dialogs.
- `wizard/staff_loan_transaction_wizards.py`
  Handles disbursement and collection dialogs.
- `views/staff_loan_views.xml`
  Contains the main loan views, actions, and menu structure.
- `views/staff_loan_document_views.xml`
  Contains the document workspace views and action for loan attachments.

## Module Layout

```text
tha_staff_loan/
|-- models/
|-- wizard/
|-- views/
|-- report/
|-- security/
|-- data/
|-- static/
|-- __init__.py
|-- __manifest__.py
`-- README.md
```

## Dependencies

- `account`
- `accountant`
- `hr`
- `mail`

## Installation

1. Place the module in your custom addons path.
2. Restart Odoo and update the Apps list.
3. Install **Staff Loan Management**.

## License

This module is licensed under `LGPL-3`.
