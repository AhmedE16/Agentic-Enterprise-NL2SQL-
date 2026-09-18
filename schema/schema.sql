-- ============================================================
-- Agentic NL2SQL Project — Banking Schema (20 tables)
-- Deliberately hard: joint-account junctions, self-referential
-- hierarchies, polymorphic references, temporal/versioned data,
-- and ambiguous "two ways to read the same fact" situations.
-- ============================================================

PRAGMA foreign_keys = ON;

-- 1. Customers
CREATE TABLE customers (
    customer_id     INTEGER PRIMARY KEY,
    first_name      TEXT NOT NULL,
    last_name       TEXT NOT NULL,
    date_of_birth   DATE NOT NULL,
    email           TEXT,
    phone           TEXT,
    ssn_hash        TEXT NOT NULL,          -- never store raw SSN
    customer_since  DATE NOT NULL,
    is_vip          INTEGER DEFAULT 0        -- boolean flag, ambiguous derived vs stored
);

-- 2. Addresses (temporal — a customer can have several over time)
CREATE TABLE addresses (
    address_id      INTEGER PRIMARY KEY,
    customer_id     INTEGER NOT NULL REFERENCES customers(customer_id),
    address_line    TEXT NOT NULL,
    city            TEXT NOT NULL,
    state           TEXT,
    zip_code        TEXT,
    country         TEXT NOT NULL,
    address_type    TEXT NOT NULL,           -- 'home' | 'mailing' | 'billing'
    valid_from      DATE NOT NULL,
    valid_to        DATE                     -- NULL = current
);

-- 3. Branches
CREATE TABLE branches (
    branch_id           INTEGER PRIMARY KEY,
    branch_name         TEXT NOT NULL,
    city                TEXT NOT NULL,
    state               TEXT,
    region_manager_id   INTEGER              -- FK to employees, resolved after employees exist
);

-- 4. Employees (self-referential management hierarchy)
CREATE TABLE employees (
    employee_id     INTEGER PRIMARY KEY,
    first_name      TEXT NOT NULL,
    last_name       TEXT NOT NULL,
    branch_id       INTEGER NOT NULL REFERENCES branches(branch_id),
    manager_id      INTEGER REFERENCES employees(employee_id),  -- self-referential; NULL at top
    job_title       TEXT NOT NULL,
    hire_date       DATE NOT NULL,
    termination_date DATE
);

-- 5. Account types (lookup)
CREATE TABLE account_types (
    account_type_id INTEGER PRIMARY KEY,
    type_name       TEXT NOT NULL,           -- checking, savings, money_market, credit_line
    description     TEXT,
    monthly_fee     REAL DEFAULT 0
);

-- 6. Accounts
--    current_balance = ledger balance (includes pending)
--    available_balance = usable balance (excludes holds) — classic ambiguous-term trap
CREATE TABLE accounts (
    account_id          INTEGER PRIMARY KEY,
    account_type_id     INTEGER NOT NULL REFERENCES account_types(account_type_id),
    branch_id           INTEGER NOT NULL REFERENCES branches(branch_id),
    opened_by_employee_id INTEGER REFERENCES employees(employee_id),
    opened_date         DATE NOT NULL,
    closed_date          DATE,
    current_balance      REAL NOT NULL,
    available_balance    REAL NOT NULL,
    status               TEXT NOT NULL        -- redundant with account_status_history "current" row
);

-- 7. Account holders (junction — enables joint accounts;
--    "who owns this account" requires a join here, not a simple FK)
CREATE TABLE account_holders (
    account_id      INTEGER NOT NULL REFERENCES accounts(account_id),
    customer_id     INTEGER NOT NULL REFERENCES customers(customer_id),
    holder_role     TEXT NOT NULL,           -- primary | joint | authorized_signer
    added_date      DATE NOT NULL,
    PRIMARY KEY (account_id, customer_id)
);

-- 8. Account status history (temporal — "current status" needs MAX(changed_at) per account,
--    and may disagree with accounts.status if not kept in sync)
CREATE TABLE account_status_history (
    history_id          INTEGER PRIMARY KEY,
    account_id           INTEGER NOT NULL REFERENCES accounts(account_id),
    status                TEXT NOT NULL,
    changed_at            DATETIME NOT NULL,
    changed_by_employee_id INTEGER REFERENCES employees(employee_id),
    reason                TEXT
);

-- 9. Cards
CREATE TABLE cards (
    card_id         INTEGER PRIMARY KEY,
    account_id      INTEGER NOT NULL REFERENCES accounts(account_id),
    customer_id     INTEGER NOT NULL REFERENCES customers(customer_id),  -- denormalized on purpose
    card_type       TEXT NOT NULL,           -- debit | credit
    issued_date     DATE NOT NULL,
    expiry_date     DATE NOT NULL,
    status          TEXT NOT NULL            -- active | blocked | expired
);

-- 10. Merchants
CREATE TABLE merchants (
    merchant_id     INTEGER PRIMARY KEY,
    merchant_name   TEXT NOT NULL,
    category        TEXT NOT NULL,
    city            TEXT,
    country         TEXT
);

