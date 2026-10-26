# ErgoCare — Hack for Social Cause submission kit

Theme: **Healthcare, Wellbeing & Service Delivery** (preventive care, mental health).
Judged on: Relevance · Technical Strength · Functionality · Creativity · Social Cause Impact · Presentation & Team Synergy.
Registration & submission window closes **15 October 2026**; state rounds run 16 Oct – 30 Nov 2026.

## 1. Submission checklist

- [ ] Every team member registered individually on the MY Bharat portal
- [ ] **Deck**: 6–7 slides, PDF or PPT, **≤ 10 MB**
- [ ] **Demo video**: 3–5 min, **720p or better, ≤ 80 MB**
- [ ] **Public GitHub repo**: README renders, screenshots show, no secrets committed (`git ls-files | findstr /i ".env ergocare.db secrets.h"` returns nothing)
- [ ] Team details, self-certification, ID proof
- [ ] Hindi + Kannada text reviewed by native speakers (`public/i18n.js`)
- [ ] Backend redeployed with **new** `ADMIN_USERNAME` / `ADMIN_PASSWORD` (the old password is in the public git history)
- [ ] Pilot data collected (even 10–15 people) — real numbers beat claims

## 2. Deck outline (7 slides)

The portal asks for Problem Definition on slides 1–2, Solution Overview on slides 3–4,
Impact & Scalability on slide 5, and Team & Implementation plus AI-use disclosure on
slides 6–7. Use the official IIT Bombay template from the submission page when available.

| # | Slide | What goes on it |
|---|---|---|
| 1 | **Problem & local context** | Define one specific group and setting the team has observed (for example, students in a college computer lab). Describe the ergonomic screening gap using your own interviews/observations; do not invent prevalence figures. |
| 2 | **Who is affected & why current approaches miss them** | Name the intended users and local barriers to noticing or discussing discomfort. Distinguish the problem you observed from assumptions that still need validation. |
| 3 | **Solution: ErgoCare** | “What you report + what optional body signals show.” A 40-question screening in English, Hindi or Kannada; typed or spoken answers; optional ESP32 wearable; personalised, rule-based guidance. |
| 4 | **Working prototype & technical design** | Show the real flow and report. Optional wearable: ESP32, pulse, skin response and posture; a personal 60-second baseline. Questionnaire and sensor scores combine 60:40 when wearable data is available. MiniLM helps match free-form answers to options; it does not predict health risk. |
| 5 | **Impact, scale & evidence so far** | Indicative wearable parts cost: approximately ₹1,000–1,700 (replace with the team’s actual bill of materials). Report the held-out English answer-matcher result accurately: 17/20 examples (85%)—not clinical accuracy. No clinical validation or measured health outcomes yet. Propose a consent-based pilot and metrics such as usability, completion, language matching and physiotherapist review. |
| 6 | **Implementation & team** | Give each member’s real role. Show a staged plan: usability and language review → small supervised pilot → review with qualified health professionals → iterate before any wider deployment. |
| 7 | **AI-use disclosure & next step** | State the AI tools actually used, what they helped create, and the team’s honest estimate of AI-assisted/generated work in the final submission. Name what remains rule-based and unvalidated; end with a concrete pilot or partnership ask. |

## 3. Demo video script (~4 min)

| Time | Shot | Say |
|---|---|---|
| 0:00–0:25 | Team on camera; show intended setting | Introduce the team, local user group and observed problem. |
| 0:25–0:50 | Show registration and consent; choose a language | Explain what information is collected, why consent matters and that this is screening—not diagnosis. |
| 0:50–1:20 | Show wearable and sensor checklist | Name the pulse, skin-response and posture sensors. State that hardware cost is an estimate unless you have the actual bill. |
| 1:20–1:40 | Start baseline (briefly time-lapse the real 60 seconds) | Explain that readings are compared with the participant’s own baseline, not a population norm. |
| 1:40–2:35 | Answer several questions; show voice confirmation and live posture warning | Demonstrate typed fallback, spoken-answer matching and participant confirmation. Do not stage a health result as real pilot data. |
| 2:35–3:15 | Show the completed report and optional wearable insights | Explain the transparent score and practical next steps. Clearly call any sample screen values illustrative. |
| 3:15–3:40 | Show architecture or code repository briefly | Point out the working pieces and distinguish rule-based screening from MiniLM answer matching. |
| 3:40–4:00 | Team together; show one pilot metric and next milestone | Share only measured evidence; state that clinical validation is future work and ask for a supervised pilot partner. |

Record at 1080p (Windows: Win + Alt + R, or OBS). Keep the file under 80 MB (HandBrake "Fast 720p30" if needed).

## 4. Stage demo runbook

**Night before**
- Charge laptop; pack USB cable **and a spare**; tape/hot-glue the jumper wires.
- Run `start_demo.bat`, do one full session, then `scripts\verify_wearable.py` → 35/35 while someone wears the band and leans forward when asked (22/23 with no band connected).
- Have the demo video on the laptop **and** a phone, in case everything fails.

**At the table (5 min before)**
1. Plug in the ESP32 → `start_demo.bat` (three windows + browser open).
2. Check the connect screen shows **Connected · ERGO-01** and all four checks turn green on your own hand.
3. Voice needs internet → phone hotspot; otherwise use typed mode.

**If the hardware fails** → close the "wearable" window, run `start_demo.bat demo` (or `firmware\demo_simulator.py`), and **say it is the demo simulator** (it shows as DEMO-01). Keys: `s` slouch · `u` upright · `t` stress · `c` calm · `m` move.

**The 2-minute live demo**
1. Judge wears the band → 60 s baseline (explain the personal-baseline idea while it runs).
2. Answer 3–4 questions by voice in Hindi or Kannada → "Understood as…".
3. Judge leans forward 10 s → red warning. Quick mental maths (17 × 13) → stress rises.
4. Finish (tap through remaining questions) → report → Hidden stress / posture insight → PDF.

## 5. Questions judges will likely ask — honest answers

| Question | Answer |
|---|---|
| Is this AI/ML? | MiniLM helps match free-form answers to questionnaire options; on the documented held-out English set it matched 17 of 20 examples (85%). Risk scoring uses transparent prototype rules, not a trained clinical prediction model. |
| How accurate is the stress / posture measurement? | The sensors measure real physiological changes relative to each person's own baseline. They are low-cost, not medical grade; our next step is a validation pilot against physiotherapist assessment. |
| Why is it a social cause? | It explores a lower-cost, multilingual route to preventive ergonomic screening that could be piloted through colleges or community health programmes. The hardware cost is an estimate; impact and access still need field validation. |
| What about privacy? | Server-enforced consent, protected admin login, delete-on-request, nothing sensitive in the code. |
| How will it scale? | One laptop + one band per camp; web backend already deployable (Render/Vercel); bands can be shared after cleaning. |
| What did you test? | Show `verify_wearable.py` (35/35 with the band worn), `eval_matcher.py` table, and your pilot numbers. |

Avoid claims you cannot show on screen (e.g. "clinically validated", "99% accurate", participant numbers without the data).
