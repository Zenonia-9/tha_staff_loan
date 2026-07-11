# Staff Loan Management

![Odoo 19](https://img.shields.io/badge/Odoo-19.0-875A7B?style=flat-square)
![License](https://img.shields.io/badge/License-LGPL--3-blue?style=flat-square)
![Category](https://img.shields.io/badge/Category-Accounting-4ECDC4?style=flat-square)

Staff loan workflow for Odoo 19 Accounting with flat-rate or EMI schedules, disbursement accounting, interest recognition, line-level collections, full settlement, exception handling, and linked loan documents.

## Highlights

- Adds a dedicated **Staff Loans** flow inside Accounting.
- Supports **draft, approved, disbursed, running, closed, and cancelled** loan states.
- Computes repayment schedules using **Flat Rate** or **EMI**.
- Supports repayment anchors of **Start of Month** or **End of Month**.
- Uses **Loan Date end of month** as the default first payment month.
- Supports **Skip Until** to postpone the first repayment month.
- Uses one shared **Journal** plus these loan accounts:
  - **Receivable Account**
  - **Income Account**
  - **Disbursement Account**
  - **Collection Account**
  - **Deferred Account**
- Posts a disbursement entry and creates repayment/recognition journal entries linked to the loan and schedule lines.
- Collects normal repayments from the **repayment line Collect action**.
- Supports **Full Settlement** for closing the full remaining receivable and deferred interest.
- Supports **Manual Exception** for partial-payment months, then **Update Schedule** to recalculate future unpaid installments.
- Keeps a linked document workspace and printable loan reports.

## Workflow

1. Create a staff loan in Draft.
2. Enter loan terms and configure **Loan Settings**.
3. Compute the repayment schedule.
4. Approve the loan.
5. Disburse the loan to post the disbursement journal entry.
6. Run the loan using one of these repayment paths:
   - collect the full scheduled amount from a repayment line
   - post a manual exception for a partial-payment month
   - run full settlement for the remaining balance
7. If an exception was posted, use **Update Schedule** to rewrite future unpaid schedule lines and future draft recognition entries.
8. Close the loan when the outstanding balance reaches zero.

## Loan Settings

The loan form includes a **Loan Settings** tab for accounting and schedule control:

- **Interest Type**: `Flat Rate` or `EMI`
- **Payment Anchor**: `Start of Month` or `End of Month`
- **Skip Until**: optional date to postpone the first repayment month
- **Journal**: single journal used for disbursement, collection, settlement, and recognition flows
- **Receivable Account**
- **Income Account**
- **Disbursement Account**
- **Collection Account**
- **Deferred Account**

Example:

- Loan Date: `2025-12-12`
- Payment Anchor: `End of Month`
- First payment date defaults to `2025-12-31`
- If `Skip Until = 2026-02-05`, first payment date becomes `2026-02-28`

## Collection And Exception Handling

### Normal collection

- The user collects from the repayment line **Collect** button.
- Normal collection is intended for the full open amount of the selected installment.
- The collection journal entry uses the configured **Collection Account** and **Receivable Account**.
- Related interest recognition for the collected month is posted as part of the live workflow.

### Full settlement

- **Full Settlement** is available after disbursement while there is still outstanding balance.
- It posts the final remaining receivable collection and recognizes remaining deferred interest.
- Remaining eligible schedule lines are completed and the loan can move to **Closed**.

### Manual exception

- **Exception** is used for a partial-payment month.
- The system posts the actual partial collection and posts the month’s full scheduled interest recognition.
- The exception line stores paid amount, principal paid, remaining principal, reference, reason, and update status.
- After exception posting, use **Update Schedule** to recalculate only future unpaid lines from the carried-forward principal balance.
- `Update Schedule` rewrites only future **draft** recognition entries. If some future recognition entries are already posted, the user is told exactly which posted entries must be reset to draft first.
- After schedule update, the user must also review and fix the **Disbursement** journal entry so total deferred interest matches the revised schedule.

## Administrative Controls

- **Cancel** and **Reset to Draft** are restricted to admin users in the form header.
- Running-loan cancellation goes through a confirmation wizard instead of cancelling immediately.
- Cancelled loans can be reset back to Draft only after linked posted entries are handled appropriately.

## Technical Notes

- [models/staff_loan.py](C:\ZenDev\Odoo\odoo_19_projects\custom_addons\tha_staff_loan\models\staff_loan.py)
  Main staff loan model, accounting flow, exception update logic, settlement, and attachment actions.
- [models/staff_loan_line.py](C:\ZenDev\Odoo\odoo_19_projects\custom_addons\tha_staff_loan\models\staff_loan_line.py)
  Repayment line behavior, status handling, payment calculations, and collection posting.
- [models/account_move.py](C:\ZenDev\Odoo\odoo_19_projects\custom_addons\tha_staff_loan\models\account_move.py)
  Loan-specific accounting move links, flags, totals, and actions.
- [models/ir_attachment.py](C:\ZenDev\Odoo\odoo_19_projects\custom_addons\tha_staff_loan\models\ir_attachment.py)
  Staff-loan-specific attachment behavior and previews.
- [wizard/staff_loan_compute_wizard.py](C:\ZenDev\Odoo\odoo_19_projects\custom_addons\tha_staff_loan\wizard\staff_loan_compute_wizard.py)
  Schedule computation, flat-rate and EMI preview, approval, settlement, exception, closing, and cancellation dialogs.
- [wizard/staff_loan_lifecycle_wizards.py](C:\ZenDev\Odoo\odoo_19_projects\custom_addons\tha_staff_loan\wizard\staff_loan_lifecycle_wizards.py)
  Split lifecycle wizard models for approval, close, and cancel.
- [wizard/staff_loan_transaction_wizards.py](C:\ZenDev\Odoo\odoo_19_projects\custom_addons\tha_staff_loan\wizard\staff_loan_transaction_wizards.py)
  Split transaction wizard models for disbursement and collection.
- [views/staff_loan_views.xml](C:\ZenDev\Odoo\odoo_19_projects\custom_addons\tha_staff_loan\views\staff_loan_views.xml)
  Main loan form, list, search, buttons, and schedule views.
- [views/staff_loan_document_views.xml](C:\ZenDev\Odoo\odoo_19_projects\custom_addons\tha_staff_loan\views\staff_loan_document_views.xml)
  Loan document workspace views and actions.
- [wizard/staff_loan_wizard_views.xml](C:\ZenDev\Odoo\odoo_19_projects\custom_addons\tha_staff_loan\wizard\staff_loan_wizard_views.xml)
  Wizard form layouts for compute, disburse, collect, exception, settlement, close, cancel, and document upload.

## Module Layout

```text
tha_staff_loan/
|-- data/
|-- models/
|-- report/
|-- security/
|-- static/
|-- views/
|-- wizard/
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
