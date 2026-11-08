# Order Drill-Down Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clicking a row in the `Latest orders` table opens a detail page with an Order card and a Customer card.

**Architecture:** `poll.py` runs per-row detail SQL (from an opt-in `detail` block in `config.yml`) and writes one JSON file per record under `docs/data/details/<metric>/<key>.json`. A generic `docs/detail.html` fetches and renders it. `index.html` turns the key cell into a link.

**Tech Stack:** Python 3.10+ stdlib + pyyaml, sqlite (demo), vanilla JS, `unittest`.

**Spec:** `specs/2026-11-08-order-drilldown-design.md`

## Global Constraints

- No new dependencies beyond `pyyaml`; tests use stdlib `unittest` only.
- Everything written is English (code, comments, strings, docs).
- DB access stays read-only; DB error text never goes into public JSON (generic message, details via `::warning::` to stderr).
- Keys and metric names used in file paths must match `^[A-Za-z0-9_-]+$`.
- DB data is written to the DOM with `textContent` only.
- Detail files contain no timestamp and are written only when content differs (use `write_bytes` with `\n` so output is identical on Windows and Linux).
- `detail` is opt-in per metric; metrics without it behave exactly as before.
- Commit messages end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Run `git pull --rebase origin main` before any push (the workflow bot commits to `main`).

## Review Focus

