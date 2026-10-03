import './styles/app.css'
import { questions } from './data/questions'
import { exportSessionJson } from './domain/session'
import { renderAssessment, renderLanding, renderResults, renderLoading } from './ui/templates'
import type { AssessmentSession, InputMode, RecognitionLike, Screen } from './types/assessment'
import {
  apiCreateSession,
  apiSaveAnswer,
  apiUploadAudio,
  apiCompleteSession,
  apiReportPdfUrl,
} from './api/client'

declare global {
  interface Window {
    SpeechRecognition?: new () => RecognitionLike
    webkitSpeechRecognition?: new () => RecognitionLike
  }
}

type AppState = {
  screen: Screen
  mode: InputMode | null
  currentIndex: number
  session: AssessmentSession | null
  backendSessionId: string | null      // ← ID returned by POST /api/sessions
  selectedOption: string
  freeText: string
  transcript: string
  recording: boolean
  recorder: MediaRecorder | null
  recognition: RecognitionLike | null
  audioChunks: BlobPart[]
  notice: string
  saving: boolean                      // ← true while an API call is in-flight
  errorMessage: string | null
}

const app = document.querySelector<HTMLDivElement>('#app')!

const state: AppState = {
  screen: 'landing',
  mode: null,
  currentIndex: 0,
  session: null,
  backendSessionId: null,
  selectedOption: '',
  freeText: '',
  transcript: '',
  recording: false,
  recorder: null,
  recognition: null,
  audioChunks: [],
  notice: '',
  saving: false,
  errorMessage: null,
}

// ── Session start ─────────────────────────────────────────────────────────────

async function startAssessment(mode: InputMode): Promise<void> {
  state.saving = true
  state.errorMessage = null
  renderLoadingScreen('Starting your assessment…')

  const clientInfo = {
    name: (document.querySelector('#reg-name') as HTMLInputElement)?.value || undefined,
    email: (document.querySelector('#reg-email') as HTMLInputElement)?.value || undefined,
    phone: (document.querySelector('#reg-phone') as HTMLInputElement)?.value || undefined,
    age: parseInt((document.querySelector('#reg-age') as HTMLInputElement)?.value || '0') || undefined,
    job: (document.querySelector('#reg-job') as HTMLInputElement)?.value || undefined,
    consent: (document.querySelector('#reg-consent') as HTMLInputElement)?.checked ?? true,
  }

  try {
    const backendSession = await apiCreateSession(mode, clientInfo)
    state.backendSessionId = backendSession.id

    // Build a local session shell (scores/report come from backend on completion)
    state.session = {
      sessionId: backendSession.id,
      inputMode: mode,
      createdAt: backendSession.created_at,
      completedAt: null,
      answers: [],
      scores: null,
      report: null,
    }

    state.mode = mode
    state.currentIndex = 0
    state.screen = 'assessment'
    state.selectedOption = ''
    state.freeText = ''
    state.transcript = ''
    state.notice = mode === 'voice'
      ? 'Voice mode stores one recording and transcript per question.'
      : 'Typed mode stores one text answer per question.'
  } catch (error) {
    state.errorMessage = `Could not reach the backend. Make sure the server is running on http://127.0.0.1:8000\n\n${String(error)}`
    state.screen = 'landing'
  } finally {
    state.saving = false
    render()
  }
}

// ── Answer flow ───────────────────────────────────────────────────────────────

function canContinue(): boolean {
  if (state.saving) return false
  if (state.recording) return false
  if (state.mode === 'typed') return Boolean(state.freeText.trim() || state.selectedOption)
  return Boolean(state.transcript.trim() || state.freeText.trim() || state.selectedOption)
}

