#!/usr/bin/env python3
"""Run the SQL queries from config.yml and write the result to docs/data/dashboard.json."""
import argparse
import datetime as dt
import decimal
import json
import os
import re
import sys
from pathlib import Path

import yaml

# Keys and metric names become file names, so only allow a conservative character set.
SAFE = re.compile(r"^[A-Za-z0-9_-]+$")
GENERIC_ERROR = "query failed (details in the Actions log)"


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


def run_query(conn, sql, max_rows, params=()):
    cur = conn.cursor()
    try:
        cur.execute(sql, params) if params else cur.execute(sql)
        cols = [d[0] for d in cur.description]
        rows = [[jsonable(v) for v in r] for r in cur.fetchmany(max_rows)]
    finally:
        cur.close()
    return cols, rows


def ts_key(ts):
    """File-name key of a history point, e.g. 2026-11-08T18:50:00+00:00 -> 20261108T185000Z."""
    return re.sub(r"[^0-9T]", "", ts[:19]) + "Z"


def dumps(obj):
    return json.dumps(obj, ensure_ascii=False, indent=1) + "\n"


def write_if_changed(path, text):
    """Write UTF-8 text with LF newlines, only when the content differs (no commit noise)."""
    data = text.replace("\r\n", "\n").encode("utf-8")
    if path.exists() and path.read_bytes() == data:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def warn(msg):
    print(f"::warning::{msg}", file=sys.stderr)


def rollback(conn):
    try:
        conn.rollback()
    except Exception:  # noqa: BLE001
        pass


def query_one(conn, kind, sql, key):
    """Run a detail SQL where every `?` receives the key; returns (columns, rows)."""
    params = (key,) * sql.count("?")
    if kind == "postgres":
        sql = sql.replace("?", "%s")
    return run_query(conn, sql, 1, params)


def format_title(template, name, key, values):
    try:
        return template.format_map(values) if template else f"{name} {key}"
    except (KeyError, IndexError, ValueError):
        return f"{name} {key}"


def build_details(conn, kind, name, spec, cols, rows, root, extra_keys=frozenset()):
    """Write one detail JSON per record key (rows' keys + extra_keys); delete files of other keys."""
    if not SAFE.match(name):
        warn(f"{name}: unsafe metric name, details skipped")
        return
    key_col = spec["key"]
    if key_col not in cols:
        warn(f"{name}: detail key column {key_col!r} not in result, details skipped")
        return
    idx = cols.index(key_col)
    titles = {}
    for r in rows:
        if r[idx] is None:
            continue
        key = str(r[idx])
        if not SAFE.match(key):
            warn(f"{name}: unsafe detail key skipped")
            continue
        titles[key] = format_title(spec.get("title"), name, key, dict(zip(cols, r)))
    for key in extra_keys:
        if SAFE.match(key) and key not in titles:
            titles[key] = format_title(spec.get("title"), name, key, {key_col: key})

    folder = root / name
    for key, title in titles.items():
        sections = []
        for sec in spec["sections"]:
            try:
                scols, srows = query_one(conn, kind, sec["sql"], key)
                sections.append({"title": sec["title"], "columns": scols,
                                 "row": srows[0] if srows else None, "error": None})
            except Exception as e:  # noqa: BLE001 - one failing card must not stop the rest
                warn(f"{name}/{key}/{sec['title']}: {e}")
                rollback(conn)
                sections.append({"title": sec["title"], "columns": [], "row": None, "error": GENERIC_ERROR})
        write_if_changed(folder / f"{key}.json",
                         dumps({"metric": name, "key": key, "title": title, "sections": sections}))
    if folder.is_dir():
        for path in folder.glob("*.json"):
            if path.stem not in titles:
                path.unlink()


def build_lists(conn, kind, name, spec, history, root, now):
    """Write the list file of the current history point, drop files of trimmed points.

    Returns the keys referenced by the retained list files (rows of the link column).
    """
    lst = spec["list"]
    if not SAFE.match(name):
        warn(f"{name}: unsafe metric name, lists skipped")
        return set()
    folder = root / name
    keep = {ts_key(h["ts"]) for h in history}
    key = ts_key(now)
    link = lst["link"]
    if key in keep:  # the current poll added a history point
        try:
            cols, rows = run_query(conn, lst["sql"], int(lst.get("max_rows", 50)))
            body = {"columns": cols, "rows": rows, "link": link, "error": None}
        except Exception as e:  # noqa: BLE001
            warn(f"{name}/{key}: {e}")
            rollback(conn)
            body = {"columns": [], "rows": [], "link": link, "error": GENERIC_ERROR}
        write_if_changed(folder / f"{key}.json", dumps(
            {"metric": name, "key": key, "title": format_title(lst.get("title"), name, key, {"ts": now}),
             "list": body}))
    linked = set()
    if folder.is_dir():
        for path in folder.glob("*.json"):
            if path.stem not in keep:
                path.unlink()
                continue
            body = json.loads(path.read_text(encoding="utf-8"))["list"]
            if link["key"] in body["columns"]:
                i = body["columns"].index(link["key"])
                linked |= {str(r[i]) for r in body["rows"] if r[i] is not None}
    return linked


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
    kind = cfg["database"].get("type", "sqlite")
    root = out.parent / "details"
    metrics = []
    list_jobs = []    # (metric config, entry): line metrics with detail.list
    detail_jobs = []  # (metric config, entry, cols, rows): metrics whose query succeeded

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
        spec = m.get("detail") or {}
        if "key" in spec:
            entry["detail"] = {"key": spec["key"]}
        elif "list" in spec:
            entry["detail"] = {"list": True}
        try:
            cols, rows = run_query(conn, m["sql"], int(m.get("max_rows", 500)))
            entry.update(columns=cols, rows=rows, updated=now, error=None)
            if mode == "append":
                hist = list(old.get("history", []))
                if rows:
                    hist.append({"ts": now, "values": dict(zip(cols, rows[0]))})
                entry["history"] = hist[-int(m.get("max_points", 500)):]
            if "key" in spec:
                detail_jobs.append((m, entry, cols, rows))
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
        if "list" in spec and mode == "append":
            list_jobs.append((m, entry))
        metrics.append(entry)

    # Detail work runs after all queries: lists first, so the order pages they link to can be generated too.
    extra = {}
    for m, entry in list_jobs:
        linked = build_lists(conn, kind, m["name"], m["detail"], entry["history"], root, now)
        extra.setdefault(m["detail"]["list"]["link"]["metric"], set()).update(linked)
    for m, entry, cols, rows in detail_jobs:
        build_details(conn, kind, m["name"], m["detail"], cols, rows, root,
                      frozenset(extra.get(m["name"], ())))

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
