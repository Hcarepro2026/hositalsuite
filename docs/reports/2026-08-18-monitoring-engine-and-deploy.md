# Build Report — Monitoring Engine + Deployed Live
**GENERAL HOSPITAL IJEDE (The Family Hospital)** · 18 August 2026

## ✅ PUSHED AND LIVE

All **11 commits** are on GitHub and Render has deployed them.

```
/api/v1/health  → 200  database:true, scheduler:true, backup ran
/api/v1/ready   → 200  ready:true  (no schema drift — migrations applied cleanly)
```

**461 tests passing on SQLite AND real PostgreSQL 17.**

---

## 🔴 DO THIS NOW — revoke the token

The token you pasted (`ghp_7FM7…`) is **now visible in this chat**. Anyone who
sees it can deploy code straight to your patients.

1. Go to **github.com/settings/tokens**
2. Delete `ghp_7FM7…`
3. Next time, send a **fine-grained token that expires in 7 days**, or run
   `bash push.sh <TOKEN>` yourself so it never enters a chat window

It has done its job. Please revoke it today.

---

## The Monitoring & Tracking Engine

New page: **Patient Flow** (`/tracking`)

Every stage already stamped a time and nobody was reading them. Now:

| What you get | Why it matters |
|---|---|
| **Door-to-door time** per patient | The number a judge or commissioner asks for |
| **Time per step**, against a target | Shows exactly where the hold-up is |
| **Department efficiency** | Which unit is quick, which holds everyone up |
| **Live board** — who is waiting where | Spot the forgotten patient *today* |
| **Week-on-week trend** | Proof you are improving, not just busy |
| **Busiest arrival hours** | Roster staff to match the real rush |
| **Plain-English advice** | "Dr Busy has 6 waiting, Dr Free has 1 — send the next there" |
| **CSV export** | So the figures can be checked by hand |

### Numbers that are honest, not flattering

- **Median shown beside the average** — one forgotten patient at four hours
  drags an average to nonsense; the middle patient stays truthful
- **Under 5 finished journeys → "not enough data"** rather than a confident
  number you might act on
- **8-hour stretches excluded from averages** (a desk forgot to tick someone
  off) but still shown on the live board, flagged — a genuinely abandoned
  patient must be seen
- **Door-to-door is wall-clock**, not the sum of parts, so the walking and
  queueing between desks isn't silently dropped
- **Staff workload is explicitly not a league table** — whoever sees the
  hardest patients will always look slower

---

## The rule I built everything around

**Monitoring must never break patient care.**

If the statistics engine breaks, a receptionist must still be able to take a
patient in. That took three layers, and **each one was added because a test
failed first**:

1. **Guards at the boundary.** My first attempt put the guard *inside* the
   function — a fault in the function's own setup still escaped and killed the
   reception desk.
2. **A second guard at the call site**, so even a wholly broken tracking module
   can't break a request.
3. **Never roll back inside tracking.** This one was nasty: my cleanup rolled
   back the session to tidy up a failed measurement — and silently threw away
   *the patient* the receptionist had just entered. The page still returned
   200, so nobody would have noticed.

---

## Bugs I found by checking — not by tests passing

**1. Patients stuck at HIMS forever.** The folder was created but the database
session wasn't flushed, so the visit had no ID yet and the Reception half of
the journey was linked to nothing. The HIMS step never closed — the patient
showed as *still waiting* hours after going home. Found by walking one patient
through and reading the raw data.

**2. Reception accepted patients HIMS would reject.** Age was optional at the
front desk but required for a folder. A receptionist could take the details,
send the patient to Billing, **take their money** — and only then be told the
folder couldn't be opened. Age is now required where the patient is standing in
front of you, and a contract test asserts anything Reception accepts, HIMS
accepts.

**3. Found only on real PostgreSQL.** PostgreSQL aborts the *whole transaction*
when any statement fails. So catching a tracking error wasn't enough — the
transaction was already poisoned and the patient work that came *after* died
too. SQLite never shows this. Tracking rows now write inside a SAVEPOINT, so a
failed measurement rolls back only itself.

**That last one is exactly why your "test on both databases" rule exists.** It
caught a bug that would have hit production and been almost impossible to
diagnose from a screenshot.

---

## How thoroughly I checked, since you asked

| Check | Result |
|---|---|
| Full suite, SQLite | ✅ 461 passing |
| Full suite, real PostgreSQL 17 | ✅ 461 passing |
| Mutation tests on new safety rules | ✅ 10 applied, 10 caught |
| Every page × 4 roles (92 loads) | ✅ no 5xx, no 404 |
| Public pages, logged out | ✅ all fine |
| New pages block anonymous access | ✅ all 6 redirect to login |
| CSRF enforced on new forms | ✅ all blocked (403) |
| Hostile input (`days=abc`, negative IDs) | ✅ no crashes |
| Another hospital's patient | ✅ 404 — tenants isolated |
| Empty hospital, day one | ✅ 35 edge cases, no crash |
| Migration on real PostgreSQL | ✅ upgrade path + re-run safe |
| Full patient walked end to end | ✅ 9 stages measured, 0 left open |
| Live site after deploy | ✅ healthy, ready:true |

**Two of my ten mutations initially "passed"** — because my patch had hit the
wrong bit of code, so the test was never actually exercised. I found that,
re-ran them properly against the real target, and only then trusted them. A
mutation test that doesn't mutate proves nothing.

---

## Your next actions

| # | Action | Time |
|---|---|---|
| 1 | **Revoke `ghp_7FM7…`** at github.com/settings/tokens | 2 min |
| 2 | Add **`GROQ_API_KEY`** in Render (do NOT add `GROQ_MODEL`) | 5 min |
| 3 | Open the app on your phone, tap once to unlock audio, walk one patient | 10 min |
| 4 | Add a second UptimeRobot monitor on `/api/v1/ready` | 3 min |
| 5 | Enable Supabase backups | 2 min |

---

## Pending menu — what next

| # | Feature | My view |
|---|---|---|
| **1** | **Run a real pilot and film it** | ⭐ You now have the software AND the proof. This is what wins |
| 2 | Billing & Pay-Point as their own screens | Reception drives both today |
| 3 | Role Management | Last unbuilt item from your original nine |
| 4 | Leave approval workflow | Recorded, but no request → approve → balance |
| 5 | Patient satisfaction linked to journey time | "Short visits score 4.6★, long ones 2.1★" |
| 6 | Predicting tomorrow's load from history | Genuinely smart, needs a few weeks of real data first |

**My advice: number 1.** Everything is built and deployed. What you don't have
yet is a real morning of real patients. One clinic, one morning, then show the
dashboard before and after.

---

## One last thing

Both bugs I found today were invisible to a passing test suite. One had
patients frozen at HIMS forever; one would have taken a woman's money and then
refused her a folder.

I found them by walking one patient through and reading what actually happened.
Please do that yourself once a week — front door to pharmacy. Ten minutes will
teach you more than any report I can write.
