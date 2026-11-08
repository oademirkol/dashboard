# dbdash

A config-driven dashboard that polls a DB periodically and shows the result on a static page (GitHub Actions + Pages).

```
DB → scripts/poll.py (Actions cron) → docs/data/dashboard.json → docs/index.html → Pages
```

## Try it locally
```bash
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
python scripts/demo_db.py            # demo data
python scripts/poll.py               # docs/data/dashboard.json
python scripts/demo_db.py --tick 5 && python scripts/poll.py   # 2nd point on the trend chart
python -m http.server -d docs 8000   # http://localhost:8000
```

## Config (`config.yml`)
Each metric: `name`, `title`, `type` (`stat` | `line` | `bar` | `table`), `sql`. Optional: `mode` (`snapshot`/`append`), `max_points`, `max_rows`, `wide`.
- `stat`: the columns of the first row become value cards.
- `bar`: first column is the label, the others are values.
- `line`: defaults to `append`; on every poll the **single-row** query result is appended to the history with a timestamp.
- `table`: the result table.

## GitHub setup
1. Push the repo. Settings → Pages → Source: **GitHub Actions**.
2. (Company) Settings → Variables: `RUNNER_LABEL=self-hosted`.
3. (Real DB) Settings → Secrets: `DB_DSN`; set `config.yml` → `database.type`; enable the driver in `requirements.txt`.
4. Actions → `dashboard` → Run workflow.

If `DB_DSN` is not set, the workflow runs against the demo DB.

## Notes
- The DB connection is read-only; still, use a read-only DB user.
- Pages may be publicly accessible: fetch only summary data.
- If `main` has branch protection, allow the bot to push `docs/data/dashboard.json`.
- Chart.js is loaded from jsdelivr; if the company network blocks it, download it to `docs/vendor/` and change the `<script src>` in `index.html`.
- SQL dialects differ per DB (the examples in `config.yml` are sqlite).
