{
    "name": "Staff Loan Management",
    "version": "19.0.1.0.3",
    "summary": "Manage staff loans, schedules, disbursements, and collections",
    "description": """
Staff Loan Management
=====================

Manage employee loans with flat-rate repayment schedules, approval,
disbursement accounting, manual collections, documents, notes, and reports.
    """,
    "author": "Thein Htoo Aung",
    "category": "Accounting",
    "license": "LGPL-3",
    "depends": [
        "accountant",
        "account",
        "hr",
        "mail",
    ],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/sequence.xml",
        "views/account_move_views.xml",
        "views/staff_loan_views.xml",
        "views/staff_loan_document_views.xml",
        "wizard/staff_loan_wizard_views.xml",
        "report/staff_loan_reports.xml",
        "report/staff_loan_templates.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "tha_staff_loan/static/src/components/staff_loan_document_uploader/*.js",
            "tha_staff_loan/static/src/components/staff_loan_document_uploader/*.xml",
            "tha_staff_loan/static/src/views/*.js",
            "tha_staff_loan/static/src/views/*.xml",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
}
