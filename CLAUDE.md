# dbdash — DB poll → static dashboard (GitHub Actions + Pages)

Goal: a config-driven PoC that periodically polls a company SQL database, writes the result to
`docs/data/dashboard.json`, and shows it on a static GitHub Pages site. Plan: `MIGRATION.md`.

## Language policy
The user writes to Claude in Turkish, but **everything produced and maintained in this repo is in English**:
code, comments, identifiers, log/error/UI strings, config comments, commit messages, and all docs
(`README.md`, `MIGRATION.md`, `CLAUDE.md`, plans). Reply to the user in Turkish in chat only. When touching
an existing file that still has Turkish text, translate it.

## Architecture
```
DB --(self-hosted runner, cron)--> scripts/poll.py --> docs/data/dashboard.json --> docs/index.html (Chart.js) --> Pages
```
- Single config: `config.yml` (SQL + chart type). Changing SQL/charts requires no code change.
- History (trend) data lives in the `history` field of `dashboard.json` and is committed to the repo.
- No server, database, or build tool: Python + pyyaml, vanilla JS + Chart.js in the browser.

## Status
All PoC files are written and were **tested locally with the demo SQLite DB** (poll twice → `history` grows,
4 cards + 2 charts render without errors in headless Chrome).
- [x] `config.yml`, `scripts/poll.py`, `scripts/demo_db.py`, `docs/index.html`, `requirements.txt`, `README.md`, `.gitignore`
- [x] `.github/workflows/dashboard.yml` — valid YAML, **not yet run on GitHub**
- [ ] Real DB (postgres/mssql) connection — present in code, **untested**
- [ ] Next: `MIGRATION.md` Phase 2 (move to GitHub), then Phase 3 (company DB)
- [ ] Project files are not committed yet (only `.gitattributes` is tracked)

Known limits: the `orders_trend` example plots two series with different scales (count, average amount) on one axis;
for real metrics use series on the same scale or split them into separate cards.

## dashboard.json contract (produced by poll.py, read by index.html)
```json
{"title": "...", "generated_at": "ISO-UTC", "refresh_seconds": 60,
 "metrics": [{"name": "id", "title": "...", "type": "stat|line|bar|table",
   "mode": "snapshot|append", "wide": false,
   "columns": ["a","b"], "rows": [[1,2]],
   "history": [{"ts": "ISO-UTC", "values": {"a": 1, "b": 2}}],
   "updated": "ISO-UTC|null", "error": null}]}
```
`history` exists only on `mode: append` metrics. If `error` is set, the last successful data is shown.

## index.html requirements
- Single file, vanilla JS, Chart.js (jsdelivr CDN; show a warning in the card if the CDN fails to load).
- `fetch('data/dashboard.json', {cache:'no-store'})`; refresh every `refresh_seconds`; do not redraw if `generated_at` is unchanged.
- `stat`: each column of the first row is a value card (title = column name).
- `table`: columns/rows table.
- `bar`: first column is the label, other columns are datasets.
- `line`: if `history` exists, x = `ts` (local time) and each `values` key is a series; otherwise x = first column.
- `wide: true` → full width in the grid. Show a badge on the card if `error` is set.
- Light/dark theme (`prefers-color-scheme`), single column on mobile, `Chart.defaults.color` matches the theme.
- Write DB data to the DOM with `textContent` (never innerHTML).

## Workflow requirements (`dashboard.yml`)
- Triggers: `schedule` (`*/15 * * * *`), `workflow_dispatch`, `push` (config.yml, docs/index.html, scripts/**).
- `permissions`: contents: write, pages: write, id-token: write. `concurrency: dashboard`, cancel-in-progress: false.
- Job `build`: `runs-on: ${{ vars.RUNNER_LABEL || 'ubuntu-latest' }}` (`self-hosted` for the company).
  - job env `DB_DSN: ${{ secrets.DB_DSN }}`; if `DB_DSN` is empty run `scripts/demo_db.py` (demo mode).
  - `python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt`, then `.venv/bin/python scripts/poll.py`.
  - If `docs/data/dashboard.json` changed: commit + `git pull --rebase` + push (to persist history).
  - `actions/upload-pages-artifact` (path: docs).
- Job `deploy`: `needs: build`, `runs-on: ubuntu-latest`, `environment: github-pages`, `actions/deploy-pages`.

## Rules
- DB connection is read-only (sqlite `mode=ro`, postgres `readonly=True`); no writes.
- No secrets in the repo: connection info only via the `DB_DSN` secret.
- Never write DB error text into the public JSON (poll.py already writes a generic message; details go to the Actions log).
- Pages output may be public: fetch only summary/aggregate data, never raw records.
- Do not add new dependencies (other than pyyaml) — keep the PoC simple. For a new DB type add an `if` in `poll.py > connect()`.

## Commands
```bash
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
python scripts/demo_db.py            # demo DB (once)
python scripts/poll.py               # produces docs/data/dashboard.json
python scripts/demo_db.py --tick 5   # add new data, then run poll again → history grows
python -m http.server -d docs 8000   # http://localhost:8000 (fetch does not work over file://)
```
Windows (PowerShell): `python -m venv .venv; .\.venv\Scripts\Activate.ps1`, then the same `python scripts/...` commands.
