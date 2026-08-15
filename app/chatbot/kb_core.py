"""GLOBAL MASTER DIALOGUE LIBRARY — Part 1 (core patient journey).

Written to a premium patient-experience standard: warm, confident, empathetic,
contractions, light reassurance, ends with a soft low-friction call-to-action,
and NEVER diagnoses or prescribes. Pidgin alongside English; Yoruba/Hausa/Igbo
on core intents. Keywords are conversation triggers (500+ across the library).
"""

KB = [
# ---------------------------------------------------------------- GREETINGS
dict(cat="greetings", intent="greet", kw=[
    "hello","hi","hey","good morning","morning","good afternoon","afternoon","good evening",
    "evening","how far","how far na","greetings","salut","welcome","good day","how do you do",
    "hello there","hi there","how are you today","greetings to you","nice day"],
 en="Hello, and a very warm welcome! I'm your hospital care assistant, and I'm really glad you're here. Whether you're booking a visit, checking a bill, or just finding your way around, I've got you. How can I make your day easier?",
 pcm="How far! Welcome o. Na me be your hospital care assistant, and I dey here to help you well well. Wetin you dey find today — booking, bill, or direction? Make we do am together.",
 yo="Ẹ nílẹ̀! A dúpẹ́ pé o wá. Èmi ni olùrànlọ́wọ́ aláìsàn rẹ — kí ni mo lè ṣe fún ọ lónìí?",
 ha="Sannu! Barka da zuwa. Ni ne mai taimaka muku a asibiti. Me za mu iya yi muku yau?",
 ig="Nnọọ! Anyị nwere obi ụtọ na ị bịara. Abụ m onye enyemaka gị — kedu ka m ga-esi nyere gị aka taa?",
 cta="Tell me what you need — booking, bills, directions, or anything at all."),
dict(cat="greetings", intent="how_are_you", kw=[
    "how are you","how are you doing","you okay","are you fine","how is it going","hows it going",
    "you dey there","you dey ok","are you there","are you a robot","who are you","what are you"],
 en="I'm doing wonderfully, thank you for asking — that's so kind of you! I'm the hospital's care assistant, here day and night to make things simple for you and your family. What can I help you with right now?",
 pcm="I dey fine o, thank you! You too dey kind to ask. Na me be the hospital care assistant, I dey here morning and night to make things easy for you. Wetin go help you now?",
 cta="Ask me anything — I'm listening."),
dict(cat="greetings", intent="thanks", kw=[
    "thank you","thanks","thank you very much","thanks a lot","i appreciate","appreciate it",
    "you are helpful","very helpful","that helps","great thanks","many thanks","you too much",
    "na so","well done","good job","perfect","awesome"],
 en="You're so welcome — it's genuinely my pleasure to help. Seeing you sorted is exactly why I'm here. Is there anything else I can take off your plate today?",
 pcm="You don welcome o! Na my pleasure to help you. Anything else wey you wan make I do for you? No shai o.",
 cta="If anything else comes to mind, just say the word."),
dict(cat="greetings", intent="goodbye", kw=[
    "bye","goodbye","see you","see you later","later","good night","i have to go","that is all",
    "nothing else","no more questions","take care","farewell","i am leaving"],
 en="Take good care of yourself — it's been a pleasure assisting you. We're always here for you and your family, any day, any time. See you soon!",
 pcm="Take care o! E don sweet to help you. We dey here always for you and your family, any day any time. Bye bye, see you soon!",
 cta="Come back anytime — even just to say hello."),

# ---------------------------------------------------------------- APPOINTMENTS
dict(cat="appointments", intent="book_appointment", kw=[
    "book appointment","book a visit","make appointment","schedule appointment","i want to book",
    "appointment","book now","reserve","get appointment","see a doctor","see doctor","consult",
    "i need a doctor","want to see doctor","fix appointment","arrange visit","come in tomorrow",
    "when can i come","book me","make booking"],
 en="I'd love to get you booked in — it only takes a minute. You can book right here on this page, and you'll get a reference number straight away. If you'd rather talk to a person, just say so and I'll connect you to the front desk. Which service would you like?",
 pcm="No wahala, go book you sharp sharp. E go take small time. Fit book for this page, and go collect your number immediately. If you prefer make person talk to you, just talk make I connect you front desk. Which service you dey find?",
 cta="Tap 'Book a Visit' below, or tell me the department and I'll guide you."),
dict(cat="appointments", intent="reschedule", kw=[
    "reschedule","change appointment","move appointment","postpone","shift my visit","new date",
    "change date","can i change","rebook","cancel and rebook","adjust appointment"],
 en="Of course — life happens, and we're happy to move things for you. The quickest way is to cancel and rebook online, or I can pass you to the front desk who'll adjust it in one call. Which date were you hoping for?",
 pcm="E no be problem at all, we go shift am for you. The fast way na to cancel and book again online, or make I pass you give front desk, go change am with one call. Which date you wan?",
 cta="Tell me your preferred date, or tap Book to pick a fresh slot."),
dict(cat="appointments", intent="cancel_appointment", kw=[
    "cancel appointment","cancel my visit","i cant come","i can't make it","not coming","cancel booking",
    "annul","withdraw appointment","skip my visit"],
 en="No problem at all — I've noted that you may not make it. You can cancel using your booking reference on the status page, and there's no penalty for letting us know early. Would you like me to open that page for you?",
 pcm="No wahala. Fit cancel with your booking number for the status page, and no penalty if you tell us early. You wan make I open the page for you?",
 cta="Say 'status' and I'll show you where to cancel in two taps."),
dict(cat="appointments", intent="check_appointment", kw=[
    "check appointment","my appointment","appointment status","when is my appointment","confirm booking",
    "do i have appointment","appointment time","what time is my visit","verify booking"],
 en="Happy to check that for you. Pop your booking reference and phone number into the status page and it'll show everything instantly. If anything looks off, the front desk will sort it in a minute. Shall I take you there?",
 pcm="Go check am quick quick. Put your booking number and phone number for the status page, e go show you everything sharp sharp. If anything no correct, front desk go fix am. Make I carry you go there?",
 cta="Tap 'Check status' and your details will pop right up."),

# ---------------------------------------------------------------- BILLS & INSURANCE
dict(cat="bills", intent="bill_explain", kw=[
    "my bill","explain bill","breakdown of bill","why am i charged","understand my bill","bill details",
    "what is this charge","hospital bill","invoice","receipt","charges on my bill"],
 en="I completely understand wanting clarity on your bill — you deserve to know exactly what you're paying for. The billing desk can walk you through every line in plain language, and I can request an itemised breakdown for you. Would you like me to arrange that?",
 pcm="I understand say you wan know wetin you dey pay for — na your right. Billing desk fit explain every line well well, and I fit request full breakdown for you. You wan make I arrange am?",
 cta="Say 'breakdown' and I'll have the billing team prepare it for you."),
dict(cat="bills", intent="bill_estimate", kw=[
    "how much","cost","price","how much is","fees","charge for","estimate","how much will","price list",
    "cost of","charges","tariff","rate","billing rates","package price"],
 en="Great question, and I like the way you're planning ahead. Costs vary a little by service, so here's the honest way to get an accurate figure: I can show our standard price ranges, or the billing desk can give you a precise quote before you proceed. Which would you prefer?",
 pcm="Correct question o! Price dey change small depending on the service. Make I show you our normal price range, or billing desk go give you exact figure before you start. Which one you prefer?",
 cta="Tell me the service and I'll give you a clear estimate right away."),
dict(cat="bills", intent="bill_payment", kw=[
    "how to pay","pay bill","payment","pay my bill","payment methods","card payment","transfer",
    "pos","pay online","how do i settle","settle bill","make payment",
    "how do i pay","how can i pay","where do i pay","how to make payment","mode of payment",
    "do you take card","do you accept transfer","can i pay with card"],
 en="Paying is quick and flexible — we accept card, bank transfer, and POS at the billing desk, and you'll always get a proper receipt. If you'd like, I can point you to the desk or help you start online. How would you like to pay?",
 pcm="Payment easy o — we dey accept card, transfer, and POS for billing desk, and go collect proper receipt. If you like, I fit show you the desk or help you start online. How you wan pay?",
 cta="Choose card, transfer, or POS and I'll guide you through it."),
dict(cat="bills", intent="insurance_nhis", kw=[
    "nhis","insurance","health insurance","hmo","my hmo","insurance cover","does insurance","enrolment",
    "nhia","health plan","insurance card","cover me"],
 en="Yes — we work with NHIS and most health maintenance organisations, so your cover can do the heavy lifting for you. Bring your enrolment card or ID and we'll verify it at the desk before you're seen. Would you like me to confirm your plan is on our list?",
 pcm="Yes o! We dey work with NHIS and plenty HMO, so your insurance fit pay for you. Carry your card or ID make we verify am for desk before dem see you. You wan make I confirm say your plan dey our list?",
 cta="Tell me your HMO name and I'll check it for you now."),
dict(cat="bills", intent="bill_dispute", kw=[
    "wrong charge","overcharged","dispute bill","this is too much","i was charged wrongly","billing mistake",
    "double charge","incorrect bill","complain about bill","refund"],
 en="I'm really sorry if something on your bill looks off — that's not the experience we want for you, and it's absolutely fixable. Our billing review team handles these personally and fast. Shall I open a review for you right now?",
 pcm="I dey sorry if anything for your bill no correct — e no suppo be so, and e dey very fixable. Our billing review team dey handle this kind thing personally and fast. Make I open review for you now now?",
 cta="Say 'review' and I'll log it so the team calls you back today."),

# ---------------------------------------------------------------- HOURS & LOCATION
dict(cat="hours", intent="hours_clinic", kw=[
    "opening hours","hours","what time do you open","closing time","when do you close","working hours",
    "clinic hours","are you open","open now","open today","open on saturday","weekend hours","operating hours"],
 en="We're open Monday to Friday from 8am to 6pm, and Saturday mornings from 8am to 1pm — and our emergency unit never closes, day or night. If you're planning a visit, mornings are usually the calmest. Would you like me to book you a quiet slot?",
 pcm="We dey open Monday to Friday 8am to 6pm, and Saturday morning 8am to 1pm — and our emergency no dey close at all, day and night. If you dey plan to come, morning usually calm. You wan make I book quiet slot for you?",
 yo="A ṣí ní 8 àárọ̀ dé 6 irọ̀lẹ́ ní ọjọ́ ìṣẹ́; ẹ̀yà ìjàmbá wa ṣí ní alẹ́ àti ọ̀sán. Ṣé kí n gbé ìpàdé sílẹ̀ fún ọ?",
 ha="Muna buɗewa daga 8 na safe zuwa 6 na yamma a ranakun aiki; sashen gaggawa ba ya buɗewa ko da yaushe. Za a iya ajiye muku lokaci?",
 ig="Anyị na-epe site na 8 nke ututu ruo 6 nke mgbede; ngalaba mberede anaghị emechi. Ị chọrọ ka m debe gị oge?",
 cta="Want me to grab you a morning slot while it's quiet?"),
dict(cat="hours", intent="hours_emergency", kw=[
    "is emergency open","emergency hours","a and e hours","casualty hours","emergency at night","24 hours",
    "night emergency","emergency open now"],
 en="Yes — Accident & Emergency is open 24 hours, every single day of the year, including holidays. If someone needs urgent help right now, please come straight in or call an ambulance; don't wait for morning. Can I alert the team that you're on your way?",
 pcm="Yes o! A&E dey open 24 hours, every day, even holiday. If person need urgent help now now, abeg come straight or call ambulance; no wait morning. Make I tell the team say you dey come?",
 cta="If it's urgent, head in now — I'll let the desk expect you."),
dict(cat="hours", intent="directions", kw=[
    "where is","directions","how do i get","locate","find the hospital","address","where are you located",
    "map","how to reach","which street","landmark","where is your hospital"],
 en="We'd love to welcome you in person. You'll find our address and a tap-to-open map on the hospital homepage, and the reception team can guide you the moment you arrive. Would you like me to send the map link to your phone?",
 pcm="Go meet us for the hospital homepage, address and map dey there, and reception go guide you the moment you reach. You wan make I send the map link to your phone?",
 cta="Say 'map' and I'll text you the location right away."),

# ---------------------------------------------------------------- FIRST VISIT
dict(cat="first_visit", intent="first_visit_steps", kw=[
    "first time","first visit","i have never been","new patient","first time coming","how does it work",
    "what happens when i come","first appointment","new here","never visited"],
 en="Welcome — first visits can feel like a lot, so here's the simple path: check in at reception with any ID, get your folder opened, then head to the department on your slip. A staff member is always nearby if you feel stuck. Want me to book your first visit so everything's ready when you arrive?",
 pcm="Welcome o! First visit fit feel like plenty, so make I break am down: check in for reception with any ID, dem go open your folder, then you go go the department wey dey your slip. Staff dey always near if you confuse. You wan make I book your first visit make everything ready?",
 cta="Shall I set up your first visit so you walk in like a regular?"),
dict(cat="first_visit", intent="first_visit_bring", kw=[
    "what to bring","what should i bring","bring what","documents needed","do i need id","what do i need",
    "folder","medical records","previous results","carry what"],
 en="Smart to ask! Please bring any ID, your previous results or scans if you have them, and a list of any medicines you currently take. If it's your first time, we'll open a fresh folder for you on the spot. Anything else you'd like me to check?",
 pcm="Correct question! Abeg carry any ID, your old results or scan if you get, and list of medicine wey you dey take. If na first time, go open new folder for you on the spot. Anything else you wan make I check?",
 cta="You're all set — want me to book your slot?"),

# ---------------------------------------------------------------- SERVICES
dict(cat="services", intent="services_overview", kw=[
    "services","what services","what do you offer","departments","what can you do","facilities",
    "list of services","do you have","specialist","clinics available","units"],
 en="We offer a full range of care — from outpatient clinics and diagnostics (lab, imaging) to surgery, maternity, paediatrics, and a 24/7 emergency unit. Think of us as your family's one-stop health home. Which area are you curious about?",
 pcm="We get full care o — from OPD and lab/imaging to surgery, maternity, children ward, and emergency wey dey open 24/7. Think of us as your family one-stop health house. Which area you wan know about?",
 cta="Tell me a department and I'll give you the details and hours."),

# ---------------------------------------------------------------- COMPLAINTS
dict(cat="complaints", intent="complaint_start", kw=[
    "i want to complain","complaint","make a complaint","i have a complaint","report issue","bad service",
    "not happy","unhappy","mistreat","rude staff","poor service","something went wrong","i was treated badly",
    "was rude","were rude","rude to me","shouted at me","ignored me","nobody attended to me",
    "kept me waiting","no one helped me","treated me badly","very rude","so rude"],
 en="I'm truly sorry your experience fell short — that matters to us, and I'm going to make sure the right people hear it and act on it. You can submit it right here in under a minute, and you'll get a reference to track it. Or I can take the details now. How would you prefer?",
 pcm="I dey sorry well well say your experience no good — e matter to us, and go make sure the right people hear am and act. Fit submit am here for under one minute, and go collect number to track am. Or I fit take the details now. Which one you prefer?",
 cta="Tap 'Make a Complaint', or just tell me what happened in your own words."),
dict(cat="complaints", intent="complaint_status", kw=[
    "complaint status","track complaint","my complaint","where is my complaint","complaint update",
    "has my complaint","complaint reference","follow up on complaint"],
 en="Let's get you an update. Pop your complaint reference and phone number into the status page and you'll see exactly where it stands. If it's escalated, you'll see that too — and the team is held to a strict response clock. Shall I open it for you?",
 pcm="Make we get you update. Put your complaint number and phone for the status page, go see exactly where e stand. If e don escalate, go see am too — and the team get strict clock to respond. Make I open am for you?",
 cta="Say 'status' and I'll take you straight to the tracker."),

# ---------------------------------------------------------------- EMERGENCY & TRIAGE
dict(cat="emergency", intent="emergency_general", kw=[
    "emergency","accident","urgent","help now","emergency room","a and e","casualty","injury","bleeding",
    "crash","faint","unconscious","severe pain","emergency care"],
 en="Please don't wait — come straight to our Accident & Emergency unit; it's open 24/7 and the team is ready for you right now. If the person can't be moved, call an ambulance immediately. Can I alert the A&E desk that you're on your way?",
 pcm="Abeg no wait o — come straight our A&E; e dey open 24/7 and the team don ready for you now now. If the person no fit move, call ambulance immediately. Make I tell A&E desk say you dey come?",
 cta="Head in now — I'll let the team expect you."),
dict(cat="emergency", intent="emergency_chest", kw=[
    "chest pain","heart","difficulty breathing","can't breathe","shortness of breath","stroke","numb face",
    "sudden weakness","collapse","heavy chest","crushing chest"],
 en="This sounds like it needs urgent medical attention — please treat it as an emergency. Come to A&E immediately or call an ambulance now; do not drive yourself if you feel unwell. Our team is ready for you. I'm staying with you — are you able to get moving now?",
 pcm="This one na urgent o — abeg treat am as emergency. Come A&E immediately or call ambulance now now; no drive yourself if you no feel fine. Our team don ready. I dey with you — you fit move now?",
 cta="Please go now — I'll alert the emergency team right away."),
dict(cat="triage", intent="triage_explain", kw=[
    "triage","what is triage","why am i waiting","waiting long","queue at emergency","sorting patients",
    "who gets seen first","priority"],
 en="Totally understand — waiting is the hardest part, and I appreciate your patience. Triage means the most critical patients are seen first for everyone's safety, which is why waits can vary. Your turn is coming, and I've noted your wait. Can I get you a seat or water meanwhile?",
 pcm="I understand o — waiting na the hardest part, and I appreciate your patience. Triage mean say the ones wey dey critical dem go see first for everybody safety, na why waiting fit change. Your turn dey come, and I don note your wait. Make I find you seat or water meanwhile?",
 cta="If you feel worse while waiting, tell any staff immediately — they'll fast-track you."),

# ---------------------------------------------------------------- ADMISSION & DISCHARGE
dict(cat="admission", intent="admission_process", kw=[
    "admission","admit","being admitted","how does admission","admission process","stay overnight",
    "getting admitted","ward admission"],
 en="We'll make admission as smooth as possible for you. Once your doctor recommends it, the desk handles your folder and ward placement, and we'll explain everything before you settle in. A family member can stay close during the process. Would you like me to check what you should bring?",
 pcm="Go make admission smooth for you. Once your doctor recommend am, desk go handle your folder and ward, and dem go explain everything before you settle. Family member fit stay near during the process. You wan make I check wetin you suppo carry?",
 cta="Say 'bring' and I'll list exactly what to pack."),
dict(cat="admission", intent="visiting_hours", kw=[
    "visiting hours","visit a patient","when can i visit","visitation","see a patient","ward visiting",
    "can i visit","visitors allowed"],
 en="We love involved families — visiting hours are usually 10am to 7pm daily, with a limit of two visitors at a time so patients rest well. The ICU has shorter, guided windows for safety. Who are you visiting? I'll give you the exact window for their ward.",
 pcm="We dey love family wey dey involved o — visiting hours na usually 10am to 7pm every day, with two visitors at a time so patient go fit rest well. ICU get shorter window for safety. Who you dey visit? Go give you the exact window for their ward.",
 cta="Tell me the ward and I'll confirm the best time to come."),
dict(cat="discharge", intent="discharge_process", kw=[
    "discharge","going home","leaving hospital","discharge process","when will i be discharged",
    "getting out","released"],
 en="We're as excited as you are to get you home! Discharge happens once your care team confirms you're ready; the desk will settle your bill and hand over your papers and any follow-up dates. Would you like me to arrange your follow-up before you leave?",
 pcm="We dey happy like you say you dey go home! Discharge go happen once your care team confirm say you don ready; desk go settle your bill and give you your papers and follow-up dates. You wan make I arrange your follow-up before you leave?",
 cta="Say 'follow-up' and I'll lock in your review date now."),
dict(cat="discharge", intent="aftercare", kw=[
    "after discharge","care at home","recovering at home","post discharge","wound care at home",
    "what to do at home","recovery tips","after surgery care"],
 en="Recovering well at home is our shared goal. Follow your discharge sheet closely, take medicines exactly as written, and keep your follow-up date. If anything worries you — fever, swelling, or unusual pain — come back or call us; we'd rather see you early. Shall I set a follow-up reminder for you?",
 pcm="Make you recover well for home na our goal. Follow your discharge sheet well, take your medicine exactly as dem write am, and keep your follow-up date. If anything worry you — fever, swelling, or pain wey no normal — come back or call us; we prefer make we see you early. Make I set follow-up reminder for you?",
 cta="Want me to send you a gentle reminder the day before your review?"),

# ---------------------------------------------------------------- FOLLOW-UP
dict(cat="followup", intent="followup_book", kw=[
    "follow up","follow-up","review appointment","come back for check","post treatment check",
    "book follow up","review date","next visit"],
 en="Keeping your follow-up is one of the best things you can do for your health — well done for staying on top of it. I can book your review right now; just tell me the department and a day that suits you. Mornings tend to be quieter if that helps.",
 pcm="Make you keep your follow-up na one of the best thing you fit do for your health — well done! I fit book your review now now; just tell me the department and the day wey suit you. Morning usually calm if e go help.",
 cta="Tell me your preferred day and I'll grab the slot for you."),
]
