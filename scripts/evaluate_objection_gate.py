"""Explicit paid replay of saved drawing objections; no restart, no end-to-end claim."""
import argparse,json,shutil,time,os
from pathlib import Path
from dataclasses import replace
from math_agent.config import ROOT,Settings
from math_agent.contracts import Source,Review
from math_agent.reference_flow import validate_math,assemble
from math_agent.scene_tools import PreviewSpec
from math_agent.pipeline import Runner
from math_agent.storage import Store,write_json


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,required=True);ap.add_argument('--case',choices=['false','mixed'],default='false');args=ap.parse_args();args.out=args.out.resolve()
    args.out.mkdir(parents=True,exist_ok=False)
    for line in (ROOT/'.env').read_text().splitlines():
        if '=' in line and not line.startswith('#'):
            k,v=line.split('=',1);os.environ[k]=v
    cfg=replace(Settings(),data_dir=args.out/'runtime',redis_url='',ocr_url='',effort='low',max_calls=6,max_tokens=16000)
    old=ROOT/('evaluation/geometry-tools-v2/draw_static' if args.case=='false' else 'evaluation/geometry-tools-v2/draw')
    origin=next((old/'runtime/jobs').iterdir())
    gold=json.loads((ROOT/'evaluation/isolation-v1/gold-48.json').read_text())
    source=Source.model_validate(gold['source']);math=validate_math(gold['math'],source)
    drawing=PreviewSpec.model_validate(json.loads((origin/('model-02-draw.json' if args.case=='false' else 'model-03-draw.json')).read_text()))
    candidate=assemble(source,math,drawing)
    review=Review.model_validate(json.loads((old/'review-0.json').read_text()))
    store=Store(cfg.data_dir);job,directory=store.prepare();store.enqueue(job);store.claim()
    req=json.loads((origin/'request.json').read_text())
    for img in req['images']:shutil.copyfile(origin/img['file'],directory/img['file'])
    write_json(directory/'request.json',req)
    runner=Runner(cfg,job);start=time.monotonic();result={'end_to_end':False,'status':'failed','case':args.case}
    try:
        runner.save_ledger(source,candidate);runner.scenes.current=candidate.spec;runner.review_candidate=candidate
        observed=runner.observe(candidate)
        objections=[{'id':f'R{i+1}','kind':'review_issue','issue':issue.model_dump()} for i,issue in enumerate(review.issues)]
        verdict=runner.adjudicate(source,candidate,observed,objections,original_review=review)
        write_json(args.out/'resolution.json',verdict.model_dump())
        expected={f'R{i+1}':('invalid_check' if args.case=='false' or i==3 else 'real_issue') for i in range(len(review.issues))}
        result.update(status='expected_resolution' if all(d.verdict==expected[d.assertion_id] for d in verdict.decisions) and verdict.reviewed.verdict==('pass' if args.case=='false' else 'revise') else 'unexpected_resolution')
    except Exception as exc:result.update(error=str(exc),error_type=type(exc).__name__)
    finally:
        runner.provider.close();result.update(seconds=round(time.monotonic()-start,3),calls=runner.provider.calls)
        write_json(args.out/'result.json',result);print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':main()