-- 11. Card transactions (own currency, may differ from account's home currency)
CREATE TABLE card_transactions (
    card_txn_id     INTEGER PRIMARY KEY,
    card_id         INTEGER NOT NULL REFERENCES cards(card_id),
    merchant_id     INTEGER NOT NULL REFERENCES merchants(merchant_id),
    amount          REAL NOT NULL,
    currency_code   TEXT NOT NULL,
    txn_datetime    DATETIME NOT NULL,
    status          TEXT NOT NULL,           -- approved | declined | reversed
    is_flagged      INTEGER DEFAULT 0
);

-- 12. Transaction types (lookup)
CREATE TABLE transaction_types (
    txn_type_id     INTEGER PRIMARY KEY,
    type_name       TEXT NOT NULL,           -- deposit, withdrawal, transfer_out, transfer_in, fee, interest, loan_payment
    category        TEXT NOT NULL            -- debit | credit
);

-- 13. Transactions (ledger; self-referential for reversals/linked entries)
CREATE TABLE transactions (
    transaction_id      INTEGER PRIMARY KEY,
    account_id            INTEGER NOT NULL REFERENCES accounts(account_id),
    txn_type_id            INTEGER NOT NULL REFERENCES transaction_types(txn_type_id),
    amount                  REAL NOT NULL,   -- signed: + credit, - debit
    currency_code           TEXT NOT NULL,
    txn_datetime             DATETIME NOT NULL,
    description               TEXT,
    related_transaction_id  INTEGER REFERENCES transactions(transaction_id)  -- self-ref, nullable
);

-- 14. Transfers (the SAME transfer fact is also expressible as two rows in `transactions`
--     linked via related_transaction_id — a deliberately ambiguous dual representation)
CREATE TABLE transfers (
    transfer_id             INTEGER PRIMARY KEY,
    from_account_id          INTEGER NOT NULL REFERENCES accounts(account_id),
    to_account_id             INTEGER NOT NULL REFERENCES accounts(account_id),
    amount                     REAL NOT NULL,
    initiated_at                DATETIME NOT NULL,
    completed_at                 DATETIME,
    status                        TEXT NOT NULL,   -- pending | completed | failed
    debit_transaction_id          INTEGER REFERENCES transactions(transaction_id),
    credit_transaction_id          INTEGER REFERENCES transactions(transaction_id)
);

-- 15. Loans
CREATE TABLE loans (
    loan_id             INTEGER PRIMARY KEY,
    customer_id           INTEGER NOT NULL REFERENCES customers(customer_id),
    disbursement_account_id INTEGER REFERENCES accounts(account_id),  -- nullable
    loan_type              TEXT NOT NULL,   -- mortgage | auto | personal | student
    principal_amount        REAL NOT NULL,
    origination_date          DATE NOT NULL,
    term_months                 INTEGER NOT NULL,
    status                       TEXT NOT NULL  -- active | paid_off | defaulted
);

-- 16. Loan payments
CREATE TABLE loan_payments (
    payment_id          INTEGER PRIMARY KEY,
    loan_id               INTEGER NOT NULL REFERENCES loans(loan_id),
    due_date                DATE NOT NULL,
    paid_date                 DATE,
    amount_due                  REAL NOT NULL,
    amount_paid                  REAL,
    principal_component            REAL,
    interest_component              REAL,
    late_fee                         REAL DEFAULT 0,
    status                            TEXT NOT NULL  -- on_time | late | missed | paid
);

-- 17. Interest rate history — POLYMORPHIC: applies_to_type tells you whether
--     applies_to_id points at account_types or loans. No single clean FK.
CREATE TABLE interest_rate_history (
    rate_id             INTEGER PRIMARY KEY,
    applies_to_type       TEXT NOT NULL,     -- 'account_type' | 'loan'
    applies_to_id           INTEGER NOT NULL,
    rate_pct                  REAL NOT NULL,
    effective_from              DATE NOT NULL,
    effective_to                 DATE          -- NULL = current
);

-- 18. Exchange rates (temporal; needed to reconcile card_transactions.currency_code
--     against an account's home currency, which is implied, not stored, on accounts)
CREATE TABLE exchange_rates (
    rate_id             INTEGER PRIMARY KEY,
    base_currency          TEXT NOT NULL,
    quote_currency            TEXT NOT NULL,
    rate                        REAL NOT NULL,
    rate_date                    DATE NOT NULL
);

-- 19. Fraud flags — POLYMORPHIC: entity_type tells you whether entity_id points
--     at transactions or card_transactions. Deliberately no clean FK.
CREATE TABLE fraud_flags (
    flag_id             INTEGER PRIMARY KEY,
    entity_type            TEXT NOT NULL,    -- 'transaction' | 'card_transaction'
    entity_id                INTEGER NOT NULL,
    flag_reason                 TEXT NOT NULL,
    flagged_at                    DATETIME NOT NULL,
    resolved_at                     DATETIME,
    resolution_status                 TEXT NOT NULL  -- open | confirmed_fraud | false_positive
);

-- 20. Risk scores (historical — need latest per customer via MAX(score_date))
CREATE TABLE risk_scores (
    score_id            INTEGER PRIMARY KEY,
    customer_id            INTEGER NOT NULL REFERENCES customers(customer_id),
    score_date               DATE NOT NULL,
    score_value                 REAL NOT NULL,  -- 0-1000
    model_version                  TEXT NOT NULL
);

-- Helpful indexes (kept sparse on purpose — this is not meant to be a fully-tuned schema)
CREATE INDEX idx_addresses_customer ON addresses(customer_id);
CREATE INDEX idx_accounts_branch ON accounts(branch_id);
CREATE INDEX idx_account_holders_customer ON account_holders(customer_id);
CREATE INDEX idx_transactions_account ON transactions(account_id);
CREATE INDEX idx_card_transactions_card ON card_transactions(card_id);
CREATE INDEX idx_loan_payments_loan ON loan_payments(loan_id);
CREATE INDEX idx_risk_scores_customer ON risk_scores(customer_id);
