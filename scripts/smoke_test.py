#!/usr/bin/env python3
"""Smoke tests for the demo DB, poll.py and the drill-down detail files (stdlib only).

Run: python scripts/smoke_test.py -v
"""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(script, *args, env=None):
    """Run scripts/<script> with the current interpreter from the repo root."""
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / script), *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


class PollCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.db = self.tmp / "t.sqlite"
        self.env = {**os.environ, "DB_DSN": str(self.db)}
        res = run("demo_db.py", "--path", str(self.db), env=self.env)
        self.assertEqual(res.returncode, 0, res.stderr)

    def tick(self, n):
        res = run("demo_db.py", "--path", str(self.db), "--tick", str(n), env=self.env)
        self.assertEqual(res.returncode, 0, res.stderr)

    def poll(self, config=None):
        return run(
            "poll.py",
            "--config", str(config or ROOT / "config.yml"),
            "--out", str(self.tmp / "data" / "dashboard.json"),
            env=self.env,
        )


class DemoDbTest(PollCase):
    def test_demo_db_has_customers(self):
        conn = sqlite3.connect(self.db)
        try:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0], 40)
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM orders WHERE customer_id IS NULL").fetchone()[0], 0
            )
            orphans = conn.execute(
                "SELECT COUNT(*) FROM orders o LEFT JOIN customers c ON c.id = o.customer_id WHERE c.id IS NULL"
            ).fetchone()[0]
            self.assertEqual(orphans, 0)
        finally:
            conn.close()


sys.path.insert(0, str(ROOT / "scripts"))
import poll  # noqa: E402
import yaml  # noqa: E402

GENERIC_ERROR = "query failed (details in the Actions log)"


class DetailCase(PollCase):
    """Helpers for tests that inspect the generated detail files."""

    @property
    def details(self):
        return self.tmp / "data" / "details"

    def variant(self, mutate):
        """Write a copy of config.yml modified by mutate(cfg) and return its path."""
        cfg = yaml.safe_load((ROOT / "config.yml").read_text(encoding="utf-8"))
        mutate(cfg)
        path = self.tmp / "variant.yml"
        path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
        return path

    @staticmethod
    def metric(cfg, name):
        return next(m for m in cfg["metrics"] if m["name"] == name)

    def no_list(self):
        return self.variant(lambda cfg: self.metric(cfg, "orders_trend").pop("detail"))

    def load(self, *parts):
        return json.loads(self.details.joinpath(*parts).read_text(encoding="utf-8"))

    def dashboard(self):
        return json.loads((self.tmp / "data" / "dashboard.json").read_text(encoding="utf-8"))

    def metric_out(self, name):
        return next(m for m in self.dashboard()["metrics"] if m["name"] == name)

    def table_ids(self):
        return {str(r[0]) for r in self.metric_out("latest_orders")["rows"]}

    def files(self, metric):
        folder = self.details / metric
        return {p.stem for p in folder.glob("*.json")} if folder.is_dir() else set()


class OrderDetailTest(DetailCase):
    def test_detail_files_written(self):
        res = self.poll(self.no_list())
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.files("latest_orders"), self.table_ids())
        self.assertEqual(len(self.table_ids()), 10)
        for key in self.table_ids():
            d = self.load("latest_orders", f"{key}.json")
            self.assertEqual([s["title"] for s in d["sections"]], ["Order", "Customer"])
            self.assertEqual(d["title"], f"Order {key}")
            for s in d["sections"]:
                self.assertIsNone(s["error"])
                self.assertIsNotNone(s["row"])
        self.assertEqual(self.metric_out("latest_orders")["detail"], {"key": "id"})

    def test_second_poll_leaves_details_unchanged(self):
        self.poll()
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in (self.details / "latest_orders").glob("*.json")}
        self.assertTrue(before)
        self.assertEqual(self.poll().returncode, 0)
        for p, state in before.items():
            self.assertEqual((p.read_bytes(), p.stat().st_mtime_ns), state)

    def test_stale_details_removed(self):
        cfg = self.no_list()
        self.poll(cfg)
        old = self.table_ids()
        self.tick(5)
        self.poll(cfg)
        new = self.table_ids()
        self.assertNotEqual(old, new)
        self.assertEqual(self.files("latest_orders"), new)

    def test_unsafe_key_rejected(self):
        def mutate(cfg):
            self.metric(cfg, "orders_trend").pop("detail")
            self.metric(cfg, "latest_orders")["sql"] = (
                "SELECT '../evil' AS id, 'x' AS created_at, 'EU' AS region, 1.0 AS amount, 'paid' AS status"
            )

        res = self.poll(self.variant(mutate))
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.files("latest_orders"), set())
        self.assertEqual([p for p in self.tmp.rglob("*") if "evil" in p.name], [])
        self.assertIn("::warning::", res.stderr)

    def test_null_key_skipped(self):
        def mutate(cfg):
            self.metric(cfg, "orders_trend").pop("detail")
            self.metric(cfg, "latest_orders")["sql"] = (
                "SELECT NULL AS id, 'x' AS created_at, 'EU' AS region, 1.0 AS amount, 'paid' AS status"
            )

        self.assertEqual(self.poll(self.variant(mutate)).returncode, 0)
        self.assertEqual(self.files("latest_orders"), set())

    def test_missing_customer_gives_null_row(self):
        def mutate(cfg):
            self.metric(cfg, "orders_trend").pop("detail")
            detail = self.metric(cfg, "latest_orders")["detail"]
            detail["sections"][1]["sql"] = "SELECT name FROM customers WHERE id = -1 AND ? IS NOT NULL"

        self.assertEqual(self.poll(self.variant(mutate)).returncode, 0)
        key = next(iter(self.table_ids()))
        customer = self.load("latest_orders", f"{key}.json")["sections"][1]
        self.assertIsNone(customer["row"])
        self.assertIsNone(customer["error"])

    def test_failed_section_isolated(self):
        def mutate(cfg):
            self.metric(cfg, "orders_trend").pop("detail")
            self.metric(cfg, "latest_orders")["detail"]["sections"][1]["sql"] = "SELECT name FROM nope WHERE id = ?"

        res = self.poll(self.variant(mutate))
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("::warning::", res.stderr)
        key = next(iter(self.table_ids()))
        order, customer = self.load("latest_orders", f"{key}.json")["sections"]
        self.assertIsNone(order["error"])
        self.assertIsNotNone(order["row"])
        self.assertEqual(customer["error"], GENERIC_ERROR)
        self.assertIsNone(customer["row"])

    def test_main_query_failure_keeps_details(self):
        self.poll(self.no_list())
        before = self.files("latest_orders")
        self.assertTrue(before)

        def mutate(cfg):
            self.metric(cfg, "orders_trend").pop("detail")
            self.metric(cfg, "latest_orders")["sql"] = "SELECT * FROM does_not_exist"

        self.assertEqual(self.poll(self.variant(mutate)).returncode, 0)
        self.assertEqual(self.files("latest_orders"), before)


