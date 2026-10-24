"""Validate explicit independent resolution of every textual drawing objection."""
from .contracts import check_review


def validate_resolution(result, original, source):
    revised = result.reviewed
    if revised is None:
        raise ValueError('文字异议裁决必须返回完整reviewed复核')
    check_review(revised, source)
    # Source/math objections never disappear as a side effect of a drawing dispute.
    expected = [i for i in original.issues if i.stage != 'diagram']
    expected += [d.issue for d in result.decisions if d.verdict == 'real_issue']
    if revised.issues != expected:
        raise ValueError('reviewed必须逐字保留原source/math异议及所有确认的真实问题，不能新增未裁决修图要求')
    if original.verdict == 'needs_input' and revised.verdict != 'needs_input':
        raise ValueError('裁决不能解除原needs_input')
    if any(d.verdict == 'unresolved' for d in result.decisions) and revised.verdict != 'needs_input':
        raise ValueError('未决裁决必须needs_input')
    old = {c.id:c for c in original.conditions + original.questions}
    for c in revised.conditions + revised.questions:
        previous = old[c.id]
        if previous.verdict == 'unknown' and c.verdict != 'unknown':
            raise ValueError('裁决不得顺带清空未知核验项')
        if previous.verdict != 'pass' and c.verdict == 'pass' and c.evidence == previous.evidence:
            raise ValueError('撤销异议需给出新的核验证据，不能只改状态')
