"""Explicit, offline migration of nine historical evaluation scenes; not a production fallback.

Native relationships below are reviewed test fixtures. This does NOT test a model's ability
 to produce the new JSXGraph contract. Original low56 outputs remain untouched.
"""
import copy,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def convert(old):
    result={'format':'jsxgraph-v1','title':old['title'],'problem_text':old['problem_text'],'tabs':[]}
    for tab in old['tabs']:
        stage=tab['stage'];ox,oy=stage['origin'];scale=stage['scale'];objects=[]
        for point in stage.get('points',[]):
            d=point.get('dynamic',{});objects.append({'id':point['name'],'label':point.get('label',point['name']),'kind':'point','coords':point.get('coord',[d.get('x'),d.get('y')]),'color':point.get('color','#ffd166')})
        def ref(value):
            if isinstance(value,str):return value
            name='aux'+str(len(objects));objects.append({'id':name,'kind':'point','coords':value,'visible':False});return name
        for i,line in enumerate(stage.get('lines',[])):
            parents=[ref(line['p1']),ref(line['p2'])]
            objects.append({'id':line.get('id','seg'+str(i)),'kind':'segment','parents':parents,'color':line.get('color','#65c7ff'),'dashed':line.get('dashed',False)})
        for i,curve in enumerate(stage.get('curves',[])):objects.append({'id':'curve'+str(i),'kind':'functiongraph','expression':curve['expr'],'domain':curve['domain'],'color':curve.get('color','#65c7ff')})
        for i,poly in enumerate(stage.get('polygons',[])):objects.append({'id':'poly'+str(i),'kind':'polygon','parents':[ref(x) for x in poly['points']],'color':poly.get('stroke','#65c7ff')})
        new={k:tab[k] for k in ('tab_title','steps','conclusion')};new['board']={'bounding_box':[-ox/scale,oy/scale,(560-ox)/scale,(oy-420)/scale],'axis':stage.get('axis',{}).get('show',True),'objects':objects}
        if 'controls' in tab:
            new['controls']=copy.deepcopy(tab['controls']);s=new['controls']['slider'];s['label']=s.pop('slider_label','参数 t');s.pop('slider_id',None)
        result['tabs'].append(new)
    return result

def main():
    for case in ('01','08','16','21','28','36','41','48','56'):
        old=json.loads((ROOT/f'evaluation/low56/{case}/candidate.corrected.json').read_text());spec=convert(old);board=spec['tabs'][0]['board'];objects=board['objects'];byid={o['id']:o for o in objects}
        def replace(name,kind,parents,**kwargs):
            obj=byid[name];obj.pop('coords',None);obj.update(kind=kind,parents=parents,**kwargs)
        def helper(name,kind,**kwargs):objects.append(dict(id=name,kind=kind,visible=False,**kwargs))
        if case=='08':
            replace('Ap','translation',['A'],vector=['-t',0]);replace('Cp','translation',['C'],vector=['-t',0])
        if case=='16':
            helper('BC','line',parents=['B','C']);helper('O','point',coords=[0,0]);helper('OY','line',parents=['O','C']);helper('vertical','parallel',parents=['OY','P']);replace('M','intersection',['vertical','BC'],branch=0)
        if case=='21':replace('D','midpoint',['B','C'])
        if case=='28':
            helper('O','point',coords=[0,0]);helper('Y','point',coords=[0,1]);helper('axisY','line',parents=['O','Y']);replace('Bs','reflection',['B','axisY']);board['bounding_box']=[-3.5,5,7,-1]
        if case=='36':
            helper('AC','line',parents=['A','C']);helper('perpA','perpendicular',parents=['AC','A']);helper('parallelD','parallel',parents=['AC','D']);replace('E','intersection',['perpA','parallelD'],branch=0);board['bounding_box']=[-1,14,7,-6]
        if case=='41':
            helper('DE','line',parents=['D','E']);replace('F','reflection',['A','DE']);replace('G','midpoint',['A','F']);byid['G']['visible']=False
        if case=='48':replace('Bp','rotation',['B','A'],angle='-t*pi/180');replace('Cp','rotation',['C','A'],angle='-t*pi/180')
        if case=='56':
            helper('C0','point',coords=[6,0]);helper('E0','point',coords=[2,0]);replace('C','rotation',['C0','A'],angle='t');replace('D','midpoint',['B','C']);replace('E','rotation',['E0','A'],angle='t');board['bounding_box']=[-7,7,9,-1]
        folder=ROOT/'evaluation/jsxgraph'/case;folder.mkdir(parents=True,exist_ok=True);(folder/'spec.json').write_text(json.dumps(spec,ensure_ascii=False,indent=2)+'\n')
if __name__=='__main__':main()
