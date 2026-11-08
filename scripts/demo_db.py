#!/usr/bin/env python3
"""Demo SQLite DB. Usage: demo_db.py [--path demo.sqlite] [--tick N]

On the first run it creates ~400 orders spread over the last 72 hours.
--tick N: add N new orders at the current time (to grow the poll history).
"""
import argparse
import datetime as dt
import random
import sqlite3

REGIONS = ["EU", "US", "APAC", "LATAM"]
STATUSES = ["paid", "paid", "paid", "pending", "refunded"]


def fmt(t):
    return t.strftime("%Y-%m-%d %H:%M:%S")


def new_order(ts):
    return (fmt(ts), random.choice(REGIONS), round(random.uniform(5, 250), 2), random.choice(STATUSES))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", default="demo.sqlite")
    ap.add_argument("--tick", type=int, default=0, help="add N new orders at the current time")
    args = ap.parse_args()

    conn = sqlite3.connect(args.path)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            region TEXT NOT NULL,
            amount REAL NOT NULL,
            status TEXT NOT NULL)"""
    )
    now = dt.datetime.now(dt.timezone.utc)
    rows = []
    if conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 0:
        rows += [new_order(now - dt.timedelta(seconds=random.randint(0, 72 * 3600))) for _ in range(400)]
    rows += [new_order(now) for _ in range(args.tick)]
    rows.sort(key=lambda r: r[0])  # keep ids increasing with time
    conn.executemany("INSERT INTO orders (created_at, region, amount, status) VALUES (?, ?, ?, ?)", rows)
    conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    conn.close()
    print(f"{args.path}: +{len(rows)} rows, total {total}")


if __name__ == "__main__":
    main()
