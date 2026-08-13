# HANDOFF — Hospital Admin Manager Suite ("Patient Experience OS")

> **Read this first** if you are a new chat session or a new developer.
> Everything below is verified fact as of 2026-08-13. The repo is the source of truth:
> **https://github.com/Hcarepro2026/hositalsuite** (branch `main`).

---

## 0. The founder & how to work with them

- **Zero-tech, zero-budget solo founder** (Nigeria, Lagos timezone). Non-technical language only.
- Standing instructions: (1) **always end with the pending-features menu** so they can choose;
  (2) **ROUND UP** (stop & summarize cleanly) whenever tokens run low, work slows, or quality risks degrading.
- They deploy-test via screenshots from **Render** and **Arena** — expect screenshots, diagnose logs patiently.
- GitHub pushes: repo is theirs. A classic PAT was used historically (`github_pat`/`ghp_` flow); if it fails,
  guide them to create a fresh 7-day PAT (repo scope) at https://github.com/settings/tokens and push with
  `git push https://Hcarepro2026:<TOKEN>@github.com/Hcarepro2026/hositalsuite.git main`.

## 1. Where things live

| What | Where |
|---|---|
| Code | this repo (`app/` Flask monolith, `tests/`, `loadtest/`) |
| Live production | **https://hospital-suite.onrender.com** (Render free web service `hospital-suite`) |
| Production DB | Supabase project ref `zhhdhfllypkzvmukilwt` — **Session pooler** URL (NOT the `db.` direct host; it is IPv6-unreachable from Render). Format: `postgresql://postgres.zhhdhfllypkzvmukilwt:<pw-%40-encoded>@aws-0-<region>.pooler.supabase.com:5432/postgres?sslmode=require`. Founder's DB password contains `@` → must be `%40`. |
| Workspace preview | this sandbox, port 8077, started with `bash start.sh` (SQLite at `data/app.db`, demo-seeded) |
| Docs | `README.md`, `ROADMAP.md` (gap review + waves), `DEPLOYMENT_GUIDE.md` (founder-proof), `LOAD_TEST_REPORT.md` |

### Sandbox quirks (Arena workspace)
- **pip packages and apt installs (PostgreSQL) are wiped between messages** — reinstall with
  `pip3 install -r requirements.txt` (and `sudo apt-get install -y postgresql` if Postgres needed) at session start.
- Only files under `/home/user` persist. The SQLite demo DB persists.
- `pkill -f` will kill YOUR OWN shell if the pattern string appears in your command — use the
  bracket trick: `pkill -f "python run[.]py"`.
