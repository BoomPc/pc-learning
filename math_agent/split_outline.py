"""Sequential, scoped proof tasks; same global request budget and final review gates."""
from .contracts import Source
from .math_outline import check_outline, check_expansion
from .outline_agent import OutlineProvider, OutlineRunner
from .pipeline import Runner, NeedsInput
from .storage import write_json


def question_context(source, question_id, previous):
    if question_id not in {q.id for q in source.questions}:
        raise ValueError('未知小问')
    return {'source':source.model_dump(), 'target_question':question_id,
        'condition_scope':{
            'global':[c.id for c in source.conditions if not c.question_ids],
            'local':[c.id for c in source.conditions if question_id in c.question_ids],
            'other_questions':[c.id for c in source.conditions if c.question_ids and question_id not in c.question_ids]},
        'previous_outlines':[q.model_dump() for q in previous],
        'scope_warning':'其他小问的条件不是当前已知。前序底稿尚未独立复核；跨问使用必须重新核对适用前提，不能因点名或数值相同沿用。'}


def append_question(raw, source, previous):
    target=source.questions[len(previous)].id
    if len(raw.get('questions',[]))!=1 or raw['questions'][0].get('question_id')!=target:
        raise ValueError('本次只返回指定小问，不得重写前序小问或跳到后问')
    prefix_source=source.model_copy(update={'questions':source.questions[:len(previous)+1]})
    combined={**raw,'questions':[q.model_dump() for q in previous]+raw['questions']}
    return check_outline(combined,prefix_source)


class SplitOutlineProvider(OutlineProvider):
    def generate(self,stage,messages,tools=None,dispatch=None):
        # OutlineProvider creates the schema prompt. Override after that via request,
        # where the same instruction also survives tool continuation turns.
        return super().generate(stage,messages,tools,dispatch)

    def request(self,stage,history,tools=None,**kwargs):
        if stage=='reference_math':
            history=[dict(m) for m in history]
            history[0]['content'] += '\n本次只处理context.target_question指定的一问，questions数组恰好一个元素。不要求解或输出其它小问。previous_outlines是未经独立复核的前序结果，可引用其Qn:Ok步骤但须说明前提仍适用。先核对condition_scope，严禁套用其它构型的长度或角。把工具结果作为内部核对，不必为已经成功的同一计算再次调用。uncertainties只记录尚未解决的题意或证明问题；已修复工具错误保留在审计记录，不冒充未决数学问题。每条必要推理写明依据；不要反复自述检查过程。'
        return super().request(stage,history,tools,**kwargs)


class SplitOutlineRunner(OutlineRunner):
    def validated(self,stage,payload,validate,request_override=None):
        if stage!='reference_math':
            return super().validated(stage,payload,validate,request_override)
        source=Source.model_validate(payload['source']);previous=[]
        for question in source.questions:
            context=question_context(source,question.id,previous)
            context.update(feedback=payload.get('feedback',[]),
                tool_evidence=[r for r in self.records if r.get('kind')=='tool'])
            outline=Runner.validated(self,stage,context,
                lambda raw:append_question(raw,source,previous),request_override)
            write_json(self.directory/f'scoped-outline-{self.provider.calls}-{question.id}.json',outline.model_dump())
            if outline.uncertainties:raise NeedsInput('；'.join(outline.uncertainties))
            previous=list(outline.questions)
        # Full proof is checked again, not just each smaller result in isolation.
        outline=check_outline(outline.model_dump(),source)
        expanded=Runner.validated(self,'math_repair',{'source':source.model_dump(),'math_outline':outline.model_dump()},
            lambda raw:check_expansion(raw,source,outline),request_override={**self.request,'images':[]})
        write_json(self.directory/f'math-expansion-{self.provider.calls}.json',expanded.model_dump())
        return validate({'solutions':[s.model_dump() for s in expanded.solutions]})
