"""Offline independent numerical oracle for evaluation fixture 48 only; never a runtime solver."""
import json,math,sys
from pathlib import Path
out=Path(sys.argv[1]);job=next((out/'runtime/jobs').iterdir())
candidate=json.loads((out/'candidate.json').read_text())
observation=json.loads(sorted(job.glob('observation-*.json'))[-1].read_text())
checks=[]
allow_scale='--allow-unlabelled-scale' in sys.argv
scales=[]
def check(name,ok):checks.append({'name':name,'pass':bool(ok)})
def sub(a,b):return (a[0]-b[0],a[1]-b[1])
def dist(a,b):return math.hypot(*sub(a,b))
def close(a,b):return abs(a-b)<1e-5
for i,state in enumerate(observation['default_states']):
    board=candidate['spec']['tabs'][i]['board'];coords=state['points'];pts={}
    for label in ['A','B','C','B′','C′']+(['D','E','F'] if i>=2 else []):
        matches=[o for o in board['objects'] if o.get('label','').replace("'",'′')==label or o.get('label','').startswith(label+'(=')]
        if len(matches)!=1:raise ValueError(f'tab{i}: ambiguous/missing label {label}')
        o=matches[0];p=coords[o['id']];pts[label]=(p['x'],p['y'])
        if label in ['B′','C′']:check(f'{i}/{label}/native_rotation',o['kind']=='rotation')
        if label in ['D','E','F']:check(f'{i}/{label}/native_translation',o['kind']=='translation')
    a,b,c,bp,cp=[pts[k] for k in ['A','B','C','B′','C′']]
    check(f'{i}/base_lengths',close(dist(a,b),2*math.sqrt(3)) and close(dist(a,c),2) and close(dist(b,c),4))
    if allow_scale:
        if board.get('axis',True):raise ValueError('坐标轴可见时不能允许未标注比例')
        scale=dist(a,c)/2;scales.append(scale)
        if scale<=0:raise ValueError('退化比例')
        pts={k:(v[0]/scale,v[1]/scale) for k,v in pts.items()}
        a,b,c,bp,cp=[pts[k] for k in ['A','B','C','B′','C′']]
        checks.pop()  # Replace the explicitly selected scale-dependent base length check.
        check(f'{i}/scaled_base_lengths',close(dist(a,b),2*math.sqrt(3)) and close(dist(a,c),2) and close(dist(b,c),4))
    angle=-math.pi*(2 if i==1 else 1)/3
    for name,old,new in [('B',b,bp),('C',c,cp)]:
        v=sub(old,a);w=sub(new,a)
        check(f'{i}/{name}/clockwise',close(w[0],v[0]*math.cos(angle)-v[1]*math.sin(angle)) and close(w[1],v[0]*math.sin(angle)+v[1]*math.cos(angle)))
    if i==0:
        check('Q1/C_on_segment',close(dist(bp,c)+dist(c,cp),dist(bp,cp)))
        v,w=sub(b,bp),sub(c,bp);check('Q1/right_angle',close(v[0]*w[0]+v[1]*w[1],0))
    if i==1:
        check('Q2/C_on_segment',close(dist(b,c)+dist(c,bp),dist(b,bp)))
        check('Q2/length',close(dist(b,cp),2*math.sqrt(7)))
    if i>=2:
        d,e,f=[pts[k] for k in ['D','E','F']];v=sub(d,a)
        for name,w in [('CE',sub(e,c)),('CpF',sub(f,cp))]:check(f'{i}/translation/{name}',all(close(x,y) for x,y in zip(v,w)))
        check(f'{i}/isosceles',close(dist(cp,b),dist(cp,e)))
        check(f'{i}/AD',close(dist(a,d),(4 if i==2 else 2)*math.sqrt(3)))
        check(f'{i}/position',close(dist(bp,a)+dist(a,d),dist(bp,d)) if i==2 else close(dist(bp,d),0))
if allow_scale:check('same_scale_across_tabs',all(close(s,scales[0]) for s in scales))
result={'display_scales':scales,'scope':'fixed fixture 48, actual native browser coordinates; not OCR/proof/general accuracy', 'checks':checks,'status':'pass' if all(c['pass'] for c in checks) else 'fail'}
(out/('independent-similarity.json' if allow_scale else 'independent-geometry.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2))
print(result['status'],len(checks));sys.exit(0 if result['status']=='pass' else 1)