async function saveCurrentAnswer(): Promise<void> {
  if (!state.session || !state.mode || !state.backendSessionId) return

  const question = questions[state.currentIndex]
  const typed = state.mode === 'typed'
    ? (state.freeText.trim() || state.selectedOption)
    : state.selectedOption
  const transcript = state.mode === 'voice'
    ? (state.transcript.trim() || state.freeText.trim() || state.selectedOption)
    : null

  state.saving = true
  render()

  try {
    let serverAudioUrl: string | null = null

    // Upload audio first if we have chunks (voice mode)
    if (state.mode === 'voice' && state.audioChunks.length > 0) {
      const blob = new Blob(state.audioChunks, { type: 'audio/webm' })
      const fileName = `session-${state.backendSessionId}-q${question.id}.webm`
      const uploaded = await apiUploadAudio(
        state.backendSessionId,
        question.id,
        blob,
        fileName,
        transcript ?? '',
      )
      serverAudioUrl = uploaded.audio_url
    }

    // Save the answer to the backend
    await apiSaveAnswer(
      state.backendSessionId,
      question.id,
      question.text,
      state.mode === 'typed' ? typed : null,
      transcript,
      serverAudioUrl,
    )

    // Also keep a local copy for rendering the progress count
    state.session.answers = state.session.answers
      .filter((item) => item.questionId !== question.id)
      .concat({
        questionId: question.id,
        question: question.text,
        typedAnswer: state.mode === 'typed' ? typed : null,
        transcript,
        audioUrl: serverAudioUrl,
        audioFileName: null,
      })
      .sort((a, b) => a.questionId - b.questionId)

    // Last question → complete the session
    if (state.currentIndex === questions.length - 1) {
      await finishSession()
    } else {
      moveToNextQuestion()
    }
  } catch (error) {
    // Bug 8 fix: use errorMessage (persistent banner) not notice (ephemeral, cleared on next question)
    state.errorMessage = `Save failed: ${String(error)}`
  } finally {
    state.saving = false
    render()
  }
}

async function finishSession(): Promise<void> {
  if (!state.session || !state.backendSessionId) return

  renderLoadingScreen('Analysing your answers and generating your ergonomic report…')

  try {
    const result = await apiCompleteSession(state.backendSessionId)
    const scores = result.scores
    const report = result.report

    // Map backend snake_case → frontend camelCase
    state.session.completedAt = new Date().toISOString()
    state.session.scores = {
      postureRisk: scores.posture_risk,
      eyeStrain: scores.eye_strain,
      workloadStress: scores.workload_stress,
      musculoskeletalRisk: scores.musculoskeletal_risk,
      recoveryRisk: scores.recovery_risk,
      overallRisk: scores.overall_risk,
    }
    state.session.report = {
      level: report.level,
      topFactors: report.top_factors,
      actionPlan: report.action_plan,
    }

    // Store extra backend fields for richer rendering
    ;(state.session as any)._backendReport = report

    state.screen = 'results'
  } catch (error) {
    // Bug 8 fix: use errorMessage (persistent banner) so the user sees it even if they click quickly
    state.errorMessage = `Could not complete session: ${String(error)}`
    state.screen = 'assessment'
  }
}

// ── Navigation ────────────────────────────────────────────────────────────────

function moveToNextQuestion(): void {
  state.currentIndex += 1
  state.selectedOption = ''
  state.freeText = ''
  state.transcript = ''
  state.audioChunks = []
  state.notice = ''
}

function moveToPreviousQuestion(): void {
  if (state.currentIndex === 0) return
  state.currentIndex -= 1
  const previous = state.session?.answers.find(
    (item) => item.questionId === questions[state.currentIndex].id,
  )
  state.selectedOption = previous?.typedAnswer ?? previous?.transcript ?? ''
  // Bug 10 fix: restore the correct field based on current mode
  // In voice mode, typedAnswer is always null — use transcript instead
  state.freeText = state.mode === 'typed'
    ? (previous?.typedAnswer ?? '')
    : (previous?.transcript ?? '')
  state.transcript = previous?.transcript ?? ''
  if (!previous?.audioUrl) {
    state.audioChunks = []
  }
  render()
}

// ── Recording ─────────────────────────────────────────────────────────────────

async function toggleRecording(): Promise<void> {
  if (state.recording) {
    stopRecording()
    return
  }
  if (!navigator.mediaDevices?.getUserMedia) {
    state.notice = 'This browser does not expose microphone recording. Type the spoken answer in the transcript box.'
    render()
    return
  }
  try {
    await startRecording()
  } catch {
    state.notice = 'Microphone permission was blocked. You can still type a transcript for this voice-mode answer.'
    render()
  }
}

async function startRecording(): Promise<void> {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
  state.audioChunks = []
  const recorder = new MediaRecorder(stream)
  recorder.ondataavailable = (event) => {
    if (event.data.size > 0) state.audioChunks.push(event.data)
  }
  recorder.onstop = () => {
    stream.getTracks().forEach((track) => track.stop())
  }
  startSpeechRecognition()
  state.recorder = recorder
  state.recording = true
  recorder.start()
  render()
}

