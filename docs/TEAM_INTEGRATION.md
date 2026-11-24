# Team Integration Handoff

Prepared for Shree Pranav G and Harshdeep on 24 November 2026.

## Change Scope

This revision starts from upstream commit
`ff2a2bce91ac92654be2a414c167ca03956e153e` and addresses application persistence
and local setup. It does not remove or redesign the repository's optional
hardware integration. The separate academic paper is application-only and is
not included in this code change.

- Persist the typed/voice choice on the backend before collecting answers.
- Keep the current question, answer, and recording available when saving fails.
- Keep server report failures visible instead of silently replacing their output.
- Validate question IDs and use canonical question wording on the server.
- Preserve recording links during answer edits and reject unrelated audio URLs.
- Validate upload media types, extensions, sizes, and basic container signatures.
- Commit a replacement recording before deleting the old file.
- Remove deleted sessions from research CSV copies as well as session storage.
- Respect the configured backend URL in the production frontend build.
- Provide local Windows launchers, private configuration generation, and tests.
- Refresh the frontend lockfile within the existing dependency version ranges.

## Run Locally

Install dependencies using the Windows instructions in `README.md`, then open
`Open-ErgoCare.bat`. For an application-only assessment, continue without the
optional device and select typed or voice answers. No device is needed to test
the questionnaire and reporting path.

The launcher binds only to the local computer. Its actual frontend and API URLs
are saved in `logs/local-run.json`. It does not publish the app to the internet.
Keep each developer's `.env`, `LOCAL_ACCESS.txt`, database, recordings, and
research exports private. None belongs in a Git commit or shared code archive.

## Verification Repeated on 24 November 2026

| Check | Result |
|---|---|
| Backend session integrity regressions | 12/12 pass |
| Frontend integrity checks | 6/6 pass, including inline script parsing |
| Questionnaire scoring checks | 27/27 pass |
| Frontend/backend scoring parity | 206 values across 40 questions |
| TypeScript and Vite production build | Pass |

Run the focused checks from the repository root:

```powershell
node scripts/verify_frontend_integrity.mjs
./ergo_ml_backend/.venv/Scripts/python.exe ergo_ml_backend/scripts/verify_session_integrity.py
./ergo_ml_backend/.venv/Scripts/python.exe ergo_ml_backend/scripts/verify_scoring.py
./ergo_ml_backend/.venv/Scripts/python.exe ergo_ml_backend/scripts/verify_frontend_parity.py
npm run build
```

These checks use synthetic fixtures and are not clinical validation or a
complete browser acceptance test. See `LOCAL_HANDOFF.md` for the earlier test
coverage and its limits.

## Integration Checklist

1. Review the pull request and run the focused tests on the receiving machine.
2. Exercise one full typed session and one voice session in the target browser.
   Verify transcript correction, one clip per question, saved mode, and PDF output.
3. Interrupt the API during saving and confirm that the answer is retained for
   retry without falsely advancing. Retry after restoring the API.
4. Use synthetic records to verify admin report access and session deletion,
   including associated recording files and exported CSV rows.
5. Merge after review, then configure the deployment's backend URL, CORS origins,
   unique secrets, private storage, and database backups independently.

## Remaining Work

- Require all 40 answers or explicitly label partial reports. Current non-empty
  partial sessions can still be completed.
- Add database uniqueness and safe concurrent upserts for session-question pairs.
- Add cross-process export locking or a database-backed export queue before
  running multiple backend workers.
- Review recommendation wording and the questionnaire with the guide and a
  qualified subject-matter reviewer; the scoring rules are not diagnostic models.
- Test actual speech recognition, mobile layouts, accessibility, and translations
  with real speakers and target devices.
- Perform a backend dependency audit and production security review.

No secrets, participant records, recordings, or generated academic documents
are required to review or merge this change.
