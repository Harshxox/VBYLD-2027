"""Run the integration handoff checks without touching participant storage."""
from pathlib import Path
from datetime import datetime, timezone
import json
import os
import shutil
import subprocess
import sys

BACKEND=Path(__file__).resolve().parents[1]
REPO=BACKEND.parent
node=os.getenv('NODE_BINARY') or shutil.which('node')
if not node:raise SystemExit('Install Node.js 22.12+ or set NODE_BINARY to its executable.')
env={**os.environ,'PYTHONIOENCODING':'utf-8','PATH':str(Path(node).parent)+os.pathsep+os.environ.get('PATH','')}
checks=[('frontend integrity',[node,'scripts/verify_frontend_integrity.mjs'],REPO),
        ('session integrity',[sys.executable,'scripts/verify_session_integrity.py'],BACKEND),
        ('speech route',[sys.executable,'scripts/verify_voice_transcription.py'],BACKEND),
        ('scoring',[sys.executable,'scripts/verify_scoring.py'],BACKEND),
        ('full scoring parity',[sys.executable,'scripts/verify_frontend_parity.py'],BACKEND),
        ('sensor authorization',[sys.executable,'scripts/verify_sensor_security.py'],BACKEND),
        ('simulated wearable logic',[sys.executable,'scripts/verify_wearable.py','--logic-only'],BACKEND),
        ('real HTTP synthetic integration',[sys.executable,'scripts/smoke_wearable.py'],BACKEND),
        ('Indic PDF',[sys.executable,'scripts/verify_pdf_indic.py'],BACKEND),
        ('Python dependencies',[sys.executable,'-m','pip','check'],BACKEND),
        ('TypeScript',[node,'node_modules/typescript/bin/tsc'],REPO),
        ('production frontend',[node,'node_modules/vite/bin/vite.js','build'],REPO)]
results=[]
for name,args,cwd in checks:
    print('CHECK',name,flush=True)
    try:
        proc=subprocess.run(args,cwd=cwd,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=240)
        result={'name':name,'passed':proc.returncode==0,'returncode':proc.returncode,'output':proc.stdout+proc.stderr}
    except subprocess.TimeoutExpired:
        result={'name':name,'passed':False,'returncode':None,'output':'Check timed out after 240 seconds.'}
    results.append(result);print('PASS' if result['passed'] else 'FAIL',name,flush=True)
log=REPO/'logs/handoff-verification.json';log.parent.mkdir(exist_ok=True)
log.write_text(json.dumps({'timestamp_utc':datetime.now(timezone.utc).isoformat(),'synthetic':True,'checks':results},indent=2),encoding='utf-8')
print(f"{sum(c['passed'] for c in results)}/{len(results)} suites passed. Details: logs/handoff-verification.json")
raise SystemExit(0 if all(c['passed'] for c in results) else 1)
