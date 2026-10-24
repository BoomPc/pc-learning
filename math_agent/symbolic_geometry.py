"""Exact coordinate calculations, separate from JSXGraph rendering and source interpretation."""
import re
from .tool_math import expression


def construct(points, constructions, measurements, variables=None):
    import sympy as s
    names=variables or []
    if len(set(names))!=len(names) or any(not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,15}',n) or n in {'pi','sqrt','sin','cos','tan','abs'} for n in names):
        raise ValueError('变量名无效或重复')
    symbols={n:s.Symbol(n,real=True) for n in names};restrictions=[]
    def parse(value):
        v=expression(value,symbols,restrictions)
        if v.is_real is False:raise ValueError('坐标/角度必须为实数')
        if v.is_real is None:restrictions.append(f'im({v}) = 0')
        return v
    def pair(values):return s.Matrix([parse(v) for v in values])
    pts={name:pair(values) for name,values in points.items()}
    for item in constructions:
        name=item['id'];kind=item['kind'];parents=item['parents']
        if name in pts:raise ValueError('派生点ID重复')
        if any(p not in pts for p in parents):raise ValueError('派生点引用不存在或尚未构造的点')
        if kind=='rotation':
            if len(parents)!=2 or set(item)!={'id','kind','parents','degrees','direction'}:raise ValueError('rotation需[原点,中心]、degrees和direction')
            degrees=parse(item['degrees'])
            if degrees.is_nonnegative is False:raise ValueError('degrees必须非负，方向用direction声明')
            if degrees.is_nonnegative is None:restrictions.append(f'{degrees} >= 0')
            angle=degrees*s.pi/180
            if item['direction']=='clockwise':angle=-angle
            p,o=[pts[n] for n in parents];u=p-o
            v=o+s.Matrix([[s.cos(angle),-s.sin(angle)],[s.sin(angle),s.cos(angle)]])*u
        elif kind=='translation':
            if len(parents)!=1 or set(item)!={'id','kind','parents','vector'}:raise ValueError('translation需[原点]和vector')
            v=pts[parents[0]]+pair(item['vector'])
        elif kind=='midpoint':
            if len(parents)!=2 or set(item)!={'id','kind','parents'}:raise ValueError('midpoint需两个点')
            v=(pts[parents[0]]+pts[parents[1]])/2
        else:raise ValueError('不支持此构造')
        pts[name]=v.applyfunc(s.simplify)
    rows=[]
    for item in measurements:
        ids=item['points'];kind=item['kind'];arity={'distance_squared':2,'oriented_area2':3,'dot':4,'angle_cosine':3}[kind]
        if len(ids)!=arity or any(n not in pts for n in ids):raise ValueError('测量点数错误或点不存在')
        p=[pts[n] for n in ids]
        if kind=='distance_squared':v=(p[1]-p[0]).dot(p[1]-p[0])
        elif kind=='dot':v=(p[1]-p[0]).dot(p[3]-p[2])
        elif kind=='angle_cosine':
            u,w=p[0]-p[1],p[2]-p[1]
            product=s.simplify(u.dot(u)*w.dot(w))
            if product.is_zero is True:raise ValueError('重合点不能定义角')
            if product.is_positive is not True:restrictions.append(f'{product} > 0')
            v=u.dot(w)/s.sqrt(product)
        else:
            u,w=p[1]-p[0],p[2]-p[0];v=u[0]*w[1]-u[1]*w[0]
        v=s.simplify(v)
        rows.append({**item,'value':str(v),'zero':v.is_zero})
    return {'ok':True,'points':{n:[str(s.simplify(v)) for v in p] for n,p in pts.items()},'measurements':rows,
        'domain_restrictions':sorted(set(restrictions)),
        'scope':'仅按声明坐标计算精确表达式，不确认坐标符合原题。零叉积或零点积也可能来自退化线段；镜像会改变顺逆时针，必须核对原图朝向及各小问条件。恒等式仅在表达式有定义的实数域成立，仍需筛选根和退化位置。'}


EXPR={'type':['number','string']}
PAIR={'type':'array','minItems':2,'maxItems':2,'items':EXPR}
PROPERTIES={
 'variables':{'type':'array','maxItems':8,'uniqueItems':True,'items':{'type':'string','maxLength':16}},
 'points':{'type':'object','minProperties':1,'maxProperties':24,'propertyNames':{'pattern':'^[A-Za-z][A-Za-z0-9_]{0,15}$'},'additionalProperties':PAIR},
 'constructions':{'type':'array','maxItems':24,'items':{'type':'object','additionalProperties':False,'required':['id','kind','parents'],'properties':{
  'id':{'type':'string','pattern':'^[A-Za-z][A-Za-z0-9_]{0,15}$'},'kind':{'enum':['rotation','translation','midpoint']},
  'parents':{'type':'array','minItems':1,'maxItems':2,'items':{'type':'string'}},'degrees':EXPR,'direction':{'enum':['clockwise','counterclockwise']},'vector':PAIR}}},
 'measurements':{'type':'array','maxItems':40,'items':{'type':'object','additionalProperties':False,'required':['kind','points'],'properties':{
  'kind':{'enum':['distance_squared','oriented_area2','dot','angle_cosine']},'points':{'type':'array','minItems':2,'maxItems':4,'items':{'type':'string'}}}}}
}
