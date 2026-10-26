# Product Architecture Notes

> **Superseded.** Early planning notes from before the build — several items here (XGBoost, SHAP, RAG) were never implemented. The system as built is described in [TECHNICAL_DESIGN.md](TECHNICAL_DESIGN.md).

## Frontend Responsibilities

- Collect typed or spoken answers.
- Keep each assessment as one session record.
- Show progress, question category, and captured answer state.
- Calculate prototype scores locally until backend scoring is added.
- Render the visual report and export the session JSON.

## Backend Responsibilities Later

- Persist sessions in a database.
- Store voice recordings as files or object-storage assets.
- Convert voice answers to transcripts with a speech-to-text service.
- Run validated XGBoost scoring and SHAP explanations.
- Generate a grounded RAG report from ergonomic guideline documents.
- Export a polished PDF report for the user.

## Suggested Session Tables

```text
assessment_sessions
  id
  input_mode
  created_at
  completed_at
  overall_risk
  report_json

assessment_answers
  id
  session_id
  question_id
  question_text
  typed_answer
  transcript
  audio_url
  created_at
```
