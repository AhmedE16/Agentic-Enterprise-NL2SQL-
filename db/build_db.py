"""
Builds the SQLite banking database from schema.sql + generated CSVs.

Run: python build_db.py
Produces: bank.db (in this directory)
"""
import csv
import os
import sqlite3

HERE = os.path.dirname(__file__)
SCHEMA_PATH = os.path.join(HERE, "..", "schema", "schema.sql")
CSV_DIR = os.path.join(HERE, "..", "data", "csv")
DB_PATH = os.path.join(HERE, "bank.db")

# Load order matters: parents before children (FK dependencies)
LOAD_ORDER = [
    "customers", "addresses", "branches", "employees", "account_types",
    "accounts", "account_holders", "account_status_history", "cards",
    "merchants", "card_transactions", "transaction_types", "transactions",
    "transfers", "loans", "loan_payments", "interest_rate_history",
    "exchange_rates", "fraud_flags", "risk_scores",
]


def build():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    conn = sqlite3.connect(DB_PATH)
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        conn.executescript(f.read())
    conn.execute("PRAGMA foreign_keys = OFF")  # off during bulk load (schema.sql still declares FKs)

    cur = conn.cursor()
    for table in LOAD_ORDER:
        path = os.path.join(CSV_DIR, f"{table}.csv")
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader)
            rows = list(reader)
            placeholders = ",".join(["?"] * len(header))
            cur.executemany(f"INSERT INTO {table} ({','.join(header)}) VALUES ({placeholders})", rows)
        conn.commit()
        count = cur.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  loaded {table}: {count} rows")

    conn.execute("PRAGMA foreign_keys = ON")
    conn.close()
    print(f"\nDatabase built at {DB_PATH}")


if __name__ == "__main__":
    build()