- Sandbox has web-only egress: it **cannot** open TCP to Supabase (matches Render's earlier IPv6 failure pattern).
  Verify DB compatibility with **local** PostgreSQL 17 instead (`sudo service postgresql start`,
  user `hms` / pw `hms_test_pw`, dbs `hms_test`, `hms_load` — recreate if wiped).

## 2. Production-critical knowledge (do not regress)

- **Render free plan has NO Shell and NO One-Off Jobs.** First-run seeding happens via `AUTO_SEED=1`
  (empty-DB-only bootstrap in `app/seeddata.py`; prints initial creds once to logs; all accounts
  `must_change_password=True` → forced change at first login). Founder's production admin password is
  whatever they chose at first login (unknown to us).
- **Workers must stay at 1** (`render.yaml`): the in-process scheduler (reminders, SLA escalation,
  retries, backups) must run exactly once. Horizontal scale later = `DISABLE_SCHEDULER=1` on web workers.
- **DB resilience**: `pool_pre_ping` + `pool_recycle=300` in `app/config.py` (fixes Supabase
  `SSL SYSCALL EOF` after idle). SQLite uses WAL + busy_timeout (set in `create_app`).
- **Reference-number race is fixed** by `services.insert_with_unique_ref` (collision retry; DB unique
  constraint as arbiter; idem collision returns original record). Do not reintroduce `count+1` inserts.
- **Load-tested**: 4,000 req/min PASSED (0% failures) on 1 worker, SQLite & PostgreSQL; overload
  ~8,800/min degrades gracefully. See `LOAD_TEST_REPORT.md`; suite in `loadtest/locustfile.py`
  (needs `RATE_LIMIT_SCALE=100000` on BOTH client and server for capacity measurement).

## 3. Immutable business rules (spec)

1. Exactly **FIVE** inspection criteria (app/scoring.py), scores 1–5, total 25; rating bands
   22+ EXCELLENT / 18+ GOOD / 13+ FAIR / 8+ POOR / else CRITICAL.
2. Score 1 or 2 ⇒ **mandatory explanation** (text or voice) before submit (enforced server-side).
3. Complaint portal: **no login, exactly 5 primary fields**, ref `HOSP-CMP-YYYY-NNNNNN`;
   routes to AM-on-duty + department HOD; configurable SLA; auto-**ESCALATED** to MD/CEO on breach
   (audit-logged; SLA extensions may only ADD time).
4. Admin Manager on duty comes from the roster; reminders day-before + duty-day (configurable times).
5. Inspection submit ⇒ lock + PDF (verification QR/code) + WhatsApp Business delivery (cloud/sandbox) + notify MD/CEO.
6. Multi-tenant: `org_id` on every table; RLS deferred; app-layer scoping enforced.
7. AI must stay **administrative & advisory, never clinical** (when AI features get built).

## 4. What is built (all tested; **104/104 tests**, green on SQLite)

- **Core**: auth (scrypt, RBAC 4 roles, forced password change, MFA-ready), CSRF, per-IP rate limits,
  hash-chained audit trail (`app/audit.py`, thread-safe), safe uploads (magic bytes), idempotency keys.
- **Inspections** (5 criteria, voice-to-text, GPS optional/mandatory/disabled, photo evidence,
  review screen, offline draft + sync queue, controlled amendments keeping SUPERSEDED originals).
- **Complaints** (portal + QR locations + USSD intake `/api/v1/ussd/complaint`, SLA engine, escalation,
  status history, attachments, staff queue/detail, HOD actions).
- **Bookings** (`/book`, slots+capacity, refs, SMS confirmation, status/cancel, check-in→queue ticket),
  **Queue** (tickets, staff call/serve/no-show, privacy-safe display screen with voice announcement),
  **Feedback** (stars→service recovery; 4–5★ issue a personal trackable share-link + QR),
  **Referrals** (`/r/<code>` landing, hospital-wide + staff-named QR, click/book analytics,
  own-link is a repeat visit not a conversion, no prizes; staff board `/referrals`).
- **Rosters**: Admin Manager roster (manual + CSV/XLSX import w/ validation preview) and
  **Department rosters** (HOD-managed own dept / super admin all; modes: two 12h shifts or 24h duty;
  1–2 staff per shift; add/edit/delete/import/templates; unique date+shift).
- **Full CRUD** (Add/Edit/Delete/Suspend): users (role edit), departments (+roster system, guarded delete),
  sections, units, complaint categories, QR locations.
- **Automation**: notification engine (in-app/email/WhatsApp/SMS), Termii/Twilio provider interface
  (`app/sms.py`, sandbox default), WhatsApp Cloud API client with retry (`app/whatsapp.py`),
  background dispatch (`app/tasks.py`), scheduler (`app/scheduler.py`).
- **Alerts/UX**: live alert polling `/api/v1/alerts/poll`, toasts, louder/clearer voice reminders
  (quiet hours, min-urgency prefs at `/alert-settings`), premium token-based CSS design system.
- **i18n**: EN/Yorùbá/Hausa/Igbo on patient portals incl. voice-to-text language tags (`app/i18n.py`,
  `/lang/<code>`), best-effort translations flagged for community validation.
- **Management**: executive dashboard (KPIs, heatmap, Management Attention, satisfaction),
  department performance + recurring-issue detection, 9 report types (PDF+CSV, incl. referrals), report archive,
  QR Poster Pack generator (`/admin/posters`), admin control center, audit UI with chain verify.
- **Ops**: Dockerfile, render.yaml, `run.py` CLI (seed/demo/tick/backup/dbcheck), AUTO_SEED bootstrap,
  nightly SQLite backups, `dbcheck` migration helper (`app/migrate.py`).

## 5. Test & run cheat-sheet

```bash
pip3 install -r requirements.txt
python -m pytest tests/ -q            # 99 tests
DATABASE_URL="postgresql://hms:hms_test_pw@127.0.0.1:5432/hms_test" python -m pytest tests/ -q
bash start.sh                          # workspace preview on :8077 (SQLite demo data)
python run.py seed | demo | tick | backup | dbcheck
```

## 6. PENDING MENU (founder chooses)

- 🅱️ 2. **AI service-recovery** (classify urgency/sentiment/category; free-tier AI + rule-based fallback; advisory only)
- 🅱️ 3. **MD/CEO satisfaction dashboard** (deeper analytics)
- 🅲 4. **Attendance + geo-fencing** (tamper-resistant, manual-correction workflow)
- 🅳 6. **Founder's Guide** (10-year-old level manual) · 🅳 8. **Multi-branch + tenant branding**

## 7. Suggested opening for a new chat (founder paste)

> Clone https://github.com/Hcarepro2026/hositalsuite, read HANDOFF.md and ROADMAP.md,
> then continue building my hospital platform. Remember: I am a zero-tech, zero-budget founder;
> always list the pending menu at the end and round up if you run low on tokens.
