"""Resolve execution errors only with later observations of the same check and graph."""
import json
import math


def target(probe, check, spec=None):
    parameter = probe.get('parameter')
    if 'parameter' not in probe and spec is not None:
        parameter = (spec['tabs'][probe['tab']].get('controls') or {}).get('slider', {}).get('default')
    return {'tab': probe['tab'], 'parameter': parameter,
            'relation': check['relation'], 'points': check['points'],
            'has_expected': type(check.get('expected')) is bool, 'expected': check.get('expected')}


def key(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def reconcile(records, fingerprint):
    pending, resolved = [], []
    for index, record in enumerate(records):
        result = record['result']
        if result.get('ok') is not True:
            failure = result.get('execution_failure', {})
            targets = failure.get('targets', [])
            # Unknown/malformed errors remain blocking. No retrospective guessing.
            if failure.get('spec_sha256') != fingerprint or not targets:
                pending.append({'record': index, 'target': None, 'error': result.get('error')})
            else:
                pending.extend({'record': index, 'target': t, 'error': result.get('error'), 'failure_kind':failure.get('kind')} for t in targets)
            continue
        if result.get('spec_sha256') != fingerprint:
            continue
        successful = set()
        for probe in result.get('probes', []):
            if probe.get('in_domain') is not True: continue
            for check in probe.get('checks', []):
                if 'error' not in check and type(check.get('holds')) is bool:
                    successful.add(key(target(probe, check)))
        remaining = []
        for item in pending:
            if item['target'] is not None and key(item['target']) in successful:
                resolved.append({**item, 'resolved_by': index})
            else:
                remaining.append(item)
        pending = remaining
    return {'resolved': resolved, 'unresolved': pending}


RELATION_ARITY = {'same_x':2, 'same_y':2, 'collinear':3, 'on_segment':3,
                  'parallel':4, 'perpendicular':4, 'equal_length':4}


def reference_problem(t,spec):
    """Only facts decidable from the current declared scene, never geometry truth."""
    from .jsxgraph.spec import POINTS
    ids=t.get('points');arity=RELATION_ARITY.get(t.get('relation'))
    if not isinstance(ids,list) or arity is None or not all(isinstance(i,str) for i in ids):return None
    tab=spec['tabs'][t['tab']]
    if any('kind' not in o for o in tab['board']['objects']):return None
    points={o['id'] for o in tab['board']['objects'] if o['kind'] in POINTS}
    missing=[i for i in ids if i not in points]
    if missing:return {'referral_reason':'invalid_point_reference','invalid_point_ids':missing,
        'available_point_ids':sorted(points),'required_point_count':arity}
    value=t.get('parameter');slider=(tab.get('controls') or {}).get('slider')
    if value is not None and type(value) in (int,float) and math.isfinite(value):
        if not slider or not slider['min']<=value<=slider['max']:
            return {'referral_reason':'invalid_parameter','required_point_count':arity,
                'permitted_parameter_range':[slider['min'],slider['max']] if slider else None}
    return None


def partition_pending(pending, spec):
    """Refer impossible query shapes or invalid assertion bases to independent adjudication.

    This never resolves an error or a mathematical assertion. Unknown/runtime
    failures still require successful execution; unsupported checks require a
    separate adjudicator's explicit verdict before publication.
    """
    blocked, malformed = [], []
    seen = set()
    for item in pending:
        t = item.get('target')
        if not isinstance(t,dict) or type(t.get('tab')) is not int or not 0 <= t['tab'] < len(spec['tabs']):
            blocked.append(item); continue
        invalid=reference_problem(t,spec)
        if invalid:
            identity=key(t)
            if identity not in seen:malformed.append({**item,**invalid});seen.add(identity)
            continue
        ids = t.get('points'); arity = RELATION_ARITY.get(t.get('relation'))
        objects = {o['id'] for o in spec['tabs'][t['tab']]['board']['objects']}
        if not isinstance(ids,list) or arity is None or not all(isinstance(i,str) and i in objects for i in ids) or (len(ids)==arity and item.get('failure_kind')!='basis_validation'):
            blocked.append(item); continue
        identity=key(t)
        if identity not in seen:
            malformed.append({**item, 'required_point_count':arity, 'referral_reason':'invalid_point_count' if len(ids)!=arity else 'invalid_basis'})
            seen.add(identity)
    return blocked, malformed


def reference_failure(args,spec):
    """Preflight schema-valid query references; never repair or waive a request.

    If any reference is impossible, none of this batch executes. Every original
    target remains: legal targets still require actual observation, invalid ones
    require independent adjudication. Unknown tab/shape stays on existing gates.
    """
    if spec is None:return None
    from .scene_tools import fingerprint
    from .rendering import strict_spec
    clean=strict_spec(spec);targets=[];invalid=[]
    for probe in args['probes']:
        tab=probe['tab']
        if not 0<=tab<len(clean['tabs']):return None
        for check in probe['checks']:
            t=target(probe,check,clean);targets.append(t)
            problem=reference_problem(t,clean)
            if problem:invalid.append({'target':t,**problem})
    if not invalid:return None
    return {'ok':False,'error':'查询引用当前画板不存在或非点的对象，或使用该画板不允许的参数；本批未执行',
        'execution_failure':{'kind':'invalid_reference','spec_sha256':fingerprint(clean),'targets':targets},
        'invalid_queries':invalid,'recovery_hint':'保留本批全部检查。合法目标仍需实际执行；无效对象/参数不能原样重做或自动删除，原请求交独立裁决。需要时按真实tab、对象和参数另发合法查询，不猜改原expected。'}


def schema_failure(args, spec):
    """Bind a rejected request to its explicit checks without repairing its input.

    Only a later schema-valid observation of the same graph/check/expectation
    clears this failure. Unknown identifiers or ambiguous assertion types remain
    unbound and blocking; no spelling/type coercion or execution is performed.
    """
    from jsonschema import validate, ValidationError
    from .scene_tools import INSPECT, fingerprint
    from .rendering import strict_spec
    try:
        validate(args,INSPECT['function']['parameters'])
        return None
    except ValidationError as exc:
        error={'path':list(exc.absolute_path),'message':exc.message[:1200]}
    clean=strict_spec(spec) if spec is not None else None
    targets=[]
    def extract():
        from .jsxgraph.spec import POINTS
        if clean is None or not isinstance(args,dict):return None
        probes=args.get('probes')
        if not isinstance(probes,list) or not 1<=len(probes)<=16:return None
        values=[]
        for probe in probes:
            if not isinstance(probe,dict):return None
            tab=probe.get('tab')
            if type(tab) is not int or not 0<=tab<len(clean['tabs']):return None
            if 'parameter' in probe and (type(probe['parameter']) not in (int,float) or not math.isfinite(probe['parameter'])):return None
            checks=probe.get('checks')
            if not isinstance(checks,list) or not 1<=len(checks)<=20:return None
            points={o['id'] for o in clean['tabs'][tab]['board']['objects'] if o['kind'] in POINTS}
            for check in checks:
                if not isinstance(check,dict) or not isinstance(check.get('relation'),str) or check['relation'] not in RELATION_ARITY:return None
                ids=check.get('points')
                if not isinstance(ids,list) or not 1<=len(ids)<=12 or not all(isinstance(i,str) and i in points for i in ids):return None
                if 'expected' in check and type(check['expected']) is not bool:return None
                values.append(target(probe,check,clean))
        return values
    targets=extract() or []
    return {'ok':False,'error':'图形工具参数不符合声明格式：'+json.dumps(error,ensure_ascii=False),
            'schema_error':error,'execution_failure':{'kind':'schema_validation',
                'spec_sha256':fingerprint(clean) if clean is not None else None,'targets':targets},
            'recovery_hint':('本请求未执行。按提示修正字段，保持原tab、参数、关系、点顺序和expected；所有已绑定检查都需在同一图上实际有效重做。不要改写或删除原数学断言。' if targets else
                             '本请求未执行且无法唯一绑定检查目标，仍保持阻断；不能猜测点名、参数或expected，也不能声称已通过。')}
