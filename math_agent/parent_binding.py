"""Bind the unique point/straight-line argument roles before strict native validation.

Never infer coordinates, missing parents, rotation direction or same-type order.
"""
import copy
from .jsxgraph.spec import POINTS,LINES


def bind_parent_roles(spec, audit=None):
    result=copy.deepcopy(spec);changes=[]
    for ti,tab in enumerate(result.get('tabs',[])):
        objects=tab.get('board',{}).get('objects',[])
        by_id={o.get('id'):o for o in objects}
        if len(by_id)!=len(objects):continue  # Leave duplicates for strict rejection.
        for obj in objects:
            kind=obj.get('kind');refs=obj.get('parents',[])
            if kind not in {'perpendicularpoint','reflection','parallel','perpendicular'} or len(refs)!=2:continue
            if any(r not in by_id for r in refs):continue
            types=[by_id[r].get('kind') for r in refs]
            groups=(POINTS,LINES) if kind in {'perpendicularpoint','reflection'} else (LINES,POINTS)
            if types[0] in groups[1] and types[1] in groups[0]:
                obj['parents']=list(reversed(refs))
                changes.append({'tab':ti,'object':obj['id'],'kind':kind,'before':refs,'after':obj['parents'],
                    'reason':'点/直线类型唯一，按已声明构造的参数角色绑定；不改变几何定义'})
    if changes and audit:audit('parent_role_binding',{'changes':changes})
    return result,changes
