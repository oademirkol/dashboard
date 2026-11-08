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


if __name__ == "__main__":
    unittest.main()
