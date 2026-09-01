"""
GLOBAL MASTER KNOWLEDGE — App Master v1.0

Makes the AI assistant knowledgeable about the ENTIRE hospital suite,
not just appointments and departments.

Coverage: patient hub 6 tiles, booking, queue, complaint, feedback,
referrals, TV screens, personal TV /t/<key>, VAPID push free alarm,
voice bank 2M2F 4 languages, hospital setup logo, branches, attendance,
roster 4 patterns + 8 leave types, HIMS folder, reception flow,
triage OPD/SOPD/MOPD/EMERGENCY, call room queue, onward routing,
tracking, reports, audit, admin users, security, notifications,
NDPA data requests, backups, offline PWA, slow internet, multi-browser,
feature phone, Fast Track gold lane, SMS/WhatsApp, USSD, queue estimator.

Tone: 1000% human, warm, confident, empathetic, short clear simple
standard English, patient-care oriented, contractions allowed,
ends with soft call-to-action, never diagnoses.

Written for General Hospital Ijede — premium plus plus quality.
"""

KB = [
# ---------------------------------------------------------------- APP OVERVIEW
dict(cat="app_overview", intent="app_what_is", kw=[
    "what is this app","what does app do","explain app","what is hospital suite",
    "what is this system","how does this work","what can this app do",
    "explain this hospital app","what is patient experience os","what is hms",
    "tell me about app","overview of app","app overview","how does app work",
    "what does this app do for patients","what does this app do for staff"],
 en="This is your hospital care system — we built it so your visit feels calm, quick, and respectful. For you, you can book a visit, join the queue and watch your turn live on your phone, ask questions, tell us a problem, and share feedback. For our staff, it guides every single step — from reception to billing to doctor to lab to going home — so no one gets forgotten. It's not a medical record; it's a patient-experience system.",
 pcm="Na your hospital care system be this — we build am make your visit calm, quick, and respectful. For you, you fit book visit, join queue and watch your turn live for your phone, ask question, tell us problem, and give feedback. For our staff, e dey guide every step — from reception to billing to doctor to lab to go house — so nobody go forget. E no be medical record; na patient-experience system.",
 cta="Open the home page — you'll see six simple tiles. Tap what you need."),

dict(cat="app_overview", intent="app_tiles", kw=[
    "six tiles","what are tiles","home tiles","patient hub tiles",
    "what is on home page","home page options","what can i do on home"],
 en="On the home page you'll see six clear tiles: 1. Book a visit — choose a day and time. 2. Join the queue — get a number and track it live. 3. Ask us anything — our assistant answers 24/7. 4. Tell us a problem — make a complaint with a tracking number. 5. How was your visit? — give stars and a comment. 6. Invite a friend — share the hospital with someone you care about. Plus Fast Track at the top — pay a little more, be seen fast in a quiet lounge.",
 cta="Which one would you like to try — Book a visit or Join the queue?"),

dict(cat="app_overview", intent="fast_track_explain", kw=[
    "fast track","fasttrack","gold lane","executive lounge","priority lane",
    "premium lane","be seen faster","skip queue","pay more get fast",
    "executive care","vip lane","fast track how","fast track price"],
 en="Fast Track is our quiet gold lane. You pay a little more and you're seen faster — no long queue. You get a calm lounge, our team walks you through every desk first, TV shows you in gold, and voice calls you in your language. Book it from Book a visit (it's at the top) or choose Fast Track when you Join the queue at the hospital.",
 pcm="Fast Track na our quiet gold lane. You pay small extra, dem go see you faster — no long queue. You go get calm lounge, our team go waka you through every desk first, TV go show you for gold, and voice go call you for your language. Book am from Book a visit (e dey for top) or choose Fast Track when you Join queue for hospital.",
 cta="Open Book a visit — Fast Track is the first card."),

# ---------------------------------------------------------------- BOOKING
dict(cat="booking", intent="how_to_book", kw=[
    "how to book","book appointment steps","how do i book","booking procedure",
    "how to book a visit","book a visit how","i want to book a visit",
    "booking guide","how booking works","how to make booking"],
 en="Booking takes one minute and you're done. Open Book a visit, choose Fast Track if you'd like to be seen faster, pick your department, pick a date and time that works for you, enter your name and phone, tap Book. You'll get a reference like HOSP-APT-2026-000001 instantly. You can check it anytime with Check a booking.",
 cta="Open Book a visit now — I'll keep this chat open if you need me."),

dict(cat="booking", intent="book_online_vs_physical", kw=[
    "online booking vs physical","physical booking","online booking",
    "book online or at hospital","difference online physical booking"],
 en="You have two easy ways: Online booking — do it from your phone anywhere, get a reference, come at your time. Physical booking — walk to reception, we take your details and guide you to billing. Both join the same fair queue. Online just saves you waiting at the gate.",
 cta="If you're at home, use Book a visit. If you're already here, tap Join the queue."),

dict(cat="booking", intent="check_booking", kw=[
    "check booking","check appointment status","my booking","booking status",
    "where is my booking","track booking","booking reference"],
 en="To check your booking, open Check a booking, enter your reference and phone number, and you'll see date, time, department and status instantly. If you need to change it, cancel and rebook — there's no penalty for telling us early.",
 cta="Open Check a booking."),

# ---------------------------------------------------------------- QUEUE
dict(cat="queue", intent="how_to_join_queue", kw=[
    "how to join queue","join queue steps","get a number","queue procedure",
    "how does queue work","how to get queue number","join the queue how"],
 en="Joining the queue is simple. Open Join the queue, choose your department, choose Fast Track at the top if you want to be seen faster, enter your name and phone, tap Get my number. You'll get a ticket like A-042. Keep your phone — we'll show your position live and call you on TV and voice.",
 cta="Open Join the queue — you'll get your number in seconds."),

dict(cat="queue", intent="queue_ticket_explain", kw=[
    "queue ticket","what is queue ticket","ticket page","my ticket",
    "how to track queue","queue position","how long to wait"],
 en="Your ticket page is private — only you can see it with your link. It shows your number, how many are ahead of you, estimated wait (we adjust it live based on how fast reception, billing, and doctors are moving), and it speaks when you're next. Your name never shows on the big TV — only your number, for privacy.",
 cta="Keep your ticket link open — it updates by itself every few seconds."),

dict(cat="queue", intent="queue_screen", kw=[
    "queue screen","tv screen","where is my number","big tv","display screen",
    "public screen","tv queue","how to see queue on tv"],
 en="We have TV screens for every area — MAIN, DENTAL, OPD, PHARMACY, and Fast Track gold. They show ticket numbers only, never your name, so it's private and safe. When it's your turn, you'll hear your number called in English, Yorùbá, Hausa or Igbo. You can also watch your own turn on your phone via personal TV.",
 cta="Look for the TV in your waiting area — or open your personal TV link."),

dict(cat="queue", intent="personal_tv", kw=[
    "personal tv","my tv","private tv","/t/","personal link","watch my turn on phone",
    "how to use personal tv","personal tv link"],
 en="Personal TV is your private tracker — /t/<your-code>. It works even when the app is closed if you enable alarm mode. It shows your number, your position, and estimated wait, and it speaks when you're next. It works on Opera Mini and slow internet, because we kept it tiny — less than 1KB per update.",
 cta="Open your ticket — the personal TV button is right there."),

dict(cat="queue", intent="alarm_mode", kw=[
    "alarm mode","enable alarm","push notification","get notified when closed",
    "notify me when closed","vapid","how to enable alarm","alarm notification"],
 en="Alarm mode lets us notify you even when the app is closed — like a real alarm, and it's free. It saves us SMS cost (₦3-4 per message, ₦90k/month) and saves you data. Tap Enable alarm mode when you see the banner, allow notifications, and we'll ping you when you're next. You can turn it off anytime in your phone settings.",
 cta="On your ticket page, tap Enable alarm mode and allow notifications."),

# ---------------------------------------------------------------- COMPLAINT & FEEDBACK
dict(cat="complaints", intent="how_to_complain", kw=[
    "how to complain","make a complaint steps","complaint procedure",
    "how do i complain","how to report problem","complaint guide"],
 en="We're really sorry something went wrong — we want to fix it quickly. Open Tell us a problem, choose department and category, write what happened in your own words (you can speak it — tap the mic), enter your phone, tap Submit. You'll get a reference like HOSP-CMP-2026-000001 to track. You can also complain anonymously — we won't ask for your phone then.",
 cta="Open Tell us a problem — it takes 1-2 minutes."),

dict(cat="complaints", intent="complaint_anonymous", kw=[
    "anonymous complaint","complain anonymously","hide my name complaint",
    "complaint without phone","anonymous report"],
 en="Yes — you can complain without giving your name or phone. Choose Anonymous on the complaint form. We'll still investigate and use it to improve care, but we won't be able to call you back. If you want a reply and a tracking number, add your phone.",
 cta="Open Tell us a problem and tick Anonymous if you prefer."),

dict(cat="feedback", intent="how_to_feedback", kw=[
    "how to give feedback","feedback steps","rate visit","how was your visit",
    "give stars","how to rate","feedback procedure"],
 en="Your feedback means a lot to us. Open How was your visit?, give 1-5 stars, add a comment if you'd like (you can speak it), choose department, tap Submit. If you give 1-2 stars, we automatically create a recovery ticket so the Admin Manager on duty and HOD must answer it — with an SLA. 4-5 stars? You'll get a personal link to invite a friend.",
 cta="Open How was your visit? — 30 seconds and you're done."),

dict(cat="referrals", intent="referral_how", kw=[
    "referral","invite a friend","share link","how referrals work",
    "share hospital","how to invite friend","refer a friend"],
 en="When you rate us 4 or 5 stars, we give you a personal share-link and QR — /r/YOURCODE. Share it on WhatsApp. When your friend books, we count it as coming from you (not a prize, just a thank you). There's also a hospital-wide QR for posters at reception. No pressure, no coupons — just a kind tell-a-friend.",
 cta="Rate us 4-5 stars and your personal link appears instantly."),

# ---------------------------------------------------------------- VOICE
dict(cat="voice", intent="voice_bank", kw=[
    "voice bank","how many voices","voice languages","2m2f voices",
    "voice audition","voice studio","how to record voice","voice recording",
    "native voice","how to add voice","voice not working"],
 en="We have 16 native voices — 2 male, 2 female for each of 4 languages: English, Yorùbá, Hausa, Igbo. Staff can audition them, pick a favourite, and record directly in the browser. On Android Chrome we record webm/opus — if it shows 00:10 and won't save, update Chrome, allow mic, and tap the screen once to unlock audio. Missing phrases report shows what still needs recording.",
 cta="Ask your admin to open Voice Studio — Record Directly."),

dict(cat="voice", intent="voice_troubleshoot", kw=[
    "voice not speaking","no voice","voice silent","tv not speaking",
    "enable voice","how to enable voice","voice not calling name"],
 en="If voice isn't speaking: 1) Tap the screen once — browsers block sound until first tap. 2) Check volume and not on silent. 3) Allow mic for recording. 4) On TV screen, press Enable Voice. 5) For personal TV, enable alarm mode. Voice needs a tap to unlock, then it calls patients by first name only for privacy.",
 cta="Tap the screen once, then press Enable Voice on the TV."),

# ---------------------------------------------------------------- HOSPITAL SETUP
dict(cat="setup", intent="hospital_setup_logo", kw=[
    "how to add logo","hospital logo","logo top","main app logo",
    "how to upload logo","logo not showing","change hospital logo",
    "logo 512","logo white background"],
 en="Your logo shows on the phone home screen and on PDFs. Go to Admin → Hospital Setup. You'll see Main App Logo at the top in a green box. Upload a square PNG 512x512 under 100KB with white background — it looks best on slow internet and on all phones. It becomes your PWA icon 192, 512, maskable, and Apple touch icon automatically — per hospital.",
 cta="Open Admin → Hospital Setup — logo is right at the top."),

dict(cat="setup", intent="vapid_setup", kw=[
    "vapid","vapid keys","push notifications setup","how to set vapid",
    "free alarm setup","how to generate vapid","web push keys"],
 en="VAPID keys make free alarm notifications work — no SMS cost. Generate once: run python -m py_vapid --gen or npx web-push generate-vapid-keys. You'll get public and private keys. Paste them in Render env as VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY, or per-hospital in Admin → Push Notifications. It's free and saves about ₦90k/month in SMS.",
 cta="Ask your IT person to generate VAPID keys and paste them in Render."),

dict(cat="setup", intent="branches", kw=[
    "branches","hospital branches","sites","gate pin","how to add branch",
    "branch setup","multiple sites"],
 en="If you have more than one site, add them as branches. Go to Admin → Branches. Add name, address, phone, and a gate PIN. Staff clock in at that branch, and you can filter roster and attendance by branch. Each branch can have its own TV screens.",
 cta="Open Admin → Branches to add a new site."),

dict(cat="setup", intent="sms_whatsapp_setup", kw=[
    "sms setup","whatsapp setup","termii","twilio","how to set sms",
    "sms provider","whatsapp provider","how to enable sms"],
 en="SMS and WhatsApp are optional and cost money. We support Termii (Nigeria) and Twilio. Set SMS_MODE to termii or twilio, add TERMII_API_KEY and SENDER_ID or TWILIO keys in Render env. Templates are ready to copy-paste — see docs/SMS_WHATSAPP_TEMPLATES_COPY_PASTE.md. By design, we don't send SMS to patients inside the hospital except emergency — it saves cost and respects their visit.",
 cta="Check docs/SMS_AND_WHATSAPP_SETUP.md for copy-ready templates."),

# ---------------------------------------------------------------- ATTENDANCE & ROSTER
dict(cat="attendance", intent="attendance_how", kw=[
    "attendance","clock in","clock out","i am here","how to clock in",
    "how attendance works","geofence","attendance map"],
 en="Attendance is tap-to-clock. Open Attendance → I am here. If you're within the hospital geofence, it clocks you in; tap again to clock out. It shows you on a map for your HOD. If you're outside, it still records but flags as outside — honest, not blocking.",
 cta="Open Attendance and tap I am here."),

dict(cat="roster", intent="roster_explain", kw=[
    "roster","duty roster","how roster works","4 patterns","shift patterns",
    "how to roster","roster patterns","office hours roster"],
 en="Roster has 4 working patterns: 1) Two 12-hour shifts, 2) One 24-hour duty, 3) Three 8-hour shifts, 4) Office hours Mon-Fri (for Procurement, Audit, Finance, ICT, Admin/HR). You can roster unlimited staff per shift, add 8 leave types — annual, casual, sick, study, maternity, compassionate, exam, off duty. Leave blocks duty automatically — it refuses and tells you which leave. Office departments refuse weekend duty.",
 cta="Open Roster — choose pattern and add staff."),

dict(cat="roster", intent="roster_bulk_upload", kw=[
    "bulk upload roster","upload roster excel","roster csv","how to upload roster",
    "roster import","roster template"],
 en="To bulk upload, download the template, fill names, dates, shifts, save as CSV or Excel, then upload. You'll see a preview — each row says OK or why it's rejected (wrong name, invalid date, duplicate, on leave). Fix and re-upload. Export anytime to CSV.",
 cta="Open Roster → Bulk upload."),

dict(cat="roster", intent="leave_types", kw=[
    "leave types","8 leave types","how to add leave","leave blocks duty",
    "annual leave","casual leave","sick leave","maternity leave"],
 en="We have 8 leave types: annual, casual, sick, study, maternity, compassionate, exam, off duty. Add a date range — it expands to one row per day. If you try to roster someone on leave, we block it and say which leave. Simple and safe.",
 cta="In Roster, choose Leave and add dates."),

# ---------------------------------------------------------------- HIMS & RECEPTION FLOW
dict(cat="hims", intent="hims_search", kw=[
    "hims","search folder","open folder","how to search patient folder",
    "hospital number","how to find patient","patient folder"],
 en="HIMS is the patient folder — not a medical record. Always search first: hospital number, phone, surname, first name, or surname firstname in any order. If found, open folder. If not, open a new folder. We prevent duplicates — if a likely match exists, we show it and force a tick-box before creating a second one. We never invent a birthday — we accept stated age honestly.",
 cta="Open HIMS Register and search — try phone number, it always works."),

dict(cat="hims", intent="hims_payment_routes", kw=[
    "lahsma","megalex","payment routes","nhis","hmo","self pay",
    "how to set payment","insurance payment","payer type"],
 en="Payment routes: LAHSMA (Lagos State insurance) and Megalex (Lagos State revenue system for general hospitals), plus Self-pay, NHIS, HMO, Exempt. LAHSMA/NHIS/HMO must have a scheme number or Billing cannot claim. Choose at reception or HIMS — it flows to billing automatically.",
 cta="At HIMS, choose payment route — LAHSMA needs scheme number."),

dict(cat="reception", intent="reception_flow", kw=[
    "reception flow","front door","how reception works","reception steps",
    "reception to billing","billing to paypoint","paypoint to hims"],
 en="Reception is the front door. You welcome the patient, note special needs (wheelchair, hard of hearing, poor sight, interpreter, preferred language EN/YO/HA/IG), insurance, then send to Billing → Pay Point. After Pay Point records payment, patient appears in HIMS as Paid — waiting for folder. HIMS opens folder and sends to Triage. This separation stops money and reception mixing — cashier records money, not receptionist.",
 cta="Follow the flow: Reception → Billing → Pay Point → HIMS → Triage."),

dict(cat="reception", intent="special_needs", kw=[
    "special needs","assistance needed","wheelchair","hard of hearing",
    "poor sight","interpreter","preferred language","how to look after"],
 en="We ask how to look after them: preferred language (English, Yorùbá, Hausa, Igbo), assistance needed — wheelchair, offer a seat, hard of hearing, poor sight, walks with difficulty, carer, interpreter — plus a free-text care note. These flags travel with the patient and trigger an urgent voice call: Team, Abatan at reception needs help. Needs wheelchair; prefers Yorùbá — greet them in it.",
 cta="At reception, tick assistance needed — it speaks to the team."),

# ---------------------------------------------------------------- TRIAGE & CONSULTING
dict(cat="triage", intent="triage_how", kw=[
    "triage","how triage works","opd sopd mopd emergency","how to triage",
    "triage bench","place patient","clinic of the day"],
 en="Triage places each patient into OPD/SOPD/MOPD/Emergency, plus doctor rooms, based on category (CHILD under 12, ELDERLY 65+, adult), day of week, clinic of the day, and which doctors are rostered AND clicked ready to consult. We show waiting counts and speak them. Blood sugar step records only that test was done — never the reading — because this is not a medical record.",
 cta="Open Triage bench — place patients into clinic and room."),

dict(cat="triage", intent="doctor_ready", kw=[
    "doctor ready","ready to consult","how doctor becomes ready",
    "consulting room queue","call room queue","doctor queue"],
 en="A doctor's queue shows patients named to them AND unassigned patients in their own clinic — so no one gets stranded. Doctor must be on today's roster AND click I am ready to consult with clinic and room. Then triage can send patients. In /consulting-room, doctor calls patient in, finishes consultation.",
 cta="Doctors: open My consulting room and tap I am ready."),

dict(cat="onward", intent="onward_routing", kw=[
    "onward routing","lab pharmacy","how to route patient","onward destinations",
    "lab pharmacy billing","megalex lahsma emergency routing"],
 en="After seeing the patient, doctor ticks where next — Lab, Pharmacy, Billing, Megalex, LAHSMA, Emergency — one, two or three at a time. Patient appears at those desks. Each desk has its own queue. When all desks finish, visit closes itself and says safe journey home. Journey time shown everywhere.",
 cta="At end of consultation, tick Lab / Pharmacy / Billing as needed."),

# ---------------------------------------------------------------- TRACKING & REPORTS
dict(cat="tracking", intent="tracking_how", kw=[
    "tracking","patient flow","door to door time","how long visit takes",
    "busiest hours","department efficiency","who is waiting where",
    "week on week","allocation advice"],
 en="Tracking measures every stage: door-to-door time, per-department efficiency, live who is waiting where, week-on-week trend, busiest hours, and plain-English allocation advice. It never breaks care — every write is wrapped in a SAVEPOINT so a tracking fault never stops a patient being seen. It also speaks when someone is forgotten or a bottleneck forms.",
 cta="Open Patient flow — it shows typical whole visit and what needs attention."),

dict(cat="reports", intent="reports_archive", kw=[
    "reports","pdf report","verification code","reports center",
    "how to get report","report archive","audit log"],
 en="Every inspection, complaint, referral, and tracking export gets a PDF with hospital branding, reference number, and verification QR + code. They're archived permanently and you can download anytime from Reports center. Audit log is hash-chained — if anyone tampers, it shows.",
 cta="Open Reports center for PDFs and verification."),

# ---------------------------------------------------------------- ADMIN & SECURITY
dict(cat="admin", intent="users_roles", kw=[
    "users","roles","permissions","how to add user","how to assign role",
    "admin manager","hod","super admin","role management"],
 en="We have 8 roles: SUPER_ADMIN, MD_CEO, DMD, DCST, APEX_NURSE, HEAD_ADMIN_HR, ADMIN_MANAGER, HOD. Go to Admin → Users to add staff, assign role, set department. Bulk upload parses your nominal roll (MEDICAL, PUB AFF OFF, FIN/ACCTS), generates usernames and one-time passwords shown once. Accounts start unapproved + must-change-password for safety.",
 cta="Open Admin → Users to manage staff."),

dict(cat="security", intent="security_headers", kw=[
    "security","secure cookies","hsts","csp","rate limiting","audit log",
    "how secure is app","security headers","login lockout"],
 en="Security is premium: secure cookies, HSTS, CSP, per-IP + per-username login lockout (10 fails → 15 min lock), hash-chained audit, ProxyFix for real IP, 8MB max upload, connect_timeout 5s so boot never hangs. Health always 200, readiness detects schema drift.",
 cta="Check /api/v1/ready — it tells you if database columns are missing."),

dict(cat="privacy", intent="ndpa_rights", kw=[
    "ndpa","data protection","privacy rights","access request","erasure",
    "how to request data","data subject request","retention"],
 en="Under NDPA 2023, you have rights: Access — ask for copy of data we hold, Correction — fix what's wrong, Erasure — ask us to delete where law allows, Withdraw consent — anytime. Go to Privacy → Make a data request. We keep records for 6 years (configurable), then anonymise name, phone, description automatically. TV screens show ticket numbers only, never names. Staff phones are masked: 080****5678.",
 cta="Open Privacy → Make a data request."),

dict(cat="privacy", intent="mask_phone", kw=[
    "mask phone","phone masked","privacy phone","why phone masked",
    "hide phone number","phone privacy"],
 en="For privacy, we mask phones on staff lists: 08012345678 → 080****5678. Only SUPER_ADMIN sees full number in complaint detail. Public screens never show phone at all. Personal TV link is a random 12-char code — 72 bits — safe from guessing, and we rate-limit it.",
 cta="If you need full number, ask a SUPER_ADMIN."),

# ---------------------------------------------------------------- BACKUP & OFFLINE
dict(cat="backup", intent="backup_how", kw=[
    "backup","how backup works","restore backup","csv zip backup",
    "how to create backup","backup restore drill","engine independent backup"],
 en="Backups are engine-independent CSV-in-zip with manifest and restore instructions, stored durably (not on ephemeral disk). Nightly at 02:00, keeps 7 by default. Manual: Admin → Backups → Download, or python run.py backup. Restore drill: restore one into a test database each quarter — an untested backup is not a backup. Enable Supabase backups too as second safety net.",
 cta="Open Admin → Backups to download now."),

dict(cat="pwa", intent="offline_how", kw=[
    "offline","pwa","service worker","works offline","slow internet",
    "how offline works","app shell","opera mini","uc browser"],
 en="The app is offline-first. Service worker caches the shell, so it loads on slow Africa internet. Payload is tiny — <1KB poll when visible — and it pauses when hidden. Works on Chrome, Firefox, Edge, Samsung Internet, Opera, Safari, iPhone Add to Home Screen, and falls back to TV+Voice+Personal link on Opera Mini/UC Browser. No external CDN — all CSS/JS is local.",
 cta="Add to Home Screen from your browser menu — it becomes an app."),

# ---------------------------------------------------------------- NOTIFICATIONS & SMS
dict(cat="notifications", intent="notifications_how", kw=[
    "notifications","whatsapp delivery","how notifications work",
    "in-app email whatsapp","notification logs","retries"],
 en="Notifications go in-app, email, WhatsApp, and SMS — all logged with retries. Report PDF is sent to MD/CEO over official WhatsApp Business Cloud API (media upload + document message). Status pipeline: Generated → Sending → Delivered → Failed with retries and audit. You can test from Admin → Notifications.",
 cta="Check Admin → Notifications for delivery status."),

dict(cat="sms", intent="no_sms_inside", kw=[
    "no sms inside","why no sms inside hospital","sms inside hospital rule",
    "sms policy","inside hospital sms"],
 en="By design, we don't send SMS to patients inside the hospital except emergency or complaints. Why? It saves cost (₦3-4 per SMS), respects their visit (they're already here), and TV + voice + personal TV already tells them their turn. Founder's rule: TV+Voice is enough inside.",
 cta="For patients inside, rely on TV and personal TV — not SMS."),

# ---------------------------------------------------------------- QUEUE ESTIMATOR & USSD
dict(cat="estimator", intent="queue_estimator", kw=[
    "queue estimator","how wait time calculated","smart queue",
    "how long will i wait","estimated wait","wait time algorithm"],
 en="Wait time is smart, not fixed. We have a per-hospital cache that looks at real speed: how many patients are at reception, billing, Megalex, LAHSMA, HIMS, Triage, waiting to see doctors, and onward (lab, pharmacy). It adjusts every minute. Fast Track is half time. It shows on ticket, TV, and staff desks.",
 cta="Your ticket shows live estimate — it updates itself."),

dict(cat="ussd", intent="ussd_how", kw=[
    "ussd","feature phone","africas talking","how ussd works",
    "ussd code","how to use ussd","ussd callback","con end"],
 en="For feature phones, we have TV + Voice + Personal TV link /t/<key> that works on Opera Mini + Help desk phone number. Future USSD via Africa's Talking is ready: they POST CON/END callbacks to /api/v1/ussd/complaint with shared secret, and it enters same complaint pipeline. No smartphone needed.",
 cta="For now, use Help desk phone or personal TV link on any phone."),

# ---------------------------------------------------------------- HOW-TO STAFF
dict(cat="howto_staff", intent="how_to_add_logo", kw=[
    "how to add logo step by step","add logo guide","upload logo steps"],
 en="Step by step to add logo: 1) Make a square PNG 512x512 under 100KB with white background. 2) Go to Admin → Hospital Setup — logo box is at top in green. 3) Choose file, upload, you'll see 96px preview plus links for 192,512,maskable,apple. 4) Save. 5) Add to Home Screen on your phone — you'll see your logo. Each hospital has its own.",
 cta="Open Admin → Hospital Setup now."),

dict(cat="howto_staff", intent="how_to_record_voice", kw=[
    "how to record voice step by step","record voice guide","voice recording steps",
    "how to audition voice","how to pick voice"],
 en="To record voice: 1) Open Admin → Voice Studio. 2) You'll see 16 voices — 2 male, 2 female × 4 langs. Tap Audition to listen. 3) Pick favourite. 4) For custom, tap Record Directly — allow mic, speak clearly, tap Save. On Android Chrome it saves webm/opus. If Save spins, update Chrome and tap screen once to unlock audio. 5) Check Missing phrases report for what still needs recording. Bulk zip download available.",
 cta="Open Voice Studio → Record Directly."),

dict(cat="howto_staff", intent="how_to_manage_roster", kw=[
    "how to manage roster","roster guide","how to roster staff",
    "how to add staff to roster","roster steps"],
 en="To manage roster: 1) Open Roster. 2) Choose scope — hospital-wide, department, section, unit. 3) Pick date range — today, 7 days, 30 days, custom. 4) Choose pattern — two 12h, one 24h, three 8h, office Mon-Fri. 5) Add staff — unlimited per shift. 6) Add leave if needed. 7) Save. It blocks if on leave and tells you which leave. Export to CSV anytime.",
 cta="Open Roster to start."),

dict(cat="howto_staff", intent="how_to_open_folder", kw=[
    "how to open folder","open folder steps","how to create folder",
    "folder guide","how to register patient"],
 en="To open a folder: 1) Open HIMS Register. 2) Search first — hospital number, phone, or name. 3) If found, open folder. 4) If not, tap Open a new folder. 5) Enter identity, contact, next of kin (required), payment route, preferred language, assistance needed. 6) Save — it auto-assigns hospital number like IJE/2026/00001 and sends to Triage. Duplicate warning shows likely matches — tick box to override if truly new.",
 cta="Open HIMS → Search first, then Open a new folder."),

dict(cat="howto_staff", intent="how_to_triage", kw=[
    "how to triage","triage steps","how to place patient","triage guide"],
 en="To triage: 1) Open Triage bench. 2) You'll see patients waiting — priority first (elderly 60+, pregnant, child <5, wheelchair). 3) Choose clinic — OPD/SOPD/MOPD/Emergency, and doctor/room if ready. 4) Tick blood sugar done if done (we record only that it was done, not the reading). 5) Tap Place this patient. They'll be called by name on voice and appear in doctor's queue.",
 cta="Open Triage bench now."),

dict(cat="howto_staff", intent="how_to_call_patient", kw=[
    "how to call patient","call patient in","call room queue",
    "how doctor calls patient","consulting room steps"],
 en="Doctor: 1) Open My consulting room. 2) If not ready, choose clinic and room and tap I am ready to consult (you must also be on today's roster). 3) You'll see your queue — named to you AND unassigned in your clinic. 4) Tap Call this patient in. 5) After seeing them, tick where next — Lab, Pharmacy, Billing, Megalex, LAHSMA, Emergency — one to three, and tap Finish consultation. If no tick, visit closes and says safe journey home.",
 cta="Open My consulting room and tap I am ready."),

dict(cat="howto_staff", intent="how_to_view_tracking", kw=[
    "how to view tracking","tracking dashboard","how to see patient flow",
    "how to see who is waiting","tracking guide"],
 en="To view tracking: Open Patient flow. You'll see typical whole visit (median), patients finished, in hospital now, waiting too long. Below: where time goes (per step), who is in hospital now (first name only for privacy), department efficiency, week-on-week are we getting better, busiest hours bar chart, workload by staff. Advice box says what needs attention — suggestions, not orders. It never moves a patient on its own.",
 cta="Open Patient flow dashboard."),

dict(cat="howto_staff", intent="how_to_backup", kw=[
    "how to backup","create backup","backup guide","how to download backup",
    "how to restore backup"],
 en="To backup: Open Admin → Backups → Download, or run python run.py backup. It's a zip of CSVs per table with manifest — engine-independent, so you can restore to SQLite or PostgreSQL. Keep 7 by default. Restore drill: restore one into a test DB each quarter. Also enable Supabase backups in Dashboard → Backups as second safety net.",
 cta="Open Admin → Backups now."),

dict(cat="howto_staff", intent="how_to_manage_users", kw=[
    "how to manage users","add user","user management","how to add staff",
    "how to assign role","how to reset password"],
 en="To manage users: Open Admin → Users. Tap Add user, enter name, phone, email, role (SUPER_ADMIN, MD_CEO, DMD, DCST, APEX_NURSE, HEAD_ADMIN_HR, ADMIN_MANAGER, HOD), department. It creates username and one-time password shown once — copy it. Account starts unapproved + must-change-password. For bulk, upload Excel/CSV of nominal roll — it parses MEDICAL, PUB AFF OFF, FIN/ACCTS, generates usernames.",
 cta="Open Admin → Users."),

# ---------------------------------------------------------------- ENGLISH REWRITE HELP
dict(cat="english", intent="english_tone", kw=[
    "english tone","how to write english","patient care tone","1000% human",
    "short clear simple english","nice tone","correct grammar"],
 en="We write in short, clear, simple standard English — warm, confident, empathetic, patient-care oriented. Use contractions (you're, we're, it's), active voice, short sentences, end with soft call-to-action. Never diagnose. Example: Instead of Please choose a department and enter your name, say Please choose where you need to go and tell us your name. We're here to help you.",
 cta="Keep it human — short, warm, clear."),

# ---------------------------------------------------------------- PAYMENT GATE
dict(cat="payment", intent="payment_upfront", kw=[
    "payment upfront","pay before service","payment gate","how payment works",
    "pay before doctor","billing gate"],
 en="Payment is upfront by design — Reception → Billing → Pay Point → HIMS → Triage. Billing issues bill, Pay Point records payment, then HIMS opens folder. This is separation of duties: cashier records money, not receptionist. It also ensures hospital collects revenue via Megalex (Lagos State revenue system) and LAHSMA (insurance). Fast Track pays more for fast lane.",
 cta="Follow the gate: Reception → Billing → Pay Point."),

# ---------------------------------------------------------------- SLOW INTERNET
dict(cat="tech", intent="slow_internet", kw=[
    "slow internet","data saving","low data","how app works on slow internet",
    "africa internet","payload small","1kb poll"],
 en="We built for slow internet in Africa. Payload is tiny — less than 1KB poll when visible, and we pause when tab is hidden. No external CDN — all CSS/JS is local. Logo is 512 under 100KB. PWA caches shell. TV and personal TV work on Opera Mini. Voice is browser-native, no extra download. It works on 2G.",
 cta="It works even on slow data — keep your ticket open."),

dict(cat="tech", intent="multi_browser", kw=[
    "which browsers","browser support","chrome firefox edge samsung",
    "opera safari iphone","does app work on iphone","add to home screen"],
 en="Works on all modern browsers: Chrome, Firefox, Edge, Samsung Internet, Opera, Safari, iPhone Safari. Add to Home Screen from browser menu — it becomes an app with your hospital logo. On Opera Mini/UC Browser, we fall back to TV + Voice + Personal TV link + Help desk phone — so feature phones still work.",
 cta="Add to Home Screen for best experience."),
]
