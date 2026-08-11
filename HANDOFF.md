# HANDOFF — Hospital Admin Manager Suite

> Read this file first if you are continuing this project in a new chat or as a new developer.
> Everything described here is real, tested, and already running.

## Project status: v1.0 COMPLETE & DEPLOYED TO GITHUB (2026-08-11)

A production-ready, mobile-first platform automating:
1. Daily Admin Manager departmental inspections (exactly 5 criteria, 1–5 scoring)
2. Mandatory explanations for scores of 1 or 2 (text or voice-to-text)
3. Automatic PDF reports → WhatsApp Business delivery to MD/CEO
4. Duty roster (Excel/CSV import) + automated reminders
5. Public patient complaint portal (no login, 5 fields, QR/USSD) with SLA + auto-escalation
6. Corrective actions, executive dashboard, analytics, 8 report types, hash-chained audit trail

**Automated tests: 28/28 passing** (`python -m pytest tests/ -q`).

## Repository
- GitHub: https://github.com/Hcarepro2026/hositalsuite
- Owner: Hcarepro2026 (zero-tech founder, zero budget — keep all solutions free)

## Tech stack
Python 3.13 · Flask 3 · SQLAlchemy 2 · SQLite (dev) / PostgreSQL (prod-ready) ·
ReportLab (PDF) · qrcode · Web Speech API (voice) · Meta WhatsApp Cloud API (sandbox mode until credentials added)

## How to run
```bash
git clone https://github.com/Hcarepro2026/hositalsuite.git
cd hositalsuite
pip install -r requirements.txt
python run.py seed          # clean setup (users, departments, roster)
python run.py demo          # (optional) adds 10 days sample inspection history
python run.py               # serves on http://0.0.0.0:8077
```

## Seeded accounts (MUST be changed before real hospital use)
| Role | Username | Password |
|---|---|---|
| Super Administrator | `admin` | `Admin#2026!` |
| MD/CEO | `md` | `Mdceo#2026!` |
| Admin Manager | `am.funke` | `Amfunke#2026!` |
| Admin Manager | `am.emeka` | `Amemeka#2026!` |
| HODs | `hod.medicine`, `hod.surgery`, `hod.paeds`, `hod.emergency`, `hod.pharmacy`, `hod.lab` | see README |

## Key paths
- `app/scoring.py` — pure business rules (5 criteria, ratings, SLA, recurring detection)
- `app/scheduler.py` — reminders, SLA escalation, overdue flags, WhatsApp retries, backups
- `app/whatsapp.py` — Meta Cloud API client; modes: sandbox (default) / cloud / disabled
- `app/views/` — routes: auth, main, inspections, complaints, roster, admincp, reports, api
- `.env.example` — ALL production credentials live here (WhatsApp, SMTP, USSD, Postgres)
- `README.md` — full deployment + WhatsApp go-live + security documentation

## Verified end-to-end (on live server, 2026-08-11)
- Inspection submitted → PDF generated → WhatsApp DELIVERED (sandbox) → MD notified → audit logged
- Anonymous complaint → routed to AM on duty + HOD → SLA breach → auto-ESCALATED to MD/CEO
- Roster import validation, verification QR pages, RBAC, CSRF, audit chain integrity

## What is deliberately NOT in git (safety)
`data/` (live database, uploads, PDFs), `.secret_key`, session cookie files — see `.gitignore`.

## Next steps (roadmap agreed with founder)
1. **Database → Supabase (free PostgreSQL)**: create free project at supabase.com,
   get connection string, set `DATABASE_URL` (add `?sslmode=require`). App already supports it.
2. **App hosting (free)**: Render.com or PythonAnywhere; prepare `render.yaml` + gunicorn.
3. **WhatsApp go-live**: Meta Business account → phone-number-id + permanent token → `WHATSAPP_MODE=cloud`.
4. Change all seeded passwords; set real hospital name/logo via Admin → Hospital Setup.
5. Print complaint QR codes (Admin → Settings → QR locations).

## Pushing future changes to GitHub
The founder creates a classic PAT (7-day expiry, `repo` scope) at
https://github.com/settings/tokens/new and pastes it; then:
```bash
git push "https://Hcarepro2026:<TOKEN>@github.com/Hcarepro2026/hositalsuite.git" main
```
Token should be deleted at https://github.com/settings/tokens immediately after use.
