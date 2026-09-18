"""
Metadata Registry module.
Defines rich, structured descriptions of database tables for semantic routing.
"""
import json
import os
import sqlite3

HERE = os.path.dirname(__file__)
DB_PATH = os.path.join(HERE, "..", "db", "bank.db")
OUT_PATH = os.path.join(HERE, "registry.json")

# Hand-authored descriptions are what make routing actually work well —
# this is the part a real project would spend the most human effort on.
TABLE_DOCS = {
    "customers": {
        "description": (
            "Bank customers (individual account holders). One row per person. "
            "Note: a customer's relationship to accounts is NOT a direct foreign key here — "
            "it goes through account_holders, because accounts can be jointly owned."
        ),
        "columns": {
            "customer_id": "Primary key.",
            "first_name": "Given name.",
            "last_name": "Family name.",
            "date_of_birth": "DOB, used for age calculations.",
            "email": "Contact email.",
            "phone": "Contact phone number.",
            "ssn_hash": "Hashed SSN, not the raw value.",
            "customer_since": "Date the customer relationship began.",
            "is_vip": "1 if flagged VIP, 0 otherwise.",
        },
        "relationships": [
            "customers.customer_id is referenced by addresses, account_holders, loans, risk_scores, cards.customer_id.",
            "To find a customer's accounts, join through account_holders, not a direct FK.",
        ],
    },
    "addresses": {
        "description": (
            "Customer addresses over time. A customer can have multiple rows (home/mailing/billing) "
            "and multiple historical addresses. valid_to IS NULL means the address is current."
        ),
        "columns": {
            "address_id": "Primary key.",
            "customer_id": "FK to customers.",
            "address_line": "Street address.",
            "city": "City.", "state": "State/province.", "zip_code": "Postal code.", "country": "Country.",
            "address_type": "'home', 'mailing', or 'billing'.",
            "valid_from": "Date this address became effective.",
            "valid_to": "Date this address stopped being effective; NULL means current.",
        },
        "relationships": ["addresses.customer_id -> customers.customer_id"],
    },
    "branches": {
        "description": "Physical bank branch locations. Each branch has a region_manager_id pointing to an employee.",
        "columns": {
            "branch_id": "Primary key.",
            "branch_name": "Display name.",
            "city": "City.", "state": "State.",
            "region_manager_id": "FK to employees.employee_id — the regional manager overseeing this branch.",
        },
        "relationships": ["branches.region_manager_id -> employees.employee_id"],
    },
    "employees": {
        "description": (
            "Bank staff. Self-referential management hierarchy via manager_id "
            "(regional manager -> branch manager -> tellers/loan officers/personal bankers). "
            "A NULL manager_id means top of the hierarchy."
        ),
        "columns": {
            "employee_id": "Primary key.",
            "first_name": "Given name.", "last_name": "Family name.",
            "branch_id": "FK to branches — where this employee works.",
            "manager_id": "Self-referential FK to employees.employee_id — this employee's manager. NULL at the top.",
            "job_title": "e.g. Regional Manager, Branch Manager, Teller, Loan Officer, Personal Banker.",
            "hire_date": "Date hired.",
            "termination_date": "Date employment ended, if applicable; NULL means currently employed.",
        },
        "relationships": [
            "employees.branch_id -> branches.branch_id",
            "employees.manager_id -> employees.employee_id (self-referential; use recursive CTE for multi-level hierarchy)",
        ],
    },
    "account_types": {
        "description": "Lookup table of account product types (checking, savings, money_market, credit_line) and their monthly fee.",
        "columns": {
            "account_type_id": "Primary key.",
            "type_name": "checking | savings | money_market | credit_line.",
            "description": "Human-readable description.",
            "monthly_fee": "Flat monthly fee for this account type.",
        },
        "relationships": ["Referenced by accounts.account_type_id. Also referenced polymorphically by interest_rate_history when applies_to_type='account_type'."],
    },
    "accounts": {
        "description": (
            "Bank accounts. current_balance is the ledger balance (includes pending items); "
            "available_balance excludes holds and is usually <= current_balance — these two terms "
            "are often confused in natural-language questions ('balance' is ambiguous). "
            "status is a point-in-time snapshot that can be stale relative to account_status_history — "
            "for the true current status, check the latest row in account_status_history, not this column."
        ),
        "columns": {
            "account_id": "Primary key.",
            "account_type_id": "FK to account_types.",
            "branch_id": "FK to branches — where the account was opened/is held.",
            "opened_by_employee_id": "FK to employees — who opened the account.",
            "opened_date": "Date opened.", "closed_date": "Date closed, if applicable.",
            "current_balance": "Ledger balance (includes pending transactions).",
            "available_balance": "Usable balance (excludes holds); may lag current_balance.",
            "status": "active | closed | frozen. May be stale — see account_status_history for authoritative current status.",
        },
        "relationships": [
            "accounts.account_type_id -> account_types.account_type_id",
            "accounts.branch_id -> branches.branch_id",
            "Ownership is NOT a direct FK: join via account_holders to find which customer(s) own an account.",
            "Referenced by cards, transactions, transfers (from/to), account_status_history, loans.disbursement_account_id.",
        ],
    },
    "account_holders": {
        "description": (
            "Junction table between customers and accounts — this is how joint accounts work. "
            "An account can have multiple rows here (primary + joint + authorized_signer). "
            "Always join through this table to answer 'which customer(s) own account X' or "
            "'which accounts does customer Y hold'."
        ),
        "columns": {
            "account_id": "FK to accounts (part of composite PK).",
            "customer_id": "FK to customers (part of composite PK).",
            "holder_role": "primary | joint | authorized_signer.",
            "added_date": "Date this customer was added as a holder.",
        },
        "relationships": ["account_holders.account_id -> accounts.account_id", "account_holders.customer_id -> customers.customer_id"],
    },
    "account_status_history": {
        "description": (
            "Full history of status changes for each account. To get an account's status 'as of' a "
            "given date, filter changed_at <= that date and take the latest row. This is the "
            "authoritative source of truth for status over time, more reliable than accounts.status."
        ),
        "columns": {
            "history_id": "Primary key.",
            "account_id": "FK to accounts.",
            "status": "Status value as of changed_at.",
            "changed_at": "Timestamp of the change.",
            "changed_by_employee_id": "FK to employees — who made the change.",
            "reason": "Free-text reason.",
        },
        "relationships": ["account_status_history.account_id -> accounts.account_id"],
    },
    "cards": {
        "description": (
            "Debit/credit cards linked to an account. Note customer_id here is denormalized (the card "
            "holder, who may be any holder of the account, not necessarily the primary one)."
        ),
        "columns": {
            "card_id": "Primary key.",
            "account_id": "FK to accounts — the account this card draws from.",
            "customer_id": "FK to customers — the named cardholder (denormalized).",
            "card_type": "debit | credit.",
            "issued_date": "Date issued.", "expiry_date": "Expiration date.",
            "status": "active | blocked | expired.",
        },
        "relationships": [
            "cards.account_id -> accounts.account_id",
            "cards.customer_id -> customers.customer_id",
            "Referenced by card_transactions.card_id. (WARNING: Do not join card_id to any account_id columns in other tables)",
        ],
    },
    "merchants": {
        "description": "Merchants where card transactions occur.",
        "columns": {
            "merchant_id": "Primary key.", "merchant_name": "Display name.",
            "category": "e.g. grocery, restaurant, travel, electronics, fuel.",
            "city": "City.", "country": "Country.",
        },
        "relationships": ["Referenced by card_transactions.merchant_id."],
    },
    "card_transactions": {
        "description": (
            "Individual card swipe/online transactions. currency_code may differ from USD — "
            "convert via exchange_rates when comparing/aggregating across currencies. "
            "is_flagged=1 marks transactions flagged for review; see fraud_flags for details "
            "(join via entity_type='card_transaction' AND entity_id=card_txn_id)."
        ),
        "columns": {
            "card_txn_id": "Primary key.",
            "card_id": "FK to cards.", "merchant_id": "FK to merchants.",
            "amount": "Transaction amount in currency_code (always positive; it's a charge).",
            "currency_code": "ISO currency code, e.g. USD, EUR, GBP, QAR, AED.",
            "txn_datetime": "Timestamp of the transaction.",
            "status": "approved | declined | reversed.",
            "is_flagged": "1 if flagged for fraud review, 0 otherwise.",
        },
        "relationships": [
            "card_transactions.card_id -> cards.card_id",
            "card_transactions.merchant_id -> merchants.merchant_id",
            "card_transactions.currency_code -> exchange_rates.base_currency (for conversion to USD)",
            "Polymorphically referenced by fraud_flags when entity_type='card_transaction'.",
        ],
    },
    "transaction_types": {
        "description": "Lookup table of ledger transaction types and whether each is a debit or credit.",
        "columns": {
            "txn_type_id": "Primary key.",
            "type_name": "deposit | withdrawal | transfer_out | transfer_in | fee | interest | loan_payment.",
            "category": "debit or credit.",
        },
        "relationships": ["Referenced by transactions.txn_type_id."],
    },
    "transactions": {
        "description": (
            "The core ledger. amount is signed: positive = credit, negative = debit. "
            "related_transaction_id links paired entries, most commonly the debit/credit pair created "
            "by a transfer (see also the `transfers` table, which records the SAME transfer as a single "
            "row with from_account_id/to_account_id — do not double count when both are queried together)."
        ),
        "columns": {
            "transaction_id": "Primary key.",
            "account_id": "FK to accounts — the account this entry posted to.",
            "txn_type_id": "FK to transaction_types.",
            "amount": "Signed amount: negative = debit, positive = credit.",
            "currency_code": "ISO currency code.",
            "txn_datetime": "Timestamp.",
            "description": "Free-text description.",
            "related_transaction_id": "Self-referential FK to transactions.transaction_id — links paired entries (e.g. a transfer's debit and credit legs). NULL if not paired.",
        },
        "relationships": [
            "transactions.account_id -> accounts.account_id",
            "transactions.txn_type_id -> transaction_types.txn_type_id",
            "transactions.related_transaction_id -> transactions.transaction_id (self-referential)",
            "transfers.debit_transaction_id and transfers.credit_transaction_id both -> transactions.transaction_id",
            "Polymorphically referenced by fraud_flags when entity_type='transaction'.",
        ],
    },
    "transfers": {
        "description": (
            "Money movements between two accounts, recorded at the transfer level (one row per transfer). "
            "The SAME transfer is also represented as two rows in `transactions` (the debit leg on "
            "from_account_id and the credit leg on to_account_id), linked via debit_transaction_id / "
            "credit_transaction_id. Use `transfers` for transfer-centric questions (status, who-to-whom); "
            "use `transactions` for account-ledger questions. Do not sum both representations together "
            "or amounts will be double-counted. credit_transaction_id is NULL if the transfer never completed."
        ),
        "columns": {
            "transfer_id": "Primary key.",
            "from_account_id": "FK to accounts — source account.",
            "to_account_id": "FK to accounts — destination account.",
            "amount": "Transfer amount (positive).",
            "initiated_at": "Timestamp initiated.",
            "completed_at": "Timestamp completed; NULL if not completed.",
            "status": "pending | completed | failed.",
            "debit_transaction_id": "FK to transactions — the debit leg on from_account_id.",
            "credit_transaction_id": "FK to transactions — the credit leg on to_account_id. NULL if not completed.",
        },
        "relationships": [
            "transfers.from_account_id -> accounts.account_id (WARNING: DO NOT join to cards.card_id)",
            "transfers.to_account_id -> accounts.account_id (WARNING: DO NOT join to cards.card_id)",
            "transfers.debit_transaction_id -> transactions.transaction_id",
            "transfers.credit_transaction_id -> transactions.transaction_id",
        ],
    },
    "loans": {
        "description": (
            "Loan accounts (mortgage, auto, personal, student). disbursement_account_id is nullable — "
            "about 15% of loans were disbursed as cash and have no linked deposit account."
        ),
        "columns": {
            "loan_id": "Primary key.",
            "customer_id": "FK to customers — the borrower.",
            "disbursement_account_id": "FK to accounts, nullable — where loan funds were deposited, if any.",
            "loan_type": "mortgage | auto | personal | student.",
            "principal_amount": "Original loan amount.",
            "origination_date": "Date the loan was issued.",
            "term_months": "Loan term in months.",
            "status": "active | paid_off | defaulted.",
        },
        "relationships": [
            "loans.customer_id -> customers.customer_id",
            "loans.disbursement_account_id -> accounts.account_id (nullable)",
            "Referenced by loan_payments.loan_id.",
            "Polymorphically referenced by interest_rate_history when applies_to_type='loan'.",
        ],
    },
    "loan_payments": {
        "description": "Scheduled and actual payments against a loan, including principal/interest split and late fees.",
        "columns": {
            "payment_id": "Primary key.", "loan_id": "FK to loans.",
            "due_date": "Date payment was due.", "paid_date": "Date actually paid; NULL if missed.",
            "amount_due": "Scheduled payment amount.", "amount_paid": "Actual amount paid; NULL if missed.",
            "principal_component": "Portion of amount_paid applied to principal.",
            "interest_component": "Portion of amount_paid applied to interest.",
            "late_fee": "Late fee charged, if any.",
            "status": "on_time | late | missed | paid.",
        },
        "relationships": ["loan_payments.loan_id -> loans.loan_id"],
    },
    "interest_rate_history": {
        "description": (
            "POLYMORPHIC table: applies_to_type tells you what applies_to_id refers to — either "
            "'account_type' (join to account_types.account_type_id) or 'loan' (join to loans.loan_id). "
            "There is no single clean foreign key; you must filter on applies_to_type first. "
            "Rate windows for the same account_type_id can be sequential (effective_to of one row is "
            "close to effective_from of the next) — for a rate 'as of' a date, filter "
            "effective_from <= date AND (effective_to IS NULL OR effective_to >= date)."
        ),
        "columns": {
            "rate_id": "Primary key.",
            "applies_to_type": "'account_type' or 'loan' — determines which table applies_to_id references.",
            "applies_to_id": "Polymorphic FK: account_types.account_type_id or loans.loan_id depending on applies_to_type.",
            "rate_pct": "Interest rate percentage.",
            "effective_from": "Date this rate became effective.",
            "effective_to": "Date this rate stopped applying; NULL means still current.",
        },
        "relationships": [
            "interest_rate_history.applies_to_id -> account_types.account_type_id WHEN applies_to_type='account_type'",
            "interest_rate_history.applies_to_id -> loans.loan_id WHEN applies_to_type='loan'",
        ],
    },
    "exchange_rates": {
        "description": (
            "Historical FX rates to USD, sampled roughly monthly. Use rate_date closest to (or on/before) "
            "the transaction date being converted, not just the latest rate, for point-in-time accuracy."
        ),
        "columns": {
            "rate_id": "Primary key.",
            "base_currency": "Currency being converted from (e.g. EUR).",
            "quote_currency": "Currency being converted to (always USD in this dataset).",
            "rate": "Multiply an amount in base_currency by this to get quote_currency.",
            "rate_date": "Date this rate applied.",
        },
        "relationships": ["exchange_rates.base_currency joins loosely to card_transactions.currency_code / transactions.currency_code."],
    },
    "fraud_flags": {
        "description": (
            "POLYMORPHIC table: entity_type tells you what entity_id refers to — either 'transaction' "
            "(join to transactions.transaction_id) or 'card_transaction' (join to "
            "card_transactions.card_txn_id). There is no single clean foreign key; filter on entity_type "
            "first, then join to the correct table."
        ),
        "columns": {
            "flag_id": "Primary key.",
            "entity_type": "'transaction' or 'card_transaction' — determines which table entity_id references.",
            "entity_id": "Polymorphic FK: transactions.transaction_id or card_transactions.card_txn_id depending on entity_type.",
            "flag_reason": "e.g. unusual_location, amount_spike, velocity_check, duplicate_entry.",
            "flagged_at": "Timestamp flagged.",
            "resolved_at": "Timestamp resolved; NULL if still open.",
            "resolution_status": "open | confirmed_fraud | false_positive.",
        },
        "relationships": [
            "fraud_flags.entity_id -> transactions.transaction_id WHEN entity_type='transaction'",
            "fraud_flags.entity_id -> card_transactions.card_txn_id WHEN entity_type='card_transaction'",
        ],
    },
    "risk_scores": {
        "description": (
            "Historical customer risk scores (0-1000, higher = riskier), multiple rows per customer over "
            "time. For a customer's 'current' risk score, take the row with the latest score_date."
        ),
        "columns": {
            "score_id": "Primary key.", "customer_id": "FK to customers.",
            "score_date": "Date the score was computed.",
            "score_value": "Risk score, 0-1000.",
            "model_version": "Version of the scoring model used, e.g. v1.2, v2.0.",
        },
        "relationships": ["risk_scores.customer_id -> customers.customer_id"],
    },
}