- Key `../x` or containing `/`, `\`, spaces → skipped with a warning, nothing written outside the details dir (Task 2).
- Key value `NULL` in a row → row skipped, no file `None.json` (Task 2).
- Order with `customer_id` NULL → Customer section has `row: null`, page shows "No data", no crash (Tasks 2, 3).
- Main metric query fails on a later poll → existing detail files are kept, not deleted (Task 2).
- One section SQL fails → only that section gets `error`, other section and other rows still written (Task 2).
- `detail.html` opened with missing or malicious `metric`/`key` (`?key=../../x`, no params) → friendly message, no fetch of arbitrary paths (Task 3).

---

### Task 1: Customers in the demo DB + test harness

**Files:**
- Modify: `scripts/demo_db.py`
- Create: `scripts/smoke_test.py`

**Interfaces:**
- Produces: demo DB tables `customers(id INTEGER PRIMARY KEY, name TEXT, email TEXT, country TEXT, segment TEXT)` (40 rows) and `orders.customer_id INTEGER` (never NULL for generated orders).
- Produces (test helpers in `smoke_test.py`, used by Task 2): `run(script: str, *args: str, env: dict) -> subprocess.CompletedProcess` (runs `sys.executable scripts/<script>`, cwd = repo root, captures output), and `class PollCase(unittest.TestCase)` whose `setUp` creates a temp dir `self.tmp`, sets `self.env = {**os.environ, "DB_DSN": str(self.tmp/"t.sqlite")}`, runs `demo_db.py --path <DB_DSN>`, and defines `self.poll(config=None) -> CompletedProcess` running `poll.py --config <config or repo config.yml> --out <self.tmp>/data/dashboard.json`.

- [ ] **Step 1: Write the failing test** in `scripts/smoke_test.py`: `test_demo_db_has_customers` opens `self.tmp/t.sqlite` and asserts `SELECT COUNT(*) FROM customers` == 40 and `SELECT COUNT(*) FROM orders WHERE customer_id IS NULL` == 0 and every `orders.customer_id` exists in `customers.id`. Include the helpers above and `if __name__ == "__main__": unittest.main()`.
- [ ] **Step 2: Run** `python scripts/smoke_test.py -v` — Expected: FAIL (`no such table: customers`).
- [ ] **Step 3: Implement** in `demo_db.py`: create `customers`, seed 40 fake customers when empty (names from a small built-in list, `email` = `<slug>@example.com`, `country`, `segment` in `SMB|Enterprise|Consumer`), add `customer_id` to the `orders` `CREATE TABLE`, and give `new_order` a random existing customer id (load ids once in `main`). Update the module docstring and printed summary.
- [ ] **Step 4: Run** `python scripts/smoke_test.py -v` — Expected: PASS.
- [ ] **Step 5: Commit** `scripts/demo_db.py scripts/smoke_test.py` — "feat: add customers to demo DB and smoke test harness".

### Task 2: Detail generation in `poll.py` and config

**Files:**
- Modify: `scripts/poll.py`, `config.yml`
- Test: `scripts/smoke_test.py`

**Interfaces:**
- Consumes: `PollCase` helpers from Task 1.
- Produces in `poll.py`:
  - `SAFE = re.compile(r"^[A-Za-z0-9_-]+$")`
  - `run_query(conn, sql, max_rows, params=()) -> tuple[list[str], list[list]]` (new optional `params`)
  - `write_if_changed(path: Path, text: str) -> None` (UTF-8 bytes, `\n` newlines, skip write when identical)
  - `build_details(conn, kind: str, name: str, spec: dict, cols: list[str], rows: list[list], root: Path) -> None` — `root` is `<out dir>/details`.
- Produces: `dashboard.json` metric gains `"detail": {"key": "<column>"}` when configured. Detail file format per spec: `{"metric","key","title","sections":[{"title","columns","row","error"}]}`.

- [ ] **Step 1: Write failing tests** in `PollCase` (using a test config that copies `config.yml` and is expected to contain the `detail` block on `latest_orders`):
  - `test_detail_files_written`: after one poll, `data/details/latest_orders/` has 10 `*.json`; each parses with 2 sections titled `Order` and `Customer`, `error` null, `row` non-null; `dashboard.json` metric `latest_orders.detail == {"key": "id"}`.
  - `test_second_poll_leaves_details_unchanged`: file bytes and mtimes of all detail files identical after a second poll.
  - `test_stale_details_removed`: run `demo_db.py --path <db> --tick 5`, poll; files exist for exactly the current 10 ids and the previous ids that dropped out are gone.
  - `test_unsafe_key_rejected`: write a temp config whose `latest_orders` SQL returns `'../evil' AS id`; poll; assert no file outside `data/details/latest_orders/`, directory empty, exit code 0.
  - `test_null_key_skipped`: SQL returns `NULL AS id`; no `None.json`.
  - `test_missing_customer_gives_null_row`: SQL for the Customer section is joined on a non-existent id (use a test config whose section SQL matches no row); that section has `"row": null`, `"error": null`.
  - `test_failed_section_isolated`: Customer section SQL references a missing table; Order section still has data, Customer has `error == "query failed (details in the Actions log)"`, and stderr contains `::warning::`.
  - `test_main_query_failure_keeps_details`: poll once, then poll with a config whose `latest_orders` SQL is invalid; previously written detail files still exist.
- [ ] **Step 2: Run** `python scripts/smoke_test.py -v` — Expected: FAIL (no detail files, no `detail` key).
- [ ] **Step 3: Implement** `config.yml`: add to `latest_orders` the `detail` block from the spec (key `id`; title `"Order {id}"`; sections `Order` = `SELECT id, created_at, status, region, amount FROM orders WHERE id = ?`, `Customer` = `SELECT c.name, c.email, c.country, c.segment FROM customers c JOIN orders o ON o.customer_id = c.id WHERE o.id = ?`), and change that metric's SQL to also be unaffected by the new column (keep selecting the same 5 columns). Implement the `poll.py` pieces above. Approach: in `main()` call `build_details` after a successful metric query only; it maps `?` to `%s` when `kind == "postgres"`, passes `(key,) * sql.count("?")`, formats the title with `str.format_map` falling back to `"<name> <key>"` on `KeyError`/`IndexError`, skips and warns on unsafe/`None` keys or a `key` column missing from `cols`, wraps each section in its own `try` (generic error text, `::warning::` to stderr, `conn.rollback()` guarded as in `main`), then deletes files in `root/<name>/` not in the current key set. Also validate `name` with `SAFE`; if it fails, skip details with a warning. `connect()` result `kind` must be available in `main` (read `cfg["database"].get("type","sqlite")`).
- [ ] **Step 4: Run** `python scripts/smoke_test.py -v` — Expected: all PASS.
- [ ] **Step 5: Commit** `scripts/poll.py config.yml scripts/smoke_test.py` — "feat: generate per-record detail JSON".

### Task 3: UI — clickable rows and `detail.html`

**Files:**
- Modify: `docs/index.html`
- Create: `docs/detail.html`

**Interfaces:**
- Consumes: `metric.detail.key` in `dashboard.json`; detail file format from Task 2 at `data/details/<metric>/<key>.json`.
- Produces: link format `detail.html?metric=<encodeURIComponent(name)>&key=<encodeURIComponent(value)>`.

- [ ] **Step 1: `index.html`** — in `renderTable(body, m)`, when `m.detail` is set, find the index of `m.detail.key` in `m.columns` and render that cell's content as an `<a>` (`el('a')`, `href` built as above, text via `textContent`); skip the link for `null`/non-matching values. Add a `tr.clickable` style (pointer cursor, hover background using existing CSS variables) and make a click anywhere on the row follow the link.
- [ ] **Step 2: `detail.html`** — copy the `:root`/dark-mode tokens and card/header styles from `index.html` (single file, no build). Behavior: read `metric` and `key` from `URLSearchParams`; if either fails `/^[A-Za-z0-9_-]+$/` show "Invalid link" and do not fetch; otherwise `fetch('data/details/'+metric+'/'+key+'.json', {cache:'no-store'})`; on 404 show "This record is no longer available (it may have dropped out of the table)"; on success set `document.title` and `<h1>` to `title`, render each section as a card with a two-column key/value list from `columns`/`row` (all `textContent`); `row === null` → "No data"; `error` → badge as in `index.html`; add a "← Back to dashboard" link to `index.html`.
- [ ] **Step 3: Verify in a browser** — run `python scripts/demo_db.py --path demo.sqlite; python scripts/poll.py; python -m http.server -d docs 8000`. Expected: in `http://localhost:8000` clicking an order id opens the detail page with Order and Customer cards and the back link works; `detail.html?metric=latest_orders&key=999999` shows the not-available message; `detail.html?key=../../x&metric=a` and `detail.html` (no params) show "Invalid link"; console has no errors; dark mode and a narrow window look correct.
- [ ] **Step 4: Commit** `docs/index.html docs/detail.html` — "feat: clickable order rows and detail page".

