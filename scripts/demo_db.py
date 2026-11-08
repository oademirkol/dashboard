#!/usr/bin/env python3
"""Demo SQLite DB. Usage: demo_db.py [--path demo.sqlite] [--tick N]

On the first run it creates 40 fake customers and ~400 orders spread over the last 72 hours.
--tick N: add N new orders at the current time (to grow the poll history).
All data is fake (example.com addresses).
"""
import argparse
import datetime as dt
import random
import sqlite3

REGIONS = ["EU", "US", "APAC", "LATAM"]
STATUSES = ["paid", "paid", "paid", "pending", "refunded"]
SEGMENTS = ["SMB", "Enterprise", "Consumer"]
COUNTRIES = ["Germany", "France", "USA", "Canada", "Japan", "India", "Brazil", "Mexico"]
FIRST = ["Alex", "Sam", "Jordan", "Taylor", "Morgan", "Casey", "Riley", "Jamie", "Avery", "Quinn"]
LAST = ["Smith", "Garcia", "Chen", "Kowalski", "Tanaka", "Silva", "Novak", "Okafor"]
N_CUSTOMERS = 40


def fmt(t):
    return t.strftime("%Y-%m-%d %H:%M:%S")


def new_order(ts, customer_ids):
    return (
        fmt(ts),
        random.choice(REGIONS),
        round(random.uniform(5, 250), 2),
        random.choice(STATUSES),
        random.choice(customer_ids),
    )


def seed_customers(conn):
    """Insert N_CUSTOMERS fake customers (unique names so emails are unique)."""
    names = [f"{f} {l}" for f in FIRST for l in LAST]
    random.shuffle(names)
    rows = []
    for name in names[:N_CUSTOMERS]:
        email = name.lower().replace(" ", ".") + "@example.com"
        rows.append((name, email, random.choice(COUNTRIES), random.choice(SEGMENTS)))
    conn.executemany("INSERT INTO customers (name, email, country, segment) VALUES (?, ?, ?, ?)", rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", default="demo.sqlite")
    ap.add_argument("--tick", type=int, default=0, help="add N new orders at the current time")
    args = ap.parse_args()

    conn = sqlite3.connect(args.path)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            country TEXT NOT NULL,
            segment TEXT NOT NULL)"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            region TEXT NOT NULL,
            amount REAL NOT NULL,
            status TEXT NOT NULL,
            customer_id INTEGER NOT NULL REFERENCES customers(id))"""
    )
    if conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0] == 0:
        seed_customers(conn)
    customer_ids = [r[0] for r in conn.execute("SELECT id FROM customers")]

    now = dt.datetime.now(dt.timezone.utc)
    rows = []
    if conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 0:
        rows += [
            new_order(now - dt.timedelta(seconds=random.randint(0, 72 * 3600)), customer_ids)
            for _ in range(400)
        ]
    rows += [new_order(now, customer_ids) for _ in range(args.tick)]
    rows.sort(key=lambda r: r[0])  # keep ids increasing with time
    conn.executemany(
        "INSERT INTO orders (created_at, region, amount, status, customer_id) VALUES (?, ?, ?, ?, ?)", rows
    )
    conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    conn.close()
    print(f"{args.path}: +{len(rows)} rows, total {total}")


if __name__ == "__main__":
    main()