def get_table_ddl_and_samples(conn, table, n_samples=3):
    cur = conn.cursor()
    cols_info = cur.execute(f"PRAGMA table_info({table})").fetchall()
    col_types = {c[1]: c[2] for c in cols_info}
    col_names = [c[1] for c in cols_info]
    rows = cur.execute(f"SELECT * FROM {table} LIMIT {n_samples}").fetchall()
    sample_rows = [dict(zip(col_names, r)) for r in rows]
    row_count = cur.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    return col_types, sample_rows, row_count


def build_registry():
    conn = sqlite3.connect(DB_PATH)
    registry = []
    for table, doc in TABLE_DOCS.items():
        col_types, sample_rows, row_count = get_table_ddl_and_samples(conn, table)
        columns = []
        for col_name, col_type in col_types.items():
            columns.append({
                "name": col_name,
                "type": col_type,
                "description": doc["columns"].get(col_name, ""),
            })
        registry.append({
            "table_name": table,
            "description": doc["description"],
            "row_count": row_count,
            "columns": columns,
            "sample_rows": sample_rows,
            "relationships": doc["relationships"],
        })
    conn.close()
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2, default=str)
    print(f"Registry written to {OUT_PATH} ({len(registry)} tables)")
    return registry


def table_to_embedding_text(entry):
    """
    Flattens a registry entry into the text blob that gets embedded for
    semantic routing. Includes description, column names+descriptions,
    and relationship notes (but not full sample rows, to keep it dense).
    """
    parts = [f"Table: {entry['table_name']}", f"Description: {entry['description']}"]
    col_lines = [f"  - {c['name']} ({c['type']}): {c['description']}" for c in entry["columns"]]
    parts.append("Columns:\n" + "\n".join(col_lines))
    if entry["relationships"]:
        parts.append("Relationships:\n" + "\n".join(f"  - {r}" for r in entry["relationships"]))
    return "\n".join(parts)


if __name__ == "__main__":
    reg = build_registry()
    print("\n--- Sample embedding text for `transfers` ---\n")
    tr = next(e for e in reg if e["table_name"] == "transfers")
    print(table_to_embedding_text(tr))
