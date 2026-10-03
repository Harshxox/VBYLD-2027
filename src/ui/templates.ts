import { categoryLabels, questions } from '../data/questions'
import type { AssessmentSession, InputMode } from '../types/assessment'

export type AssessmentViewModel = {
  mode: InputMode
  currentIndex: number
  session: AssessmentSession | null
  selectedOption: string
  answerValue: string
  recording: boolean
  notice: string
  canContinue: boolean
  saving: boolean
}

export function escapeHtml(value: string): string {
  return value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;')
}

// ── Loading ───────────────────────────────────────────────────────────────────

export function renderLoading(message: string): string {
  if (message.includes('report')) {
    return `
      <div class="loading-screen" style="justify-content: flex-start; padding-top: 60px;">
        <div style="max-width: 800px; width: 100%; display: grid; gap: 30px;">
          <div style="height: 40px; width: 40%; background: #e2e8f0; border-radius: 8px; animation: pulse 1.5s infinite"></div>
          <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px;">
            <div style="height: 200px; background: #e2e8f0; border-radius: 12px; animation: pulse 1.5s infinite 0.2s"></div>
            <div style="height: 200px; background: #e2e8f0; border-radius: 12px; animation: pulse 1.5s infinite 0.4s"></div>
          </div>
          <div style="height: 120px; background: #e2e8f0; border-radius: 12px; animation: pulse 1.5s infinite 0.6s"></div>
          <p class="loader-msg" style="text-align: center; margin-top: 20px;">${escapeHtml(message)}</p>
        </div>
      </div>
    `
  }
  return `
    <div class="loading-screen">
      <div class="loader-wrap">
        <svg class="loader-ring" viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">
          <circle cx="50" cy="50" r="42" fill="none" stroke="#e8f4f1" stroke-width="8"/>
          <circle cx="50" cy="50" r="42" fill="none" stroke="#087f8c" stroke-width="8"
            stroke-dasharray="264" stroke-dashoffset="180"
            stroke-linecap="round" class="spin-arc"/>
        </svg>
        <div class="loader-logo">EC</div>
      </div>
      <h2 class="loader-title">ErgoCare AI</h2>
      <p class="loader-msg">${escapeHtml(message)}</p>
    </div>
  `
}

// ── Landing ───────────────────────────────────────────────────────────────────

export function renderLanding(errorMessage: string | null = null): string {
  return `
    <main class="shell landing">
      <section class="intro">
        <div class="brand-row">
          <span class="brand-mark">EC</span>
          <span>ErgoCare AI</span>
        </div>
        <h1>Voice-enabled ergonomic stress assessment for faculty wellness.</h1>
        <p class="lead">Collect typed or spoken answers, store each session as one structured record, and generate a clear ergonomic risk report with visual recommendations.</p>
        ${errorMessage ? `<div class="error-banner">${escapeHtml(errorMessage)}</div>` : ''}
        <div class="mode-grid">
          <button class="mode-card" data-action="start-typed">
            <span class="mode-icon">Aa</span>
            <span>
              <strong>Type Answers</strong>
              <small>Use option chips or write a custom answer for every prompted question.</small>
            </span>
          </button>
          <button class="mode-card accent" data-action="start-voice">
            <span class="mode-icon">Mic</span>
            <span>
              <strong>Speak Answers</strong>
              <small>Record each answer, keep its audio reference, and capture a transcript.</small>
            </span>
          </button>
        </div>
      </section>
      <section class="product-visual" aria-label="ErgoCare product preview">
        <div class="phone-frame">
          <div class="phone-top"></div>
          <div class="mini-card">
            <span>Overall risk</span>
            <strong>72%</strong>
            <div class="gauge"><span style="width:72%"></span></div>
          </div>
          <div class="body-map">
            <span class="head"></span>
            <span class="torso"></span>
            <span class="arm left"></span>
            <span class="arm right"></span>
            <span class="leg left"></span>
            <span class="leg right"></span>
            <b class="hotspot neck"></b>
            <b class="hotspot wrist"></b>
            <b class="hotspot back"></b>
          </div>
          <div class="mini-bars">
            <span style="height:58%"></span>
            <span style="height:82%"></span>
            <span style="height:45%"></span>
            <span style="height:68%"></span>
            <span style="height:76%"></span>
          </div>
        </div>
      </section>
    </main>
  `
}