function startSpeechRecognition(): void {
  const Recognition = window.SpeechRecognition ?? window.webkitSpeechRecognition
  if (!Recognition) {
    state.notice = 'Recording is active. Live speech-to-text is unavailable in this browser — type the transcript manually.'
    return
  }
  const recognition = new Recognition()
  recognition.continuous = true
  recognition.interimResults = true
  
  const langMap: Record<string, string> = { en: 'en-IN', hi: 'hi-IN', kn: 'kn-IN' }
  recognition.lang = langMap[document.documentElement.lang || 'en'] || 'en-IN'

  recognition.onresult = (event) => {
    state.transcript = Array.from(event.results)
      .map((result) => result[0].transcript)
      .join(' ')
    render()
  }
  recognition.onend = () => {
    if (state.recording) recognition.start()
  }
  state.recognition = recognition
  recognition.start()
}

function stopRecording(): void {
  state.recorder?.stop()
  state.recognition?.stop()
  state.recording = false
  state.notice = 'Recording stopped. Review or edit the transcript before continuing.'
  render()
}

// ── Reset ─────────────────────────────────────────────────────────────────────

function resetApp(): void {
  // Bug 9 fix: stop mic + recognition before clearing — prevents open mic track after "Start over"
  if (state.recording) {
    state.recorder?.stop()
    state.recognition?.stop()
    state.recording = false
  }
  state.screen = 'landing'
  state.mode = null
  state.session = null
  state.backendSessionId = null
  state.currentIndex = 0
  state.selectedOption = ''
  state.freeText = ''
  state.transcript = ''
  state.audioChunks = []
  state.notice = ''
  state.saving = false
  state.errorMessage = null
  render()
}

// ── Render ────────────────────────────────────────────────────────────────────

function renderLoadingScreen(message: string): void {
  app.innerHTML = renderLoading(message)
}

function render(): void {
  if (state.screen === 'landing') {
    app.innerHTML = renderLanding(state.errorMessage)
    return
  }

  if (state.screen === 'results' && state.session) {
    app.innerHTML = renderResults(state.session, state.backendSessionId)
    return
  }

  if (!state.mode) {
    app.innerHTML = renderLanding(state.errorMessage)
    return
  }

  app.innerHTML = renderAssessment({
    mode: state.mode,
    currentIndex: state.currentIndex,
    session: state.session,
    selectedOption: state.selectedOption,
    answerValue: state.mode === 'typed' ? state.freeText : state.transcript,
    recording: state.recording,
    notice: state.notice,
    canContinue: canContinue(),
    saving: state.saving,
  })
}

// ── Event listeners ───────────────────────────────────────────────────────────

app.addEventListener('click', (event) => {
  const target = event.target as HTMLElement
  const actionTarget = target.closest<HTMLElement>('[data-action]')
  const optionTarget = target.closest<HTMLButtonElement>('[data-option]')

  if (optionTarget) {
    state.selectedOption = optionTarget.dataset.option ?? ''
    if (state.mode === 'typed') state.freeText = state.selectedOption
    if (state.mode === 'voice' && !state.transcript.trim()) state.transcript = state.selectedOption
    render()
    return
  }

  if (!actionTarget) return

  const action = actionTarget.dataset.action
  if (action === 'start-typed') void startAssessment('typed')
  if (action === 'start-voice') void startAssessment('voice')
  if (action === 'reset') resetApp()
  if (action === 'previous') moveToPreviousQuestion()
  if (action === 'next' && canContinue()) void saveCurrentAnswer()
  if (action === 'record') void toggleRecording()
  if (action === 'export' && state.session) exportSessionJson(state.session)
  if (action === 'download-pdf' && state.backendSessionId) {
    window.open(apiReportPdfUrl(state.backendSessionId), '_blank')
  }
})

app.addEventListener('input', (event) => {
  const target = event.target as HTMLTextAreaElement
  if (target.dataset.field === 'typed') state.freeText = target.value
  if (target.dataset.field === 'transcript') state.transcript = target.value

  const nextButton = document.querySelector<HTMLButtonElement>('[data-action="next"]')
  if (nextButton) nextButton.disabled = !canContinue()
})

render()