### Task 4: Workflow, docs, and release

**Files:**
- Modify: `.github/workflows/dashboard.yml`, `CLAUDE.md`, `MIGRATION.md`, `README.md`

- [ ] **Step 1: Workflow** — change `git add docs/data/dashboard.json` to `git add -A docs/data`; add `docs/detail.html` to the push `paths`; add a step before "Poll": run `.venv/bin/python scripts/smoke_test.py`.
- [ ] **Step 2: Docs** — `CLAUDE.md`: document the optional `detail` field in the `dashboard.json` contract, the detail file format, the `detail.html` requirements, and a privacy rule ("never point `detail` at real personal data on public Pages"). `MIGRATION.md`: add the privacy item to the Phase 3 prerequisites and mark the drill-down as done under status. `README.md`: add the `detail` block to the Config section. Keep everything English.
- [ ] **Step 3: Verify locally** — `python scripts/smoke_test.py -v` passes; `python -c "import yaml;yaml.safe_load(open('.github/workflows/dashboard.yml'))"` succeeds.
- [ ] **Step 4: Commit** the four files — "feat: ship order drill-down (workflow, docs)".
- [ ] **Step 5: Release** — `git pull --rebase origin main && git push origin main`; wait for the `dashboard` run, expected green; open `https://oademirkol.github.io/dashboard/`, click an order, confirm the detail page loads from Pages.

---
Spec coverage: data model (T1), config contract and poll behavior (T2), JSON contract change (T2), UI (T3), workflow + privacy (T4), testing (T1–T3 + manual). Out-of-scope items are not planned.
