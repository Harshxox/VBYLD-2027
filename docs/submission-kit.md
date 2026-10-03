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

| # | Slide | What goes on it |
|---|---|---|
| 1 | **Problem** | Young people and screen workers sit 6–10 h/day; posture pain and stress build up unnoticed. People under-report stress and don't notice slouching. Existing checks need a physiotherapist and are not in local languages. |
| 2 | **Solution** | "What you say + what your body shows." 40-question screening (typed or spoken, EN/HI/KN) + a ≈ ₹1,000–1,700 wearable (heart rate, skin response, posture) → one ErgoCare Index. Screenshot: report with insights. |
| 3 | **Live demo** | Photo/GIF: wearable on a person, live panel, red "Sit up straight" warning, "Hidden stress" card. |
| 4 | **How it works** | Architecture diagram (README). Personal 60 s baseline; transparent scoring table; MiniLM sentence-embedding model for spoken answers (70–85% on unseen phrasing, person confirms on screen). |
| 5 | **Social impact** | Low cost, runs on one laptop without Wi-Fi, 3 languages + voice (low literacy / typing barriers), usable by NSS volunteers or college health centres, consent + privacy by design. Who: students, BPO/IT workers, anyone at a screen. |
| 6 | **Validation (honest)** | What you actually measured: pilot size, % with hidden stress / posture blind spot, matcher accuracy table, sensor checks. State plainly: screening tool, not diagnosis; thresholds to be validated with physiotherapists. |
| 7 | **Roadmap + team** | Clinical validation pilot → trained risk model from pilot data → regional-language reports → on-device voice → camp/college rollout. Team names and roles. |

## 3. Demo video script (~4 min)

| Time | Shot | Say |
|---|---|---|
| 0:00–0:30 | Person slouched at a laptop | The problem, in one sentence each: pain, stress, nobody notices, checks are expensive and English-only. |
| 0:30–0:50 | Wearable close-up | "₹1,500 of sensors: pulse, skin response, posture." |
| 0:50–1:20 | Register (consent box), choose हिन्दी / ಕನ್ನಡ, connect screen turning green | Consent and language first; checklist shows every sensor is working. |
| 1:20–1:50 | 60 s baseline (speed up) | "Everything is compared with *your own* resting values." |
| 1:50–2:40 | Answer questions by voice; slouch → red warning; mental maths → stress rises | "Understood as…" confirmation; live warnings instead of a buzzer. |
| 2:40–3:30 | Report: ErgoCare Index, Hidden stress / Posture blind spot, graphs, PDF | "Answers said low stress; the body disagreed." |
| 3:30–3:50 | Admin panel + CSV | How a college health centre would use it. |
| 3:50–4:10 | Impact + roadmap | Cost, languages, offline, next step: validation pilot. |

Record at 1080p (Windows: Win + Alt + R, or OBS). Keep the file under 80 MB (HandBrake "Fast 720p30" if needed).

## 4. Stage demo runbook

**Night before**
- Charge laptop; pack USB cable **and a spare**; tape/hot-glue the jumper wires.
- Run `start_demo.bat`, do one full session, then `scripts\verify_wearable.py` → 25/25.
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
| Is this AI/ML? | Yes for understanding spoken answers (MiniLM sentence embeddings, measured 70–85% on unseen phrasing). The risk scores are transparent expert rules on purpose — explainable, and we have no labelled outcome data yet to train a model. |
| How accurate is the stress / posture measurement? | The sensors measure real physiological changes relative to each person's own baseline. They are low-cost, not medical grade; our next step is a validation pilot against physiotherapist assessment. |
| Why is it a social cause? | Cheap, offline, voice + regional languages, runs by a volunteer — preventive screening for people who never see an ergonomist. |
| What about privacy? | Server-enforced consent, protected admin login, delete-on-request, nothing sensitive in the code. |
| How will it scale? | One laptop + one band per camp; web backend already deployable (Render/Vercel); bands can be shared after cleaning. |
| What did you test? | Show `verify_wearable.py` (25/25), `eval_matcher.py` table, and your pilot numbers. |

Avoid claims you cannot show on screen (e.g. "clinically validated", "99% accurate", participant numbers without the data).
