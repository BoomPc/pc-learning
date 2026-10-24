"""Append-only outer-container closure for completed final JSON objects.

Never repair strings, values, keys, commas, inner mismatches or transport/token
truncation. Callers must have a completed/stop final response and must still run
all stage schemas, scope, mathematical and native-geometry gates.
"""
import hashlib
import json


def close_completed_containers(text):
    from .compact_output import unique_object
    if not isinstance(text,str) or not text.rstrip().endswith(('}',']')):return None
    try:json.loads(text,object_pairs_hook=unique_object)
    except json.JSONDecodeError as exc:
        if exc.pos<len(text.rstrip()):return None
    except ValueError:return None
    else:return None
    stack=[];quoted=False;escaped=False
    for char in text:
        if quoted:
            if escaped:escaped=False
            elif char=='\\':escaped=True
            elif char=='"':quoted=False
        elif char=='"':quoted=True
        elif char in '{[':stack.append(char)
        elif char in '}]':
            if not stack or stack.pop()!=('{' if char=='}' else '['):return None
    if quoted or escaped or not stack:return None
    repaired=text+''.join('}' if c=='{' else ']' for c in reversed(stack))
    try:value=json.loads(repaired,object_pairs_hook=unique_object)
    except ValueError:return None
    return repaired if isinstance(value,dict) else None


def audit_closure(audit,stage,call,original,repaired,transport):
    audit('json_container_closure',{'stage':stage,'call':call,'transport':transport,
        'suffix':repaired[len(original):],
        'before_sha256':hashlib.sha256(original.encode()).hexdigest(),
        'after_sha256':hashlib.sha256(repaired.encode()).hexdigest(),
        'detail':'API完成态仅追加缺少的外层闭合符号；原始文本逐字保留，不补字段/值，不重发请求，仍须全部阶段校验'})
