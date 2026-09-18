"""
Synthetic banking data generator.

Design goals (why the data is "hard"):
  - Joint accounts: some accounts have 2-3 holders via account_holders, so
    "which customer owns account X" is not a single-row lookup.
  - Status drift: accounts.status is sometimes stale relative to the latest
    account_status_history row (mirrors real-world denormalization bugs).
  - Multi-currency card transactions that don't match the account's implied
    home currency, forcing a join through exchange_rates.
  - Transfers represented twice: once in `transfers`, once as a linked pair
    of rows in `transactions` (via related_transaction_id).
  - Polymorphic fraud_flags and interest_rate_history: entity_type/
    applies_to_type must be interpreted correctly to join to the right table.
  - Overlapping interest rate history windows for the same account_type to
    force "as of date X" reasoning, not just "latest row".
  - Nullable disbursement_account_id on some loans (cash disbursement).
  - Self-referential employee hierarchy up to 3 levels deep.

Run: python generate_data.py  (writes CSVs to ./csv/)
"""
import csv
import os
import random
from datetime import date, datetime, timedelta

from faker import Faker

fake = Faker()
Faker.seed(42)
random.seed(42)

OUT_DIR = os.path.join(os.path.dirname(__file__), "csv")
os.makedirs(OUT_DIR, exist_ok=True)

N_CUSTOMERS = 400
N_BRANCHES = 12
N_EMPLOYEES = 60
N_ACCOUNTS = 550
N_CARDS = 500
N_MERCHANTS = 120
N_CARD_TXNS = 6000
N_TRANSACTIONS = 9000
N_TRANSFERS = 900
N_LOANS = 180
CURRENCIES = ["USD", "EUR", "GBP", "QAR", "AED"]