// ── Assessment ────────────────────────────────────────────────────────────────

export function renderAssessment(view: AssessmentViewModel): string {
  const question = questions[view.currentIndex]
  const progress = Math.round(((view.currentIndex + 1) / questions.length) * 100)

  return `
    <main class="shell assessment">
      <header class="topbar">
        <div>
          <span class="eyebrow">${view.mode === 'voice' ? 'Voice session' : 'Typed session'}</span>
          <h1>Question ${question.id} of ${questions.length}</h1>
        </div>
        <button class="ghost" data-action="reset">Start over</button>
      </header>
      <section class="question-layout">
        <aside class="progress-panel">
          <div class="progress-ring" style="--progress:${progress}"><span>${progress}%</span></div>
          <p>${categoryLabels[question.category]}</p>
          <div class="storage-note">
            <strong>Session record</strong>
            <span>${view.session?.answers.length ?? 0} answers saved to backend</span>
          </div>
        </aside>
        <section class="question-card">
          <p class="question-text">${escapeHtml(question.text)}</p>
          <div class="option-grid">
            ${question.options.map((option) => `
              <button class="option-chip ${view.selectedOption === option ? 'selected' : ''}" data-option="${escapeHtml(option)}" ${view.saving ? 'disabled' : ''}>
                ${escapeHtml(option)}
              </button>
            `).join('')}
          </div>
          ${view.mode === 'voice' ? renderVoiceAnswer(view) : renderTypedAnswer(view)}
          ${view.notice ? `<p class="notice">${escapeHtml(view.notice)}</p>` : ''}
          ${view.saving ? `<p class="notice saving-note">⏳ Saving to server…</p>` : ''}
          <div class="question-actions">
            <button class="ghost" data-action="previous" ${view.currentIndex === 0 || view.saving ? 'disabled' : ''}>Previous</button>
            <button class="primary" data-action="next" ${view.canContinue && !view.saving ? '' : 'disabled'}>
              ${view.saving ? 'Saving…' : view.currentIndex === questions.length - 1 ? 'Generate Report →' : 'Save & Continue →'}
            </button>
          </div>
        </section>
      </section>
    </main>
  `
}

// ── Results — full redesign ────────────────────────────────────────────────────

