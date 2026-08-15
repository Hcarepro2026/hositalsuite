# Continuous Integration — one-time setup (5 minutes)

`github-actions-tests.yml` runs all 142 tests on every push, against **both** SQLite and
PostgreSQL, and checks that the database migrations apply cleanly. It is free for this repo.

It lives here instead of `.github/workflows/` because a Personal Access Token cannot create
workflow files without the `workflow` scope. Activating it is a copy-paste job:

## Option A — GitHub website (easiest, no tokens)

1. Open your repo on github.com.
2. Click **Add file → Create new file**.
3. Type this exact filename: `.github/workflows/tests.yml`
4. Paste the entire contents of `ci/github-actions-tests.yml` into the box.
5. Click **Commit new file**.

Done. Open the **Actions** tab after your next push — a green tick means every test passed
and the change is safe to deploy. A red X means do NOT deploy until it is fixed.

## Option B — from your computer

```bash
mkdir -p .github/workflows
cp ci/github-actions-tests.yml .github/workflows/tests.yml
git add .github/workflows/tests.yml
git commit -m "Enable CI"
git push
```
(Requires a token with the `workflow` scope.)

## Why this matters

You have 142 tests that currently only run when someone remembers to run them. CI runs them
automatically, every time, before the code reaches patients. It is the cheapest quality
protection available and it costs nothing.
