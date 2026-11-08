# Migration plan: claude.ai chat → Claude Code (VS Code)

> Language policy: all code, comments, docs and plans in this repo are written and maintained in English (see `CLAUDE.md`).

## 1. Current status
| Item | Status |
|---|---|
| Phase 0–1: config, `poll.py`, `demo_db.py`, `index.html`, workflow, README | Done; tested locally with the demo DB (poll ×2 → 2 history points, 4 cards rendered in headless Chrome) |
| `dashboard.yml` workflow | YAML is valid, **not yet run on GitHub** |
| postgres / mssql connection | Present in code, **untested** |
| Order drill-down (trend point → list → order + customer) | Done on branch `feature/order-drilldown`; tested locally with `scripts/smoke_test.py` and headless Chrome |
| Git | Project files are **not committed yet** (only `.gitattributes` is tracked); remote `origin` exists |

## 2. Moving to Claude Code (one-time)
1. The project is open in VS Code at `Dashboard/dashboard` (Open Folder). Remote: `https://github.com/oademirkol/dashboard.git`.
2. Install the Claude Code extension in VS Code; run `claude` in the integrated terminal at the project root.
3. `CLAUDE.md` is read automatically (architecture, contract, rules, commands are there).
4. First see it work locally ("Try it locally" in the README), then the first prompt: `Apply MIGRATION.md Phase 2 and verify the acceptance criteria.`
5. When a phase is done, move on: `Go to Phase 3.`

**Windows (PowerShell) equivalents:**
```powershell
python -m venv .venv; .\.venv\Scripts\Activate.ps1; pip install -r requirements.txt
python scripts/demo_db.py; python scripts/poll.py
python scripts/demo_db.py --tick 5; python scripts/poll.py
python -m http.server -d docs 8000
```
(The workflow runs on a Linux runner, so the `.venv/bin/...` paths there are correct. A Windows self-hosted runner would need `.venv\Scripts\`.)

## 3. Phases

### Phase 0 — Preparation
- `git init`, `.gitignore`, create an empty GitHub repo (in the company org, **private**).
  - **Note:** GitHub Pages on a private repo is only available on paid plans such as Team/Enterprise Cloud; on a personal/free plan the repo must be **public** for Pages. Decide repo visibility now, based on the Pages plan.
- Python 3.10+ and a venv.
- **First commit:** `scripts/`, `docs/`, `config.yml`, `.github/`, `README.md`, `CLAUDE.md`, `MIGRATION.md`, `requirements.txt`, `.gitignore` must be committed (currently only `.gitattributes` is tracked).
- Acceptance: `python scripts/poll.py --help` runs without errors; `git ls-files` lists the project files.

### Phase 1 — Finish the PoC locally (with the demo DB) — DONE
- Written: `scripts/demo_db.py`, `docs/index.html`, `requirements.txt`, `.github/workflows/dashboard.yml`, `README.md`. Acceptance criteria were verified as below; they can be re-run in Claude Code as a regression check.
- Acceptance:
  1. `python scripts/demo_db.py && python scripts/poll.py` → `docs/data/dashboard.json` is created, all 4 metrics have `error: null`.
  2. `python scripts/demo_db.py --tick 5 && python scripts/poll.py` → `orders_trend.history` grows to 2 points.
  3. `python -m http.server -d docs 8000` → all 4 cards render, no console errors.
  4. Changing the SQL in `config.yml` updates the page without any code change.

### Phase 2 — Move to GitHub (still the demo DB)
- Push to the repo. Settings → Pages → **Source: GitHub Actions**.
- Repo variable: `RUNNER_LABEL` (`ubuntu-latest` if empty). Do **not** define the `DB_DSN` secret yet (stay in demo mode).
- Actions → `dashboard` → **Run workflow**.
- Checklist:
  - Settings → Environments → `github-pages`: does the deployment branch rule allow `main`?
  - If `main` has branch protection, allow the bot to push `docs/data/dashboard.json` (otherwise the push step fails).
  - The bot commit is pushed with `GITHUB_TOKEN`, so it does not trigger a new workflow run (no loop); the push trigger only watches `config.yml`, `docs/index.html`, `scripts/**` and the workflow file anyway.
- In demo mode the workflow regenerates the DB from scratch on every run (`--tick` is not called), so the data stays the same, but `history` still gains a new timestamped point per run.
- Acceptance: the dashboard opens at the Pages URL; after 15 minutes the scheduled run has made `history` in `docs/data/dashboard.json` one point longer and updated `generated_at`.

### Phase 3 — Connect to the company database
0. **Privacy prerequisite:** `detail` pages publish record-level data. Before enabling `detail` on real data, make sure no personal data (names, emails, ...) reaches public Pages: use anonymised/aggregate fields or access-controlled Pages.
1. Request a **read-only user** for the DB (only the required tables/views).
2. `config.yml` → `database.type` (`postgres` / `mssql`); enable the matching driver in `requirements.txt` (`psycopg2-binary`, or `pyodbc` + the ODBC driver installed on the runner).
3. Add the `DB_DSN` secret (e.g. postgres: `host=... dbname=... user=... password=...`).
4. Set `RUNNER_LABEL=self-hosted` (or the company label); verify network access from the runner to the DB.
5. Translate the example SQL to your own schema and SQL dialect (`datetime('now', ...)` is sqlite-specific; postgres: `NOW() - INTERVAL '1 hour'`, mssql: `DATEADD(hour, -1, GETDATE())`).
6. The read-only guarantee depends on the driver: postgres uses `readonly=True` in code; mssql is not enforced in code → add `ApplicationIntent=ReadOnly` to the DSN and restrict the DB user to `db_datareader`; for Oracle, add a new block to `connect()` (and use a read-only user).
- Acceptance: workflow is green, the dashboard shows real data, all `error` fields are `null`.

### Phase 4 — Hardening
- **Access:** is Pages access-controlled on the company plan (GitHub Enterprise Cloud)? If not, the page is public → aggregate data only.
- **Repo growth:** every poll is a commit. Keep `max_points` low; if it grows, move `dashboard.json` to a separate `data` branch (force-push).
- **CDN:** if the company network blocks jsdelivr, download Chart.js into `docs/vendor/` and load it locally.
- **Monitoring:** a failed poll emits a workflow warning (`::warning::` is already there); add notifications if needed.
- **Cron delay:** the GitHub schedule can drift by a few minutes; showing `generated_at` on the dashboard is enough.
- **Self-hosted runner security:** do not use a self-hosted runner on a public repo (fork PRs could run code on the company network); run the runner under a dedicated account with minimal privileges.
- **Secret rotation:** rotate the `DB_DSN` password regularly; the DB user should only have access to the required tables/views.
- **JSON size:** `dashboard.json` grows with `max_points` × number of metrics; if it exceeds a few MB, move it to the `data` branch.
- **Tests:** add a small smoke test (`demo_db.py` → `poll.py` ×2 → `history` length 2, all `error` null) and run it in CI.

## 4. Open questions (to settle before Phase 3)
1. Which DB (PostgreSQL / MSSQL / Oracle…)? If Oracle, a new block is added to `connect()`.
2. Which metrics, and what poll frequency? (Actions cron allows 5 minutes at the fastest.)
3. Can Pages be access-controlled?
4. What is the self-hosted runner's label, and how are Python/ODBC installed on it?