export function renderResults(session: AssessmentSession, backendSessionId: string | null): string {
  if (!session.scores || !session.report) return renderLanding()

  const scores = session.scores
  const report = session.report
  const backendReport: any = (session as any)._backendReport

  const level = report.level as 'Low' | 'Moderate' | 'High'
  const levelMeta = {
    Low:      { color: '#059669', bg: '#ecfdf5', label: 'Low Risk',      emoji: '✅', tagline: 'Your workspace habits are healthy. Minor tune-ups can keep you protected long-term.' },
    Moderate: { color: '#d97706', bg: '#fffbeb', label: 'Moderate Risk', emoji: '⚠️', tagline: 'Some habits need attention. Act now to prevent these from becoming chronic conditions.' },
    High:     { color: '#dc2626', bg: '#fef2f2', label: 'High Risk',     emoji: '🚨', tagline: 'Significant ergonomic stress detected. Immediate changes are strongly recommended.' },
  }[level]

  const overallRisk = scores.overallRisk
  // SVG ring math (r=54, circumference=339.3)
  const circ = 339.3
  const offset = circ - (overallRisk / 100) * circ

  const categoryData = [
    { label: 'Posture & Movement', key: 'postureRisk',       icon: '🧍', score: scores.postureRisk,
      what: 'How well your body is aligned and supported while you work.',
      tip: 'Raise your screen to eye level. Sit with your back supported and feet flat.' },
    { label: 'Eye Strain',         key: 'eyeStrain',         icon: '👁️', score: scores.eyeStrain,
      what: 'Fatigue and dryness caused by prolonged screen exposure.',
      tip: 'Follow the 20-20-20 rule: every 20 min, look 20 feet away for 20 seconds.' },
    { label: 'Workload Stress',    key: 'workloadStress',    icon: '🧠', score: scores.workloadStress,
      what: 'Mental and physical overload from continuous work without breaks.',
      tip: 'Block 5-minute breaks every 45 minutes. Protect lunch from screen use.' },
    { label: 'Body Discomfort',    key: 'musculoskeletalRisk', icon: '💪', score: scores.musculoskeletalRisk,
      what: 'Pain or tension in neck, shoulders, back, wrists or legs.',
      tip: 'Add two daily stretch sessions focusing on neck rolls, shoulder shrugs, and wrist circles.' },
    { label: 'Recovery & Sleep',   key: 'recoveryRisk',      icon: '🌙', score: scores.recoveryRisk,
      what: 'How well your body restores itself after work-related stress.',
      tip: 'Maintain a consistent sleep window and limit screens 1 hour before bed.' },
  ]

  // Prevention tips — 3D card style
  const preventionTips = [
    { icon: '🖥️', title: 'Screen at Eye Level',  desc: 'Position your monitor so the top edge aligns with your eyes. This prevents chronic neck flexion and upper back strain.', color: '#087f8c' },
    { icon: '⏱️', title: 'Break Every 45 Min',   desc: 'Set a recurring alarm. Stand up, walk 2 minutes, stretch your neck and wrists. Your spine decompresses and blood returns to your legs.', color: '#4564d6' },
    { icon: '💧', title: 'Hydrate 1.5L Daily',   desc: 'Dehydration amplifies fatigue and reduces concentration. Keep a bottle on your desk as a visual cue. Sip every 30 minutes.', color: '#059669' },
    { icon: '🌿', title: '20-20-20 Eye Rule',    desc: 'Every 20 minutes, focus on something 20 feet away for 20 seconds. This resets your eye muscles and reduces dry, burning eyes.', color: '#7c3aed' },
    { icon: '🪑', title: 'Chair Setup Check',    desc: 'Elbows at 90°, lumbar support at the small of your back, feet flat on the floor. Adjust once and your posture improves automatically.', color: '#dc2626' },
    { icon: '🏃', title: 'Move During Commute',  desc: 'Even a 10-minute walk before or after work resets cortisol, reduces stiffness and improves overall recovery quality measurably.', color: '#d97706' },
  ]

  const actionPlan = backendReport?.action_plan ?? report.actionPlan
  const topFactors = backendReport?.top_factors ?? report.topFactors
  const detailedFindings = backendReport?.detailed_findings ?? []
  const positiveHabits = backendReport?.positive_habits ?? []

  return `
    <div class="results-page">

      <!-- HERO BAND -->
      <div class="results-hero" style="background:${levelMeta.bg};border-bottom:3px solid ${levelMeta.color}20;">
        <div class="results-hero-inner">
          <div class="hero-left">
            <div class="level-badge" style="background:${levelMeta.color}15;color:${levelMeta.color};border:1.5px solid ${levelMeta.color}40;">
              ${levelMeta.emoji} ${levelMeta.label}
            </div>
            <h1 class="hero-title" style="color:${levelMeta.color};">
              Overall Risk Score: ${overallRisk.toFixed(1)}%
            </h1>
            <p class="hero-tagline">${levelMeta.tagline}</p>
            <div class="hero-actions">
              ${backendSessionId ? `<button class="btn-primary" data-action="download-pdf" style="background:${levelMeta.color};">⬇ Download PDF Report</button>` : ''}
              <button class="btn-ghost" data-action="reset">New Session</button>
              <button class="btn-ghost" data-action="export">Export JSON</button>
            </div>
          </div>
          <div class="hero-ring-wrap">
            <svg class="risk-ring" viewBox="0 0 120 120" xmlns="http://www.w3.org/2000/svg">
              <circle cx="60" cy="60" r="54" fill="none" stroke="#e5e7eb" stroke-width="10"/>
              <circle cx="60" cy="60" r="54" fill="none"
                stroke="${levelMeta.color}" stroke-width="10"
                stroke-linecap="round"
                stroke-dasharray="${circ}"
                stroke-dashoffset="${circ}"
                class="ring-fill"
                style="--target-offset:${offset};"
                transform="rotate(-90 60 60)"/>
              <text x="60" y="55" text-anchor="middle" font-size="20" font-weight="800" fill="${levelMeta.color}">${overallRisk.toFixed(0)}%</text>
              <text x="60" y="72" text-anchor="middle" font-size="8" fill="#6b7280">Overall Risk</text>
            </svg>
            <p class="ring-label">Composite score across<br>5 ergonomic categories</p>
          </div>
        </div>
      </div>

      <div class="results-body">

        <!-- CATEGORY CARDS -->
        <section class="section">
          <h2 class="section-title">📊 Category Breakdown</h2>
          <p class="section-sub">Each category shows your risk level, what it means, and one key action you can take today.</p>
          <div class="cat-grid">
            ${categoryData.map(cat => {
              const lv = cat.score >= 70 ? 'High' : cat.score >= 40 ? 'Moderate' : 'Low'
              const c  = cat.score >= 70 ? '#dc2626' : cat.score >= 40 ? '#d97706' : '#059669'
              const bg = cat.score >= 70 ? '#fef2f2' : cat.score >= 40 ? '#fffbeb' : '#ecfdf5'
              return `
              <div class="cat-card" style="border-top:4px solid ${c};">
                <div class="cat-header">
                  <span class="cat-icon">${cat.icon}</span>
                  <div>
                    <div class="cat-name">${cat.label}</div>
                    <div class="cat-badge" style="background:${bg};color:${c};">${lv} — ${cat.score.toFixed(0)}%</div>
                  </div>
                  <span class="cat-score" style="color:${c};">${cat.score.toFixed(0)}%</span>
                </div>
                <div class="cat-bar-track"><div class="cat-bar-fill" style="width:${cat.score}%;background:${c};"></div></div>
                <p class="cat-what"><strong>What this means:</strong> ${cat.what}</p>
                <div class="cat-tip" style="border-left:3px solid ${c};background:${bg};">
                  <strong>💡 Quick fix:</strong> ${cat.tip}
                </div>
              </div>`
            }).join('')}
          </div>
        </section>

        <!-- PREVENTION — 3D CARDS -->
        <section class="section">
          <h2 class="section-title">🛡️ Prevention Plan</h2>
          <p class="section-sub">Six evidence-based habits that directly reduce ergonomic risk — start with the one matching your highest score.</p>
          <div class="prevention-grid">
            ${preventionTips.map((tip, i) => `
              <div class="prev-card" style="--card-color:${tip.color};">
                <div class="prev-card-inner">
                  <div class="prev-num">0${i + 1}</div>
                  <div class="prev-icon">${tip.icon}</div>
                  <h3 class="prev-title">${tip.title}</h3>
                  <p class="prev-desc">${tip.desc}</p>
                  <div class="prev-shine"></div>
                </div>
              </div>
            `).join('')}
          </div>
        </section>

        <!-- ACTION PLAN -->
        <section class="section">
          <h2 class="section-title">📋 Your Personal Action Plan</h2>
          <p class="section-sub">Prioritised steps based on your specific answers — ranked from most urgent to maintenance.</p>
          <div class="action-list">
            ${actionPlan.map((item: string, i: number) => {
              const urgent = item.startsWith('⚠') || item.startsWith('Address')
              return `
              <div class="action-item ${urgent ? 'action-urgent' : ''}">
                <div class="action-num" style="background:${urgent ? '#dc2626' : '#087f8c'};">${i + 1}</div>
                <p>${escapeHtml(item)}</p>
              </div>`
            }).join('')}
          </div>
        </section>

        <!-- FINDINGS + POSITIVES side by side -->
        <div class="two-col">
          ${detailedFindings.length ? `
          <section class="section finding-panel">
            <h2 class="section-title">🔍 Detailed Findings</h2>
            <p class="section-sub">What your answers specifically revealed.</p>
            <ul class="finding-list">
              ${detailedFindings.map((f: string) => `<li>${escapeHtml(f)}</li>`).join('')}
            </ul>
          </section>` : ''}

          ${positiveHabits.length ? `
          <section class="section positive-panel">
            <h2 class="section-title">✅ What You're Doing Right</h2>
            <p class="section-sub">Habits worth keeping — reinforce these daily.</p>
            <ul class="positive-list">
              ${positiveHabits.map((p: string) => `<li>${escapeHtml(p)}</li>`).join('')}
            </ul>
          </section>` : ''}
        </div>

        <!-- TOP RISK FACTORS -->
        ${topFactors?.length ? `
        <section class="section">
          <h2 class="section-title">⚡ Top Risk Factors</h2>
          <div class="factor-row">
            ${topFactors.map((f: string, i: number) => {
              const parts = f.split(':')
              const name  = parts[0]?.trim() ?? f
              const val   = parseFloat(parts[1] ?? '0')
              const c = val >= 70 ? '#dc2626' : val >= 40 ? '#d97706' : '#059669'
              return `
              <div class="factor-chip">
                <span class="factor-rank">#${i + 1}</span>
                <span class="factor-name">${escapeHtml(name)}</span>
                <span class="factor-score" style="color:${c};">${isNaN(val) ? '' : val.toFixed(0) + '%'}</span>
              </div>`
            }).join('')}
          </div>
        </section>` : ''}

        <!-- FOOTER CTA -->
        <div class="results-footer">
          <div class="footer-cta">
            <h3>Download your full report</h3>
            <p>A professionally formatted PDF including all scores, findings, and your personalised action plan — ready to share with HR or your occupational health team.</p>
            ${backendSessionId
              ? `<button class="btn-primary btn-large" data-action="download-pdf">⬇ Download PDF Report</button>`
              : '<p style="color:#6b7280;font-size:0.85rem;">PDF available after backend session completes.</p>'
            }
          </div>
          <p class="disclaimer">This report is generated by ErgoCare AI and is for informational purposes only. Consult a qualified healthcare or occupational health professional for clinical advice.</p>
          ${backendSessionId ? `<p class="session-ref">Session ID: <code>${escapeHtml(backendSessionId)}</code></p>` : ''}
        </div>

      </div>
    </div>
  `
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function renderTypedAnswer(view: AssessmentViewModel): string {
  return `
    <label class="answer-field">
      <span>Your answer</span>
      <textarea data-field="typed" placeholder="Type your answer, or pick one of the options above." ${view.saving ? 'disabled' : ''}>${escapeHtml(view.answerValue)}</textarea>
    </label>
  `
}

function renderVoiceAnswer(view: AssessmentViewModel): string {
  return `
    <div class="voice-tools">
      <button class="record-button ${view.recording ? 'recording' : ''}" data-action="record" ${view.saving ? 'disabled' : ''}>
        ${view.recording ? '⏹ Stop Recording' : '🎙 Record Answer'}
      </button>
      <span>${view.recording ? 'Listening now…' : 'One audio clip per question.'}</span>
    </div>
    <label class="answer-field">
      <span>Transcript</span>
      <textarea data-field="transcript" placeholder="Transcript appears here automatically, or type it manually." ${view.saving ? 'disabled' : ''}>${escapeHtml(view.answerValue)}</textarea>
    </label>
  `
}
