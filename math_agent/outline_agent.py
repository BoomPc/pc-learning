"""Opt-in outline experiment using the existing reference LangGraph and publish gates."""
import json
from .provider import DeepSeek
from .pipeline import Runner, NeedsInput
from .contracts import Source
from .math_outline import MathOutline, ExpandedMath, check_outline, check_expansion, OUTLINE_TASK, EXPAND_TASK
from .storage import write_json

TEACHING_POLICY = '''学生讲解必须使用初中可理解的证明：全等、相似、等腰、平行垂直、勾股、特殊直角三角形、基础方程等。不得以向量数量积、旋转矩阵、三角和角公式或高中三角函数方程作为学生证明的必要依据。工具内部可用坐标进行独立校验，但不能代替学生证明。参考答案只是可核对的解法材料，不是新增题设；须补全其中跳步、逐问核对条件。辅助点名称不得与原题其它点重名。不能完成初中证明时明确保留未决项。'''


class OutlineProvider(DeepSeek):
    def generate(self, stage, messages, tools=None, dispatch=None):
        messages = [dict(m) for m in messages]
        if stage == 'reference_math':
            task = OUTLINE_TASK.replace('本阶段没有图片或参考答案，不假装读过图片。',
                '本阶段提供原始题图与参考答案图片；先核对答案里的方法和点名，再独立完成必要推导。')
            messages[0]['content'] = task + '\n' + TEACHING_POLICY + '\nJSON Schema：' + json.dumps(MathOutline.model_json_schema(), ensure_ascii=False)
        elif stage == 'math_repair':
            messages[0]['content'] = EXPAND_TASK + '\n' + TEACHING_POLICY + '\nJSON Schema：' + json.dumps(ExpandedMath.model_json_schema(), ensure_ascii=False)
            tools = []
        elif stage == 'math_review':
            messages[0]['content'] += '\n' + TEACHING_POLICY + '\n复核学生证明的方法与每个跳步。若仍依赖上述超纲方法或缺少关键推导，提出stage=math的具体异议，不能仅因最终数值正确而pass。'
        if stage in {'reference_math', 'math_review'}:
            tools = [t for t in tools or [] if t['function']['name'] != 'read_evidence']
        return super().generate(stage, messages, tools, dispatch)

    def request(self, stage, history, tools=None, **kwargs):
        if stage in {'reference_math', 'math_repair', 'math_review'}:
            kwargs.update(thinking_override=stage != 'math_repair', json_mode=stage != 'reference_math')
        return super().request(stage, history, tools, **kwargs)


class OutlineRunner(Runner):
    def validated(self, stage, payload, validate, request_override=None):
        if stage == 'reference_math':
            source = Source.model_validate(payload['source'])
            outline = super().validated(stage, payload, lambda raw: check_outline(raw, source), request_override)
            # Retain every revision: never overwrite evidence of a previous failed proof.
            version = self.provider.calls
            write_json(self.directory / f'math-outline-{version}.json', outline.model_dump())
            if outline.uncertainties:
                raise NeedsInput('；'.join(outline.uncertainties))
            expanded = super().validated('math_repair', {'source': source.model_dump(), 'math_outline': outline.model_dump()},
                lambda raw: check_expansion(raw, source, outline), request_override={**self.request, 'images': []})
            write_json(self.directory / f'math-expansion-{version}.json', expanded.model_dump())
            return validate({'solutions': [s.model_dump() for s in expanded.solutions]})
        if stage == 'math_review':
            payload = {**payload, 'tool_evidence': [r for r in self.records if r.get('kind') == 'tool']}
        return super().validated(stage, payload, validate, request_override)