class TrendListTest(DetailCase):
    def test_ts_key(self):
        self.assertEqual(poll.ts_key("2026-11-08T18:50:00+00:00"), "20261108T185000Z")

    def test_trend_list_written(self):
        self.assertEqual(self.poll().returncode, 0)
        history = self.metric_out("orders_trend")["history"]
        key = poll.ts_key(history[0]["ts"])
        d = self.load("orders_trend", f"{key}.json")
        self.assertEqual(d["list"]["link"], {"metric": "latest_orders", "key": "id"})
        self.assertIsNone(d["list"]["error"])
        self.assertEqual(d["list"]["columns"][0], "id")
        self.assertEqual(self.metric_out("orders_trend")["detail"], {"list": True})

    def test_list_ids_have_order_details(self):
        self.tick(8)
        self.assertEqual(self.poll().returncode, 0)
        ids = set()
        for key in self.files("orders_trend"):
            ids |= {str(r[0]) for r in self.load("orders_trend", f"{key}.json")["list"]["rows"]}
        self.assertGreater(len(ids), 10)
        self.assertLessEqual(ids, self.files("latest_orders"))

    def test_list_files_follow_history(self):
        def mutate(cfg):
            self.metric(cfg, "orders_trend")["max_points"] = 2

        cfg = self.variant(mutate)
        for _ in range(3):
            self.tick(1)
            self.assertEqual(self.poll(cfg).returncode, 0)
            time.sleep(1.1)  # point keys have one-second resolution
        kept = {poll.ts_key(h["ts"]) for h in self.metric_out("orders_trend")["history"]}
        self.assertEqual(len(kept), 2)
        self.assertEqual(self.files("orders_trend"), kept)
        ids = set(self.table_ids())
        for key in kept:
            ids |= {str(r[0]) for r in self.load("orders_trend", f"{key}.json")["list"]["rows"]}
        self.assertEqual(self.files("latest_orders"), ids)

    def test_empty_list(self):
        def mutate(cfg):
            self.metric(cfg, "orders_trend")["detail"]["list"]["sql"] = "SELECT id FROM orders WHERE 1 = 0"

        self.assertEqual(self.poll(self.variant(mutate)).returncode, 0)
        key = poll.ts_key(self.metric_out("orders_trend")["history"][0]["ts"])
        d = self.load("orders_trend", f"{key}.json")
        self.assertEqual(d["list"]["rows"], [])
        self.assertIsNone(d["list"]["error"])

    def test_failed_list_isolated(self):
        def mutate(cfg):
            self.metric(cfg, "orders_trend")["detail"]["list"]["sql"] = "SELECT id FROM nope"

        res = self.poll(self.variant(mutate))
        self.assertEqual(res.returncode, 0, res.stderr)
        key = poll.ts_key(self.metric_out("orders_trend")["history"][0]["ts"])
        d = self.load("orders_trend", f"{key}.json")
        self.assertEqual(d["list"]["error"], GENERIC_ERROR)
        self.assertEqual(d["list"]["rows"], [])
        self.assertEqual(self.files("latest_orders"), self.table_ids())


if __name__ == "__main__":
    unittest.main()
