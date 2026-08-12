# 🚀 Founder's Deployment Guide — Take Your Hospital Live (Free)

> Written for a non-technical founder. Follow the steps in order.
> Total time: about 15 minutes. Cost: ₦0.
>
> What we're doing: putting your app on the internet (Render.com — free) and
> connecting it to your cloud database (Supabase — free). When finished you'll
> have a real web address you can give to a hospital.

---

## BEFORE YOU START — checklist

- [ ] Your code is on GitHub ✅ (already done: `Hcarepro2026/hositalsuite`)
- [ ] You have a Supabase project ✅ (already created)
- [ ] You can sign in to GitHub

---

## STEP 1 — Get your database address from Supabase (2 min)

1. Go to **https://supabase.com** → sign in → click your project
2. Click the ⚙️ **gear icon** (Settings) on the left → click **Database**
3. Scroll to **Connection string** → select the **URI** tab
4. You'll see something like:
   `postgresql://postgres:[YOUR-PASSWORD]@db.xxxxx.supabase.co:5432/postgres`

### ⚠️ THE MOST IMPORTANT PART — special characters in your password

Web addresses can't contain a raw `@` or square brackets inside the password.
**Every `@` in your password must be typed as `%40`** (that's the web-standard
code for @). Delete any `[` `]` characters completely.

| Your password contains | In the link you must type |
|---|---|
| `@` | `%40` |
| `[` or `]` | *(delete it)* |
| space | *(delete it — no spaces anywhere in the line)* |

**Example** (password `dmq@4Supabase`):

✅ CORRECT (one line, no spaces, no brackets):
```
postgresql://postgres:dmq%404Supabase@db.zhhdhfllypkzvmukilwt.supabase.co:5432/postgres?sslmode=require
```

❌ WRONG (raw @ and brackets confuse the app):
```
postgresql://postgres:[dmq@4Supabase]@db.zhhdhfllypkzvmukilwt.supabase.co:5432/postgres
```

5. Finish the line with `?sslmode=require` (already shown above).

📋 **Copy it somewhere safe — you'll paste it in Step 3.**

> ⚠️ Keep this string private — it's a key to your database. Never post it publicly.

---

## STEP 2 — Create your free Render account (2 min)

1. Go to **https://render.com** → click **Get Started for Free**
2. Choose **Sign in with GitHub** (easiest way — it lets Render see your code)
3. Approve the permissions when GitHub asks

---

## STEP 3 — Deploy the app (5 min)

1. In the Render dashboard, click **New +** (top right) → **Blueprint**
2. You'll see your GitHub account → choose **Hcarepro2026** → select **hositalsuite**
3. Click **Connect** — Render reads the `render.yaml` file and prepares everything
4. You'll see a list of settings. Two will ask for values:
   - **DATABASE_URL** → paste the full string from **Step 1**
   - **PUBLIC_BASE_URL** → leave blank for now (we set it in Step 5)
5. Click **Apply** / **Create resources**
6. ⏳ Wait 3–6 minutes while Render builds (you'll see scrolling text — that's normal)
7. When you see **"Live"** with a green dot, click the link at the top
   (something like `https://hospital-suite-abc123.onrender.com`)

🎉 **Your app is on the internet!**

> 😴 Note: the free plan lets the app "sleep" after 15 minutes of nobody using it.
> The next visitor waits ~30 seconds for it to wake up. That's normal for the pilot.
> When a hospital starts paying, upgrade to the $7/month plan and it stays awake.

---

## STEP 4 — Set up the hospital (first-time setup, 3 min)

1. Open the **Render dashboard** → click your service → click the **Shell** tab
2. Type this and press Enter:
   ```
   python run.py seed
   ```
   This creates the hospital, departments and first user accounts.
   **Write down the usernames/passwords it prints.**
3. Now open your web address → **Sign in** as `admin` → then change the password
   (Admin → Users → Reset password). Never keep the first password.

---

## STEP 5 — Finish the last setting (2 min)

1. Copy your app's web address (e.g. `https://hospital-suite-abc123.onrender.com`)
2. Render dashboard → your service → **Environment** tab
3. Edit **PUBLIC_BASE_URL** → paste your web address → **Save Changes**
4. Render redeploys automatically (~1 minute)

✅ Done. QR codes and report links now point to your real web address.

---

## STEP 6 — Verify everything works (2 min)

Open these on your phone:

| Check | What you should see |
|---|---|
| `your-address/api/v1/health` | `{"database":true,"status":"ok"}` |
| `your-address/complaint` | Patient complaint portal |
| `your-address/book` | Booking page |
| Sign in as admin → Dashboard | KPI tiles and heatmap |
| Admin → QR Poster Pack → Download | Printable posters |

---

## 🧯 If something goes wrong

| Problem | Fix |
|---|---|
| Build fails on Render | Click the failed build → copy the last red error line → send it to me |
| App shows "Database error" | Re-check the DATABASE_URL you pasted — password and `?sslmode=require` included |
| Log says `could not translate host name "…Supabase]…" ` | Your password's `@` wasn't converted to `%40` (or brackets/spaces left in). Re-paste using the CORRECT example in Step 1. |
| Page loads forever | Free tier cold start — wait 30 seconds and refresh |
| Forgot admin password | Render → Shell tab → `python run.py seed` won't overwrite; ask me for a reset command |
| Anything else | Render → **Logs** tab → copy the last lines → send to me |

---

## 🔮 When the first hospital pays

1. Render: upgrade service to **Starter ($7/mo)** — no more sleeping, faster
2. Supabase: upgrade to **Pro ($25/mo)** — bigger database, no pausing
3. Add WhatsApp: Meta Business → set `WHATSAPP_MODE=cloud` + credentials in Render Environment
4. Add SMS: create Termii account → set `SMS_MODE=termii` + key in Render Environment
5. Rename/brand per hospital via Admin → Hospital Setup

Total running cost with 1 paying hospital: about **₦50,000/month** — charge the hospital
more than that and you're profitable. 💰
