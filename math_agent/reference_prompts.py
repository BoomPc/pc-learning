"""Stage-specific instructions; no full page rewrite when repairing geometry."""
import json
from .contracts import Review
from .reference_flow import MathDraft, DrawingPatch
from .scene_tools import PreviewSpec


def schema(model):return json.dumps(model.model_json_schema(),ensure_ascii=False,separators=(',',':'))

GEOMETRY='''只输出JSXGraph原生声明式图形。点名忠实原题。旋转点必须rotation、平移点translation、交点intersection、中点midpoint、垂足perpendicularpoint，不得把派生点写死成point.coords。
rotation.parents=[原点,中心]，新构图必须用direction="clockwise"（顺时针）或"counterclockwise"（逆时针）和degrees=非负度数；不要手算弧度正负，不要同时填写旧angle；translation.parents=[原点]、vector=[dx,dy]；parallel/perpendicular.parents=[线,点]；intersection.parents=[两线或曲线]且branch=0或1；reflection/perpendicularpoint.parents=[点,线]。表达式只用显式算术、pi、sqrt、sin/cos/tan、abs、min/max、参数t（仅动态页）或函数变量x，不支持对象坐标引用、atan/acos/asin。基本锚点可用point；派生交点必须由真实对象构造。
每问一tab，顺序同source.questions。几何点图用board.viewport="fit_points"，可省略bounding_box；工具按真实可见点在每个参数位置自动适配视野，不改变数学或参数域；函数/无限曲线需要指定manual视野。preview_scene仅需spec.tabs的board/controls和probes，不需要讲解文字。不要为已有数学结论重新推导整题。只在有必要观察分支/参数时批量调用预览。静态答案图可行但必须忠实标明各分类位置，不能漏掉分类；没有必要不要引入复杂滑块。动态域和退化位置必须与已核验解答一致。每个图都包含必要点和辅助线，不显示无关无限辅助线。'''


def task_for(stage):
    if stage=='reference_math':
        return '''按原题逐小问整理参考答案中的解法，不能把答案当题设。先采用已给解法，不另找多种解法或从头穷举搜索。参考答案看不清可局部读图；真实缺失/错误须明确指出，不得编造。
仅输出数学解答solutions，不输出图形、HTML、页面标题或重复题干。保留证明依据、关键等式、全部分类、定义域与退化情况；去掉重复解释。每步basis_ids引用题设C或先前Qn:Sm，目标Q不是已知。同一长度在不同位置数值相同也不能直接跨问引用；沿用结论须明确依赖条件在当前小问仍成立，否则在当前条件独立推导。涉及旋转平移坐标时优先用symbolic_geometry计算，再核对该坐标系与原图朝向相容；镜像坐标不能保留原顺逆时针方向。不要把坐标约定错误当成题设不充分。重要代数可一次algebra_batch批量核对，所有符号必须列入variables。之后独立数学复核会检查完整性。输出JSON：'''+schema(MathDraft)
    if stage=='math_review':
        return '''独立核验完整数学解答：对照原题与参考答案，查题设转写、关键推导、所有小问和分类、边界及退化。不要重新搜索整题解法；沿现有证明检查关键等式及前提。必要时一次algebra_batch核对（所有符号须在variables中），数值抽样不能代替一般证明。此阶段没有图形，不评价排版或构图，不输出diagram异议。
proof_dependencies列出声明依据的传递关系；逐条核对跨问引用的局部条件是否仍成立，特别是out_of_scope_conditions。它不是自动错误判定，也不能发现模型漏写的依据。已证明条件继承则允许引用；否则必须独立重推，不得因答案数值一样放行。
完整覆盖source.conditions与questions，逐项给出具体证据。真缺失needs_input，数学/题设错误revise并准确归属math/source；全部检查通过才pass。issues非空不能pass。答案不是题设、公理或正确性保证。返回JSON：'''+schema(Review)
    if stage=='draw':return GEOMETRY+'\n数学解答已单独核验并锁定，禁止改写。仅输出所有tabs的board和可选controls，不输出solutions或讲解文字：'+schema(PreviewSpec)
    if stage=='draw_patch':return GEOMETRY+'\n仅修复feedback指向的图，数学已锁定；输出updates中需要改变的tab（从0开始）的完整board和可选controls，未列出的tab保持不变。禁止输出数学解答或整页：'+schema(DrawingPatch)
    return '''你是图文一致性核验阶段，完整数学解答已通过独立math_review，附核验版本。无需从头重证数学；只检查图是否落实该解答与原题、对象关系/标签、每种分类是否展示、参数边界与可见性。
对照原题图、当前board对象、浏览器真实坐标和截图，必要时批量inspect_scene。不检查旧草稿的美观。所有小问和条件都给图文对应证据；某条件纯数学不需绘制可明确说明。真实几何冲突提出diagram异议；若发现新的数学/题设问题，必须提出math/source异议使数学版本失效，不能替模型改答案。
检查原生构图：旋转/平移/交点/中点/垂足必须为对应原生kind，静态位置也不得用独立坐标硬编码这些派生点。检查顺序先对象定义再关系，已有明确缺陷可以直接提出异议，避免反复无目的查询。
inspect_scene每个probe都必须显式填写从0开始的tab编号，不能省略。inspect_scene中expected必须引用当前小问适用的basis_ids和rationale；不确定预期时省略expected查询。工具ok与关系holds不同，false不一定是错误，断言失败会另行审查。point ID必须真实存在；on_segment顺序[起点,终点,待测点]。不能因为追求速度而放行未决问题。返回Review JSON：'''+schema(Review)