def w(name, header, rows):
    path = os.path.join(OUT_DIR, f"{name}.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)
    print(f"  wrote {name}.csv ({len(rows)} rows)")


def rand_date(start_year=2015, end_year=2025):
    start = date(start_year, 1, 1)
    end = date(end_year, 12, 31)
    return start + timedelta(days=random.randint(0, (end - start).days))


def rand_datetime(start_year=2022, end_year=2025):
    d = rand_date(start_year, end_year)
    return datetime(d.year, d.month, d.day, random.randint(0, 23), random.randint(0, 59), random.randint(0, 59))


print("Generating banking dataset...")

# ---------- 1. customers ----------
customers = []
for cid in range(1, N_CUSTOMERS + 1):
    dob = fake.date_of_birth(minimum_age=18, maximum_age=85)
    since = rand_date(2010, 2024)
    customers.append([
        cid, fake.first_name(), fake.last_name(), dob.isoformat(),
        fake.email(), fake.phone_number()[:20], fake.sha256()[:32],
        since.isoformat(), 1 if random.random() < 0.08 else 0,
    ])
w("customers", ["customer_id", "first_name", "last_name", "date_of_birth", "email", "phone", "ssn_hash", "customer_since", "is_vip"], customers)

# ---------- 2. addresses (some customers have 2, incl. a past one) ----------
addresses = []
aid = 1
for cid in range(1, N_CUSTOMERS + 1):
    n_addr = 2 if random.random() < 0.25 else 1
    for i in range(n_addr):
        is_current = (i == n_addr - 1)
        vf = rand_date(2010, 2023)
        vt = None if is_current else (vf + timedelta(days=random.randint(180, 1800))).isoformat()
        addresses.append([
            aid, cid, fake.street_address(), fake.city(), fake.state_abbr(), fake.zipcode(),
            "USA", random.choice(["home", "mailing", "billing"]), vf.isoformat(), vt,
        ])
        aid += 1
w("addresses", ["address_id", "customer_id", "address_line", "city", "state", "zip_code", "country", "address_type", "valid_from", "valid_to"], addresses)

# ---------- 3 & 4. branches & employees (self-referential hierarchy) ----------
branches = []
for bid in range(1, N_BRANCHES + 1):
    branches.append([bid, f"{fake.city()} Branch", fake.city(), fake.state_abbr(), None])

employees = []
eid = 1
# level 1: regional managers, one per ~4 branches
managers = []
for i in range(max(1, N_BRANCHES // 4)):
    branch_id = random.randint(1, N_BRANCHES)
    hire = rand_date(2008, 2015)
    employees.append([eid, fake.first_name(), fake.last_name(), branch_id, None, "Regional Manager", hire.isoformat(), None])
    managers.append(eid)
    eid += 1
# level 2: branch managers reporting to a regional manager
branch_managers = {}
for bid in range(1, N_BRANCHES + 1):
    mgr = random.choice(managers)
    hire = rand_date(2012, 2019)
    employees.append([eid, fake.first_name(), fake.last_name(), bid, mgr, "Branch Manager", hire.isoformat(), None])
    branch_managers[bid] = eid
    eid += 1
# level 3: staff reporting to their branch manager
while eid <= N_EMPLOYEES:
    bid = random.randint(1, N_BRANCHES)
    mgr = branch_managers[bid]
    hire = rand_date(2016, 2024)
    terminated = None
    if random.random() < 0.08:
        terminated = (hire + timedelta(days=random.randint(200, 1500))).isoformat()
    employees.append([eid, fake.first_name(), fake.last_name(), bid, mgr, random.choice(["Teller", "Loan Officer", "Personal Banker"]), hire.isoformat(), terminated])
    eid += 1

# backfill region_manager_id on branches
for b in branches:
    bid = b[0]
    b[4] = branch_managers[bid] if random.random() < 0.9 else random.choice(managers)

w("branches", ["branch_id", "branch_name", "city", "state", "region_manager_id"], branches)
w("employees", ["employee_id", "first_name", "last_name", "branch_id", "manager_id", "job_title", "hire_date", "termination_date"], employees)

# ---------- 5. account_types ----------
account_types = [
    [1, "checking", "Everyday checking account", 0.0],
    [2, "savings", "Interest-bearing savings account", 0.0],
    [3, "money_market", "Higher-yield money market account", 10.0],
    [4, "credit_line", "Revolving credit line", 0.0],
]
w("account_types", ["account_type_id", "type_name", "description", "monthly_fee"], account_types)

# ---------- 6 & 7. accounts & account_holders (joint accounts included) ----------
accounts = []
account_holders = []
active_employee_ids = [e[0] for e in employees]
for acc_id in range(1, N_ACCOUNTS + 1):
    atype = random.choice([1, 1, 1, 2, 2, 3, 4])  # checking most common
    branch_id = random.randint(1, N_BRANCHES)
    opened = rand_date(2015, 2024)
    closed = None
    status = "active"
    if random.random() < 0.06:
        closed = (opened + timedelta(days=random.randint(100, 2000))).isoformat()
        status = "closed"
    elif random.random() < 0.03:
        status = "frozen"
    bal = round(random.uniform(-500, 50000), 2) if atype != 4 else round(random.uniform(-8000, 0), 2)
    avail = round(bal - random.uniform(0, 300), 2) if bal > 300 else bal
    accounts.append([acc_id, atype, branch_id, random.choice(active_employee_ids), opened.isoformat(), closed, bal, avail, status])

    # holders: ~20% joint accounts with 2-3 holders
    n_holders = 1
    r = random.random()
    if r < 0.15:
        n_holders = 2
    elif r < 0.19:
        n_holders = 3
    chosen = random.sample(range(1, N_CUSTOMERS + 1), n_holders)
    for i, cust_id in enumerate(chosen):
        role = "primary" if i == 0 else random.choice(["joint", "authorized_signer"])
        account_holders.append([acc_id, cust_id, role, opened.isoformat()])

w("accounts", ["account_id", "account_type_id", "branch_id", "opened_by_employee_id", "opened_date", "closed_date", "current_balance", "available_balance", "status"], accounts)
w("account_holders", ["account_id", "customer_id", "holder_role", "added_date"], account_holders)

# ---------- 8. account_status_history (some accounts have a status not yet
#              reflected in accounts.status — deliberate drift) ----------
status_history = []
hid = 1
for acc in accounts:
    acc_id, opened_date, current_status = acc[0], acc[4], acc[8]
    opened = date.fromisoformat(opened_date)
    changed_at = datetime(opened.year, opened.month, opened.day, 9, 0, 0)
    status_history.append([hid, acc_id, "active", changed_at.isoformat(), acc[3], "account opened"])
    hid += 1
    # maybe an intermediate status change
    if random.random() < 0.2:
        mid_status = random.choice(["frozen", "under_review", "active"])
        changed_at = changed_at + timedelta(days=random.randint(30, 900))
        status_history.append([hid, acc_id, mid_status, changed_at.isoformat(), random.choice(active_employee_ids), "review"])
        hid += 1
    if current_status != "active":
        changed_at = changed_at + timedelta(days=random.randint(10, 400))
        status_history.append([hid, acc_id, current_status, changed_at.isoformat(), random.choice(active_employee_ids), "status update"])
        hid += 1
w("account_status_history", ["history_id", "account_id", "status", "changed_at", "changed_by_employee_id", "reason"], status_history)

# ---------- 9. cards (linked to an account holder, not always the primary) ----------
cards = []
account_to_holders = {}
for h in account_holders:
    account_to_holders.setdefault(h[0], []).append(h[1])

for card_id in range(1, N_CARDS + 1):
    acc_id = random.randint(1, N_ACCOUNTS)
    holder_customer = random.choice(account_to_holders.get(acc_id, [1]))
    issued = rand_date(2018, 2024)
    expiry = date(issued.year + 4, issued.month, min(issued.day, 28))
    status = "active"
    if random.random() < 0.05:
        status = "blocked"
    elif expiry < date(2025, 6, 1):
        status = "expired"
    cards.append([card_id, acc_id, holder_customer, random.choice(["debit", "credit"]), issued.isoformat(), expiry.isoformat(), status])
w("cards", ["card_id", "account_id", "customer_id", "card_type", "issued_date", "expiry_date", "status"], cards)

# ---------- 10. merchants ----------
merchant_categories = ["grocery", "restaurant", "travel", "electronics", "utilities", "entertainment", "fuel", "pharmacy", "online_retail", "clothing"]
merchants = []
for mid in range(1, N_MERCHANTS + 1):
    merchants.append([mid, fake.company(), random.choice(merchant_categories), fake.city(), random.choice(["USA", "UK", "Qatar", "UAE", "Germany", "France"])])
w("merchants", ["merchant_id", "merchant_name", "category", "city", "country"], merchants)

# ---------- 11. card_transactions (mixed currencies, some flagged/declined/reversed) ----------
card_txns = []
for txn_id in range(1, N_CARD_TXNS + 1):
    card = random.choice(cards)
    card_id = card[0]
    merchant_id = random.randint(1, N_MERCHANTS)
    amount = round(random.uniform(2, 3000), 2)
    currency = random.choices(CURRENCIES, weights=[55, 15, 10, 15, 5])[0]
    dt = rand_datetime(2022, 2025)
    status = random.choices(["approved", "declined", "reversed"], weights=[88, 8, 4])[0]
    flagged = 1 if random.random() < 0.03 else 0
    card_txns.append([txn_id, card_id, merchant_id, amount, currency, dt.isoformat(), status, flagged])
w("card_transactions", ["card_txn_id", "card_id", "merchant_id", "amount", "currency_code", "txn_datetime", "status", "is_flagged"], card_txns)

# ---------- 12. transaction_types ----------
transaction_types = [
    [1, "deposit", "credit"],
    [2, "withdrawal", "debit"],
    [3, "transfer_out", "debit"],
    [4, "transfer_in", "credit"],
    [5, "fee", "debit"],
    [6, "interest", "credit"],
    [7, "loan_payment", "debit"],
]
w("transaction_types", ["txn_type_id", "type_name", "category"], transaction_types)

# ---------- 13 & 14. transactions & transfers (dual representation) ----------
transactions = []
transfers = []
txn_id_counter = 1


def add_transaction(account_id, txn_type_id, amount, currency, dt, desc, related_id=None):
    global txn_id_counter
    tid = txn_id_counter
    transactions.append([tid, account_id, txn_type_id, amount, currency, dt.isoformat(), desc, related_id])
    txn_id_counter += 1
    return tid


# plain deposits/withdrawals/fees/interest
plain_target = int(N_TRANSACTIONS * 0.7)
for _ in range(plain_target):
    acc_id = random.randint(1, N_ACCOUNTS)
    ttype = random.choice([1, 2, 5, 6])
    amount = round(random.uniform(5, 5000), 2)
    if ttype in (2, 5):
        amount = -amount
    dt = rand_datetime(2022, 2025)
    desc = {1: "Deposit", 2: "ATM withdrawal", 5: "Monthly fee", 6: "Interest credit"}[ttype]
    add_transaction(acc_id, ttype, amount, "USD", dt, desc)

# transfers: create matching debit/credit transaction pairs AND a transfers row
for tr_id in range(1, N_TRANSFERS + 1):
    from_acc = random.randint(1, N_ACCOUNTS)
    to_acc = random.randint(1, N_ACCOUNTS)
    while to_acc == from_acc:
        to_acc = random.randint(1, N_ACCOUNTS)
    amount = round(random.uniform(10, 8000), 2)
    dt = rand_datetime(2022, 2025)
    status = random.choices(["completed", "pending", "failed"], weights=[85, 8, 7])[0]

    debit_id = add_transaction(from_acc, 3, -amount, "USD", dt, f"Transfer to account {to_acc}")
    credit_id = None
    completed_at = None
    if status == "completed":
        credit_id = add_transaction(to_acc, 4, amount, "USD", dt + timedelta(minutes=random.randint(0, 5)), f"Transfer from account {from_acc}", related_id=debit_id)
        # link back
        transactions[debit_id - 1][7] = credit_id
        completed_at = (dt + timedelta(minutes=random.randint(0, 5))).isoformat()

    transfers.append([tr_id, from_acc, to_acc, amount, dt.isoformat(), completed_at, status, debit_id, credit_id])

# fill remaining transaction quota with loan payments (linked later) placeholder skipped;
# top up with a few more plain transactions to hit target count
while txn_id_counter <= N_TRANSACTIONS:
    acc_id = random.randint(1, N_ACCOUNTS)
    ttype = random.choice([1, 2])
    amount = round(random.uniform(5, 2000), 2)
    if ttype == 2:
        amount = -amount
    dt = rand_datetime(2022, 2025)
    add_transaction(acc_id, ttype, amount, "USD", dt, "Misc transaction")

w("transactions", ["transaction_id", "account_id", "txn_type_id", "amount", "currency_code", "txn_datetime", "description", "related_transaction_id"], transactions)
w("transfers", ["transfer_id", "from_account_id", "to_account_id", "amount", "initiated_at", "completed_at", "status", "debit_transaction_id", "credit_transaction_id"], transfers)

# ---------- 15 & 16. loans & loan_payments ----------
loans = []
loan_payments = []
lp_id = 1
loan_types = ["mortgage", "auto", "personal", "student"]
for loan_id in range(1, N_LOANS + 1):
    cust_id = random.randint(1, N_CUSTOMERS)
    ltype = random.choice(loan_types)
    principal = {"mortgage": random.uniform(80000, 500000), "auto": random.uniform(8000, 45000),
                 "personal": random.uniform(1000, 20000), "student": random.uniform(5000, 60000)}[ltype]
    principal = round(principal, 2)
    origination = rand_date(2016, 2024)
    term = {"mortgage": random.choice([180, 240, 360]), "auto": random.choice([36, 48, 60, 72]),
            "personal": random.choice([12, 24, 36]), "student": random.choice([60, 120, 180])}[ltype]
    # ~15% loans have no disbursement account (cash disbursement)
    disb_acc = random.randint(1, N_ACCOUNTS) if random.random() > 0.15 else None
    status = random.choices(["active", "paid_off", "defaulted"], weights=[70, 25, 5])[0]
    loans.append([loan_id, cust_id, disb_acc, ltype, principal, origination.isoformat(), term, status])

    n_payments = random.randint(3, 24)
    monthly = round(principal / term * random.uniform(1.0, 1.3), 2)
    due = origination
    for _ in range(n_payments):
        due = due + timedelta(days=30)
        paid_status = random.choices(["paid", "on_time", "late", "missed"], weights=[40, 35, 18, 7])[0]
        paid_date = due.isoformat() if paid_status in ("paid", "on_time") else (
            (due + timedelta(days=random.randint(1, 20))).isoformat() if paid_status == "late" else None
        )
        amount_paid = monthly if paid_status != "missed" else None
        interest_component = round(monthly * random.uniform(0.2, 0.6), 2) if amount_paid else None
        principal_component = round(amount_paid - interest_component, 2) if amount_paid else None
        late_fee = round(random.uniform(15, 75), 2) if paid_status in ("late", "missed") else 0.0
        loan_payments.append([lp_id, loan_id, due.isoformat(), paid_date, monthly, amount_paid, principal_component, interest_component, late_fee, paid_status])
        lp_id += 1

w("loans", ["loan_id", "customer_id", "disbursement_account_id", "loan_type", "principal_amount", "origination_date", "term_months", "status"], loans)
w("loan_payments", ["payment_id", "loan_id", "due_date", "paid_date", "amount_due", "amount_paid", "principal_component", "interest_component", "late_fee", "status"], loan_payments)

# ---------- 17. interest_rate_history (polymorphic, with OVERLAPPING windows
#               for the same account_type_id to force "as of date" logic) ----------
interest_rates = []
rid = 1
for atype_id in [2, 3]:  # savings, money_market carry published rates
    rate = random.uniform(0.5, 2.0)
    start = date(2018, 1, 1)
    while start < date(2025, 6, 1):
        end = start + timedelta(days=random.randint(150, 400))
        interest_rates.append([rid, "account_type", atype_id, round(rate, 3), start.isoformat(), end.isoformat() if end < date(2025, 6, 1) else None])
        rid += 1
        rate += random.uniform(-0.3, 0.4)
        start = end
for loan in loans:
    if random.random() < 0.6:  # not every loan has a recorded rate row
        rate = random.uniform(3.0, 9.5)
        interest_rates.append([rid, "loan", loan[0], round(rate, 3), loan[5], None])
        rid += 1
w("interest_rate_history", ["rate_id", "applies_to_type", "applies_to_id", "rate_pct", "effective_from", "effective_to"], interest_rates)

# ---------- 18. exchange_rates (temporal, multiple dates per pair) ----------
exchange_rates = []
erid = 1
base_rates = {"EUR": 1.08, "GBP": 1.27, "QAR": 0.275, "AED": 0.272}
d = date(2022, 1, 1)
while d < date(2025, 9, 1):
    for cur, base in base_rates.items():
        jitter = random.uniform(-0.03, 0.03)
        exchange_rates.append([erid, cur, "USD", round(base + jitter, 4), d.isoformat()])
        erid += 1
    d += timedelta(days=30)
w("exchange_rates", ["rate_id", "base_currency", "quote_currency", "rate", "rate_date"], exchange_rates)

# ---------- 19. fraud_flags (polymorphic: transaction OR card_transaction) ----------
fraud_flags = []
fid = 1
flagged_card_txns = [t for t in card_txns if t[7] == 1]
for t in flagged_card_txns:
    flagged_at = datetime.fromisoformat(t[5]) + timedelta(hours=random.randint(1, 48))
    resolved = random.random() < 0.6
    resolved_at = (flagged_at + timedelta(days=random.randint(1, 10))).isoformat() if resolved else None
    res_status = random.choice(["confirmed_fraud", "false_positive"]) if resolved else "open"
    fraud_flags.append([fid, "card_transaction", t[0], random.choice(["unusual_location", "amount_spike", "velocity_check", "merchant_risk"]), flagged_at.isoformat(), resolved_at, res_status])
    fid += 1
# also flag a handful of ledger transactions directly
for _ in range(80):
    t = random.choice(transactions)
    flagged_at = datetime.fromisoformat(t[5]) + timedelta(hours=random.randint(1, 48))
    resolved = random.random() < 0.5
    resolved_at = (flagged_at + timedelta(days=random.randint(1, 10))).isoformat() if resolved else None
    res_status = random.choice(["confirmed_fraud", "false_positive"]) if resolved else "open"
    fraud_flags.append([fid, "transaction", t[0], random.choice(["duplicate_entry", "amount_spike", "account_takeover_suspected"]), flagged_at.isoformat(), resolved_at, res_status])
    fid += 1
w("fraud_flags", ["flag_id", "entity_type", "entity_id", "flag_reason", "flagged_at", "resolved_at", "resolution_status"], fraud_flags)

# ---------- 20. risk_scores (historical, multiple per customer) ----------
risk_scores = []
sid = 1
for cid in range(1, N_CUSTOMERS + 1):
    n_scores = random.randint(1, 5)
    base = random.uniform(300, 800)
    d = rand_date(2021, 2023)
    for _ in range(n_scores):
        base += random.uniform(-40, 40)
        base = max(0, min(1000, base))
        risk_scores.append([sid, cid, d.isoformat(), round(base, 1), random.choice(["v1.2", "v1.3", "v2.0"])])
        sid += 1
        d = d + timedelta(days=random.randint(60, 240))
        if d > date(2025, 8, 1):
            break
w("risk_scores", ["score_id", "customer_id", "score_date", "score_value", "model_version"], risk_scores)

print(f"\nDone. CSVs written to {OUT_DIR}")
