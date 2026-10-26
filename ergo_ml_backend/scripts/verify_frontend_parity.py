"""
Guards against the frontend copy of the scoring engine drifting from the server.

index.html re-implements option_risk / the feature weights so it can build the
pain body map (which the API never returns) and so the app still works offline.
That duplication is only safe if the two implementations agree exactly, so this
test extracts the JavaScript out of index.html, runs it under Node, and compares
every (question x option) risk value against app/domain/scoring.py.

Requires Node on PATH. Run from ergo_ml_backend:  python scripts/verify_frontend_parity.py
"""
import json
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.domain.questions import QUESTIONS            # noqa: E402
from app.domain.scoring import option_risk            # noqa: E402
from app.domain.ml_engine import get_weight           # noqa: E402

INDEX_HTML = os.path.join(ROOT, "index.html")

HARNESS = r"""
const fs = require('fs');
const html = fs.readFileSync(process.argv[2], 'utf8');
const lines = html.split(/\r?\n/);
function slice(startPat, endPat) {
  const s = lines.findIndex(l => startPat.test(l));
  if (s === -1) throw new Error('start not found: ' + startPat);
  const e = lines.findIndex((l, i) => i > s && endPat.test(l));
  if (e === -1) throw new Error('end not found: ' + endPat);
  return lines.slice(s, e + 1).join('\n');
}
const questions = eval(slice(/^const questions = \[/, /^\]$/) + '; questions');
const Q_WEIGHTS = eval(slice(/^const Q_WEIGHTS = \{/, /^\}$/) + '; Q_WEIGHTS');
const optionRiskSrc = slice(/^function optionRisk\(/, /^}$/);
const optionRisk = eval('(' + optionRiskSrc + ')');
const out = {};
for (const q of questions) {
  const rows = {};
  for (const opt of q.options) rows[opt] = optionRisk(q, opt);
  rows['__weight__'] = Q_WEIGHTS[q.id] !== undefined ? Q_WEIGHTS[q.id] : 1.0;
  out[q.id] = rows;
}
fs.writeFileSync(process.argv[3], JSON.stringify(out), 'utf8');
"""


def frontend_values(tmpdir):
    harness = os.path.join(tmpdir, "extract.js")
    outfile = os.path.join(tmpdir, "fe.json")
    with open(harness, "w", encoding="utf-8") as fh:
        fh.write(HARNESS)
    proc = subprocess.run(
        ["node", harness, INDEX_HTML, outfile],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"node harness failed:\n{proc.stdout}\n{proc.stderr}")
    with open(outfile, encoding="utf-8") as fh:
        return json.load(fh)


def main() -> int:
    if not os.path.exists(INDEX_HTML):
        print(f"FAIL  index.html not found at {INDEX_HTML}")
        return 1

    # Guards on the source of truth itself.
    reversed_qs = [q["id"] for q in QUESTIONS if q.get("reverse")]
    if reversed_qs:
        print(f"FAIL  questions.py still marks Q{reversed_qs} reverse=true. Options are "
              "ordered healthiest-first, so reverse inverts the scale.")
        return 1

    with tempfile.TemporaryDirectory() as tmpdir:
        fe = frontend_values(tmpdir)

    failures = []
    checked = 0

    fe_ids = {int(k) for k in fe}
    be_ids = {q["id"] for q in QUESTIONS}
    for missing in sorted(be_ids - fe_ids):
        failures.append(f"Q{missing} exists in questions.py but not in index.html")
    for extra in sorted(fe_ids - be_ids):
        failures.append(f"Q{extra} exists in index.html but not in questions.py")

    for q in QUESTIONS:
        qid = str(q["id"])
        if qid not in fe:
            continue
        for opt in q["options"]:
            checked += 1
            expected = option_risk(q, opt)
            actual = fe[qid].get(opt)
            if actual != expected:
                failures.append(
                    f"Q{qid} {opt!r}: server={expected} frontend={actual}")

        checked += 1
        expected_w = get_weight(q["id"])
        actual_w = fe[qid].get("__weight__")
        if actual_w != expected_w:
            failures.append(
                f"Q{qid} weight: server={expected_w} frontend={actual_w}")

    print(f"checked {checked} values across {len(be_ids)} questions "
          f"(risk per option + feature weight)")
    if failures:
        print(f"FAIL  {len(failures)} mismatch(es)")
        for f in failures[:40]:
            print("   " + f)
        return 1
    print("PASS  frontend scoring matches the server exactly")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())