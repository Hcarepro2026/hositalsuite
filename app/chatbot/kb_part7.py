"""GLOBAL MASTER DIALOGUE LIBRARY — Part 7 (handoff + everyday Naija phrasings; clears 1,000)."""

KB = [
dict(cat="engagement", intent="human_handoff", kw=[
    "talk to a human","speak to a person","real person","agent","customer care","operator","human being",
    "connect me to someone","i want a person","not a bot","talk to staff","front desk","representative",
    "make i talk to person","give me human"],
 en="Of course — you deserve a human, and I'm happy to bring one in. I've alerted our front desk and a team member will be with you shortly; I'll stay right here too if you need anything meanwhile. Thank you for your patience!",
 pcm="Of course o — you deserve human, and I go happy bring one in. I don alert our front desk and team member go meet you sharp sharp; go still dey here too if you need anything meanwhile. Thank you for your patience!",
 cta="I'm handing you over now — someone is on the way."),
dict(cat="greetings", intent="greet_pidgin", kw=[
    "how far o","howfar","wetin dey sup","how you dey","you dey","na you be bot","abeg hello","make we talk",
    "i dey find help","help me abeg","i need help o","assistance please abeg"],
 en="How far! I'm right here for you — tell me what you need and we'll sort it together, nice and easy. Booking, bills, directions, or anything at all?",
 pcm="How far o! I dey right here for you — tell me wetin you need and go sort am together, nice and easy. Booking, bill, direction, or anything at all?",
 cta="Abeg tell me wetin dey your mind."),
dict(cat="bills", intent="bill_too_high", kw=[
    "this bill is too high","too expensive","overpriced","i cant afford","bill too much","this is expensive",
    "reduce the bill","bill is high","costly"],
 en="I hear you, and I'm not going to brush that aside — cost matters, and we have options. Our billing desk can review the bill line-by-line, discuss a payment plan, and confirm any insurance or discount you qualify for. Shall I set up that review for you?",
 pcm="I hear you, and I no go brush am aside — cost matter, and we get options. Our billing desk fit review the bill line-by-line, discuss payment plan, and confirm any insurance or discount wey you qualify. Make I set up that review for you?",
 cta="Say 'review' and I'll arrange a friendly, no-pressure billing chat."),
dict(cat="operations", intent="where_is_my_doctor", kw=[
    "where is my doctor","my doctor not around","doctor don go","i cant find my doctor","doctor absent",
    "who is covering my doctor","my doctor no dey"],
 en="I understand the worry when your usual doctor isn't around — your care doesn't stop. A covering clinician with full access to your folder is available, and your doctor is briefed on your case. Shall I connect you to the covering doctor now?",
 pcm="I understand the worry when your normal doctor no dey — your care no go stop. Covering clinician wey get full access to your folder dey available, and your doctor dey briefed on your case. Make I connect you to the covering doctor now?",
 cta="I'll link you to the covering clinician right away."),
dict(cat="operations", intent="open_sunday", kw=[
    "open on sunday","sunday hours","are you open sunday","public holiday","open on holiday","sunday clinic"],
 en="Great question — our clinics are closed on Sundays and public holidays, but the emergency unit and admissions run 24/7 every day, and the pharmacy keeps an emergency window. For routine visits, Monday morning is lovely and calm. Shall I book you a weekday slot?",
 pcm="Correct question — our clinic dey close for Sunday and public holiday, but emergency and admission dey run 24/7 every day, and pharmacy keep emergency window. For normal visit, Monday morning dey lovely and calm. Make I book you weekday slot?",
 cta="I'll grab you the calmest weekday slot if you like."),
dict(cat="selfservice", intent="resend_otp", kw=[
    "resend code","code not coming","no code","i didnt get code","otp not received","send code again",
    "code no reach","i no receive code"],
 en="No stress — codes can occasionally be delayed by the network. I've triggered a fresh 6-digit code to your registered phone; it expires in 10 minutes. If it still doesn't arrive in a couple of minutes, try 'forgot password' again or I'll connect you to the desk.",
 pcm="No stress — code fit delay sometimes by network. I don trigger fresh 6-digit code to your phone; e go expire for 10 minutes. If e still no reach for two minutes, try 'forgot password' again or make I connect you to desk.",
 cta="Check your SMS now — and tell me if it lands."),
]
