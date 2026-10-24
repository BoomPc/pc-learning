"""Build a source release from an explicit allow-list; exclude secrets and legacy engines."""
from pathlib import Path
import hashlib,json,tarfile
ROOT=Path(__file__).resolve().parents[1]
VERSION='0.4.0'; PREFIX='math-agent-jsxgraph-'+VERSION
files=[]
for name in ['math_agent','tests','examples','deploy']:
    files.extend(p for p in (ROOT/name).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
for name in ['README.md','架构方案与后续建议.md','AGENTS.md','接续开发手册.md','验收记录.md','Dockerfile','compose.yaml','pyproject.toml','constraints.txt','.env.example','.dockerignore','.gitignore']:
    files.append(ROOT/name)
for name in ['init_env.py','offline_demo.py','evaluate_jsxgraph_cases.py','geometry_expectations.py','package_release.py','check_ocr_live.py','live_linux_smoke.py','live_text_smoke.py','resume_review.py','revise_diagram.py','evaluate_adjudication_live.py']:
    files.append(ROOT/'scripts'/name)
for name in ['验收报告.md','tests-final.log','replay.log','replay-results.json']:
    files.append(ROOT/'evaluation/jsxgraph'/name)
for p in (ROOT/'evaluation/jsxgraph').glob('*/spec.json'):files.append(p)
# Include one reviewable page, not all historical models or uploaded images.
for name in ['result.html','audited-preview.png']:
    files.append(ROOT/'evaluation/jsxgraph/48/output'/name)
for name in ['验收报告.md','tests-final.log','tests-guard.log','final-summary.json','audit-final.log']:
    files.append(ROOT/'evaluation/langgraph'/name)
for name in ['result.html','spec.json']:
    files.append(ROOT/'evaluation/langgraph/final-cases/16/output.round2'/name)
for name in ['验收报告.md','tests-final.log','model-costs.json','numeric-fix-replay.json','browser-checksum.txt','ocr-evidence/summary.json','ocr-evidence/fifth.json']:
    files.append(ROOT/'evaluation/ocr-linux'/name)
for name in ['验收报告.md','tests-final.log','costs.json','final/result.html','final/tab-0.png','final/visual-check.json']:
    files.append(ROOT/'evaluation/evidence-agent'/name)
(ROOT/'dist').mkdir(exist_ok=True)
archive=ROOT/'dist'/(PREFIX+'.tar.gz')
with tarfile.open(archive,'w:gz') as tar:
    for path in sorted(set(files)):
        relative=path.relative_to(ROOT)
        assert '.env' not in relative.parts and 'engine' not in relative.parts and not path.is_symlink()
        tar.add(path,arcname=str(Path(PREFIX)/relative),recursive=False)
sha=hashlib.sha256(archive.read_bytes()).hexdigest()
(archive.parent/(archive.name+'.sha256')).write_text(sha+'  '+archive.name+'\n')
print(json.dumps({'path':str(archive),'files':len(set(files)),'bytes':archive.stat().st_size,'sha256':sha}))
