// ─── ErgoCare AI — Backend API Client ────────────────────────────────────────
// Drop this file into src/api/client.ts
// Every call to the FastAPI backend goes through here.

// Injected at build time by vite.config.ts from VITE_API_BASE env var.
// Set VITE_API_BASE in Vercel → Settings → Environment Variables.
// e.g. https://ergocare-backend.onrender.com
declare const __API_BASE__: string
export const API_BASE: string = __API_BASE__

// ── Types returned by the backend ────────────────────────────────────────────

export type BackendSession = {
  id: string
  input_mode: string
  created_at: string
  completed_at: string | null
  overall_risk: number | null
  posture_risk: number | null
  eye_strain: number | null
  workload_stress: number | null
  musculoskeletal_risk: number | null
  recovery_risk: number | null
  report_json: BackendReport | null
  answers: BackendAnswer[]
}

export type BackendAnswer = {
  id: number
  session_id: string
  question_id: number
  question_text: string
  typed_answer: string | null
  transcript: string | null
  audio_url: string | null
  created_at: string
}

export type BackendScores = {
  posture_risk: number
  eye_strain: number
  workload_stress: number
  musculoskeletal_risk: number
  recovery_risk: number
  overall_risk: number
}

export type BackendReport = {
  level: 'Low' | 'Moderate' | 'High'
  top_factors: string[]
  action_plan: string[]
  category_breakdown: Record<string, number>
  detailed_findings: string[]
  positive_habits: string[]
  wearable?: {
    available: boolean
    combined?: { index: number; level: string }
    insights?: { type: string; title: string; message: string }[]
  }
}

export type CompleteSessionResponse = {
  session_id: string
  scores: BackendScores
  report: BackendReport
}

// ── Helpers ───────────────────────────────────────────────────────────────────

async function request<T>(path: string, options?: RequestInit, retries = 2): Promise<T> {
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...options,
    })
    if (!res.ok) {
      const detail = await res.text()
      throw new Error(`API ${res.status}: ${detail}`)
    }
    return res.json() as Promise<T>
  } catch (err) {
    if (retries > 0) {
      await new Promise(r => setTimeout(r, 500))
      return request(path, options, retries - 1)
    }
    throw err
  }
}

// ── Session ───────────────────────────────────────────────────────────────────

export async function apiCreateSession(
  inputMode: 'typed' | 'voice',
  clientInfo?: { name?: string; email?: string; phone?: string; age?: number; job?: string; consent?: boolean }
): Promise<BackendSession> {
  return request<BackendSession>('/api/sessions', {
    method: 'POST',
    body: JSON.stringify({
      input_mode: inputMode,
      consent: clientInfo?.consent ?? true, // ensure it's sent
      client_name: clientInfo?.name,
      client_email: clientInfo?.email,
      client_phone: clientInfo?.phone,
      client_age: clientInfo?.age,
      client_job: clientInfo?.job,
    }),
  })
}

export async function apiGetSession(sessionId: string): Promise<BackendSession> {
  return request<BackendSession>(`/api/sessions/${sessionId}`)
}

// ── Answers ───────────────────────────────────────────────────────────────────

export async function apiSaveAnswer(
  sessionId: string,
  questionId: number,
  questionText: string,
  typedAnswer: string | null,
  transcript: string | null,
  audioUrl: string | null,
): Promise<BackendAnswer> {
  return request<BackendAnswer>(`/api/sessions/${sessionId}/answers`, {
    method: 'POST',
    body: JSON.stringify({
      question_id: questionId,
      question_text: questionText,
      typed_answer: typedAnswer,
      transcript,
      audio_url: audioUrl,
    }),
  })
}

export async function apiUploadAudio(
  sessionId: string,
  questionId: number,
  audioBlob: Blob,
  fileName: string,
  transcript: string,
): Promise<{ audio_url: string; file_size: number }> {
  const form = new FormData()
  form.append('file', audioBlob, fileName)
  form.append('transcript', transcript)

  const res = await fetch(`${API_BASE}/api/sessions/${sessionId}/answers/${questionId}/audio`, {
    method: 'POST',
    body: form,
    // Do NOT set Content-Type — browser sets it with boundary automatically
  })
  if (!res.ok) {
    const detail = await res.text()
    throw new Error(`Audio upload ${res.status}: ${detail}`)
  }
  return res.json()
}

// ── Complete & Report ─────────────────────────────────────────────────────────

export async function apiCompleteSession(sessionId: string): Promise<CompleteSessionResponse> {
  return request<CompleteSessionResponse>(`/api/sessions/${sessionId}/complete`, {
    method: 'POST',
  })
}

export function apiReportPdfUrl(sessionId: string): string {
  return `${API_BASE}/api/sessions/${sessionId}/report.pdf`
}
