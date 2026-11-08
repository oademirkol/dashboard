#!/usr/bin/env python3
"""Run the SQL queries from config.yml and write the result to docs/data/dashboard.json."""
import argparse
import datetime as dt
import decimal
import json
import os
import sys
from pathlib import Path

import yaml


def jsonable(v):
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, (dt.datetime, dt.date, dt.time)):
        return v.isoformat()
    if isinstance(v, (bytes, bytearray)):
        return v.hex()
    return v


def connect(db):
    kind = db.get("type", "sqlite")
    env = db.get("dsn_env", "DB_DSN")
    dsn = os.environ.get(env) or db.get("dsn_default")
    if not dsn:
        sys.exit(f"No DSN: set the {env} environment variable")
    if kind == "sqlite":
        import sqlite3
        if not Path(dsn).exists():
            sys.exit(f"{dsn} not found (for the demo run: python scripts/demo_db.py)")
        return sqlite3.connect(f"file:{dsn}?mode=ro", uri=True)
    if kind == "postgres":
        import psycopg2
        conn = psycopg2.connect(dsn)
        conn.set_session(readonly=True)
        return conn
    if kind == "mssql":
        import pyodbc
        return pyodbc.connect(dsn)
    sys.exit(f"Unknown database.type: {kind}")


def run_query(conn, sql, max_rows):
    cur = conn.cursor()
    try:
        cur.execute(sql)
        cols = [d[0] for d in cur.description]
        rows = [[jsonable(v) for v in r] for r in cur.fetchmany(max_rows)]
    finally:
        cur.close()
    return cols, rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yml")
    ap.add_argument("--out", default="docs/data/dashboard.json")
    args = ap.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    out = Path(args.out)

    prev = {}
    if out.exists():
        try:
            data = json.loads(out.read_text(encoding="utf-8"))
            prev = {m["name"]: m for m in data.get("metrics", [])}
        except (ValueError, KeyError, TypeError):
            prev = {}

    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    conn = connect(cfg["database"])
    metrics = []

    for m in cfg["metrics"]:
        name = m["name"]
        mtype = m.get("type", "table")
        mode = m.get("mode", "append" if mtype == "line" else "snapshot")
        old = prev.get(name, {})
        entry = {
            "name": name,
            "title": m.get("title", name),
            "type": mtype,
            "mode": mode,
            "wide": bool(m.get("wide", False)),
        }
        try:
            cols, rows = run_query(conn, m["sql"], int(m.get("max_rows", 500)))
            entry.update(columns=cols, rows=rows, updated=now, error=None)
            if mode == "append":
                hist = list(old.get("history", []))
                if rows:
                    hist.append({"ts": now, "values": dict(zip(cols, rows[0]))})
                entry["history"] = hist[-int(m.get("max_points", 500)):]
        except Exception as e:  # noqa: BLE001 - one failing metric must not stop the others
            # Details go only to the Actions log; never leak DB error text into the public JSON.
            print(f"::warning::{name}: {e}", file=sys.stderr)
            try:
                conn.rollback()
            except Exception:  # noqa: BLE001
                pass
            entry.update(
                columns=old.get("columns", []),
                rows=old.get("rows", []),
                updated=old.get("updated"),
                error="query failed (details in the Actions log)",
            )
            if mode == "append":
                entry["history"] = old.get("history", [])
        metrics.append(entry)

    conn.close()

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "title": cfg.get("title", "Dashboard"),
                "generated_at": now,
                "refresh_seconds": int(cfg.get("refresh_seconds", 60)),
                "metrics": metrics,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    failed = sum(1 for m in metrics if m["error"])
    print(f"{len(metrics) - failed}/{len(metrics)} metrics updated -> {out}")
    if metrics and failed == len(metrics):
        sys.exit(1)


if __name__ == "__main__":
    main()
