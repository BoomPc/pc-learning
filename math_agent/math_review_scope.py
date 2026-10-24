"""Serial, job-local re-review after a proof-only revision.

Every condition is reviewed again. Only unchanged, previously accepted questions
outside both old and new dependency closures may retain their previous checks.
Original tab indices and the complete read-only scene/ledger remain available.
"""
import copy
import re
from pathlib import Path
import hashlib
from .contracts import Candidate, Review, check_candidate, check_review
from .review_reuse import binding, digest
from .review_partition import partition


def engine_binding():
    package=Path(__file__).resolve().parent
    return digest({str(p.relative_to(package)):hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in sorted(package.rglob('*.py'))})


def capture(source, candidate, review, request, directory):
    check_candidate(candidate, source)
    check_review(review, source)
    return {'engine': engine_binding(), 'binding': binding(source, candidate, request, directory),
            'candidate': candidate.model_dump(), 'review': review.model_dump()}


def plan(snapshot, source, candidate, request, directory):
    if not snapshot:
        return None
    if snapshot.get('engine') != engine_binding():
        return None
    old = Candidate.model_validate(snapshot['candidate'])
    prior = Review.model_validate(snapshot['review'])
    if snapshot['binding'] != binding(source, old, request, directory):
        return None
    check_candidate(candidate, source)
    check_review(prior, source)
    # All global/page and geometrical data must be identical. Only canonical
    # display strings may differ, and only as derived from changed proofs.
    from .pipeline import canonical_page
    if canonical_page(copy.deepcopy(old), source) != old or canonical_page(copy.deepcopy(candidate), source) != candidate:
        return None
    def drawing(value):
        spec = copy.deepcopy(value.spec)
        for tab in spec['tabs']:
            tab.pop('steps', None)
            tab.pop('conclusion', None)
        return spec
    if drawing(old) != drawing(candidate):
        return None
    if prior.verdict == 'needs_input' or any(c.verdict != 'pass' for c in prior.conditions):
        return None
    if any(q.verdict == 'unknown' for q in prior.questions):
        return None
    ids = [q.id for q in source.questions]
    affected = {a.question_id for a, b in zip(old.solutions, candidate.solutions) if a != b}
    if not affected:
        return None
    # Never infer localization from free-form prose or erase an unbound issue.
    for issue in prior.issues:
        targets = set(re.findall(r'(?<![A-Za-z0-9])Q[1-9][0-9]*(?![A-Za-z0-9])', issue.target))
        if issue.stage != 'math' or not targets or targets - set(ids):
            return None
        affected.update(targets)
    affected.update(q.id for q in prior.questions if q.verdict != 'pass')
    plans = [partition(source, old), partition(source, candidate)]
    if not all(p['eligible'] for p in plans):
        return None
    while True:
        expanded = affected | {g['question_id'] for p in plans for g in p['groups']
                               if set(g['proof_questions']) & affected}
        if expanded == affected:
            break
        affected = expanded
    reused = [q for q in ids if q not in affected]
    if not reused:
        return None
    context = affected | {q for p in plans for g in p['groups'] if g['question_id'] in affected
                          for q in g['proof_questions']}
    output_source = source.model_copy(deep=True)
    output_source.questions = [q for q in output_source.questions if q.id in affected]
    body = {'previous': copy.deepcopy(snapshot), 'current_binding': binding(source, candidate, request, directory),
            'current_candidate': candidate.model_dump(), 'question_ids': [q for q in ids if q in affected],
            'reused_questions': reused, 'context_questions': [q for q in ids if q in context],
            'output_source': output_source.model_dump()}
    return {**body, 'sha256': digest(body)}


def merge(raw, scope, source):
    from .contracts import Source
    from .compact_review import unpack
    body = {k: v for k, v in scope.items() if k != 'sha256'}
    if digest(body) != scope['sha256']:
        raise ValueError('局部复核证据摘要不匹配')
    output_source = Source.model_validate(scope['output_source'])
    partial = unpack(raw, output_source)
    # Match ordinary review behavior: preserve all new issues, never turn them
    # into a pass merely because the author wrote an inconsistent verdict.
    if partial.verdict == 'pass' and partial.issues:
        partial.verdict = 'revise'
    check_review(partial, output_source)
    previous = Review.model_validate(scope['previous']['review'])
    checks = {q.id: q for q in partial.questions}
    result = Review(verdict=partial.verdict, conditions=partial.conditions,
                    questions=[checks.get(q.id, q).model_copy(deep=True) for q in previous.questions],
                    issues=partial.issues)
    # A newly discovered issue can concern an unchanged question. Keep it and
    # invalidate the old pass when its target is explicit. Unlocalized issues
    # still block publication and force a full review on the next revision.
    for issue in result.issues:
        targets = set(re.findall(r'(?<![A-Za-z0-9])Q[1-9][0-9]*(?![A-Za-z0-9])', issue.target))
        for q in result.questions:
            if q.id in targets and q.verdict == 'pass':
                q.verdict = 'issue'
                q.evidence = issue.detail
    check_review(result, source)
    return result


def receipt(scope, raw, merged):
    body = {'scope': copy.deepcopy(scope), 'raw': copy.deepcopy(raw), 'merged': merged.model_dump()}
    return {**body, 'sha256': digest(body)}


def check_receipts(records, source):
    for record in records:
        body = {k: v for k, v in record.items() if k != 'sha256'}
        if digest(body) != record['sha256']:
            raise ValueError('缓存局部复核收据摘要错误')
        if merge(record['raw'], record['scope'], source).model_dump() != record['merged']:
            raise ValueError('缓存局部复核收据与实际合并不符')
