# 本目录接续约束

- 产品目标是可部署 Linux 的 DeepSeek 初中数学 Agent；详细背景见 `接续开发手册.md`。
- 先读取 README、验收记录和调用链，再改代码。不要修改相邻旧项目，不自动 git push。
- 模型只输出声明式 JSON；不能获得任意文件、Shell、网络或代码执行工具。网页由 JSXGraph 原生对象构造与绘制。
- 数学异议回解题，来源异议回识别，构图修复不能改数学解答。缓存命中不得悄悄回退付费模型调用。
- 密钥只在环境变量/.env；不要写入源码、提交、日志、测试记录或部署压缩包。
- Mock 流程通过、模板检查通过、浏览器能打开，都不能表述为真实数学正确率达标。
- 普通测试 `pytest -q`；完整浏览器/Redis 集成测试设置 `MATH_AGENT_BROWSER_TEST=1`。Linux 部署和真实模型验收目前见 `验收记录.md`。
- 一次只运行一个 Worker。取消、超时和重启不能自动重发可能已计费的请求。

## 参考答案分阶段实验

- 最新隔离实测见 `evaluation/isolation-v1/验收记录.md`：6组独立阶段实验，不是端到端成功。`scripts/evaluate_isolated.py` 会产生真实模型费用，不得自动重跑；thinking_override只用于显式实验，生产默认行为不变。

- `AGENT_REFERENCE_MODE=true` 使用 `reference_flow.py`，仅限带参考答案的旋转/平移题。旧模式仍保留，不得把不支持或失败任务自动切回旧模式计费。
- 数学独立复核后用题设+解答哈希锁定；只修图时走 `draw_patch`，只更新相关tab。新数学/题设异议必须使旧核验失效并重新核验，不能为省时间忽略。
- 原生构图要求不变；新流程的实题结果见 `evaluation/reference-v1/验收记录.md`，流程测试通过不等于四分钟完整生成达标。

## 当前产品路线（用户明确要求）

- 本服务只做 JSXGraph 在线预览 Agent。GGB/GeoGebra 下载文件是另一产品路线。
- 运行时只走 `math_agent/jsxgraph/`；根目录 `engine/` 为历史自写 SVG 快照，不得重新接入。
- 中点、交点、垂线、平行线、垂足、对称、旋转和平移交给 JSXGraph 原生对象；自有代码负责声明式输入、页面与验收，不重写几何计算器。
- 上游库保持原样，版本、许可和哈希见 `math_agent/jsxgraph/vendor/`。
- 新契约为 `jsxgraph-v1`，不隐式兼容旧 stage。历史样例的显式迁移仅用于离线评测，不代表模型已能输出新契约。
- 最新验收见 `evaluation/jsxgraph/验收报告.md`，旧 low56 报告不是当前后端验收。

## LangGraph 0.3.0

- 当前主流程为 `flow.py` 的 StateGraph，阶段内工具循环为 `agent_loop.py`；不要退回仅调用一次模型的模板流程。
- 浏览器查询与断言分开：ok表示工具执行，holds表示关系真假，expected才表示要求。on_segment点顺序为[起点,终点,待测点]。
- 每次提出架构改进应主动给出可比较方案、建议次序及实际验收限制。最新见 `架构方案与后续建议.md`、`evaluation/langgraph/验收报告.md`。

## OCR / Linux 8666（2026-10-16）

- 当前OCR使用独立Paddle环境和常驻私有服务；源码 `deploy/ocr/service.py`，客户端 `math_agent/ocr.py`。不能把OCR框当数学坐标，不能把答案当题设。
- PaddleX必须至少使用本次锁定的3.4.3；较早版本即使关闭chart也会无条件加载图表大模型。
- 当前CPU配置使用MKLDNN缓存容量1、文字识别batch1，避免连续图片的内存峰值。变更模型/参数后更新PROFILE和AGENT_OCR_PROFILE并重测连续图片。
- OCR出现未决题意时，最多一次仅凭原题重读；仍不确定必须needs_input，不得自动清空uncertainties或过滤异议来放行。
- 部署目录是 `/opt/math-agent-8666`，不是已有旧服务 `/opt/math-agent`。只管理math8666-*服务。
- 真实识别、时延、费用和失败记录见 `evaluation/ocr-linux/验收报告.md`。不得把已部署或单测通过写成整题成功。

## 0.4.0 证据 Agent

- 条件和推导按小问作用域记录；目标与猜想不能充当已知。浏览器断言expected必须附依据编号和rationale。
- 失败断言由独立adjudicate上下文审查；不得直接过滤false放行，也不得把全部false直接派给修图。已有其他异议不可因撤销一个误断言而删除。
- 局部读图仅接受本任务输入图片编号与归一化区域，实际像素传到模型，base64不进审计。参考答案角色不能改变。
- 静态答案图也必须使用原生旋转/平移/交点等派生对象。最新实题验收见evaluation/evidence-agent/验收报告.md。
- scripts/revise_diagram.py是显式管理员修订入口，会产生新的付费任务；不得自动重试已完成任务。

## 预览接口简化

preview_scene输入为spec.tabs中的board与可选controls，不再传Page讲解文字；最终发布Page的严格契约不变。复核上下文删除重复正文但保留solutions、当前构图和工具结果，完整审计仍存盘。真实第36题仍未成功，见evaluation/preview-agent/实测记录.md。

## 检查恢复

inspection_recovery按同图、同小问、同参数、同关系点序及同expected追踪执行错误。只有后续有效观察可解除，数学断言失败仍需审查，原异议不得删除。未知错误不能猜测已恢复。验收见evaluation/recovery-fix/验收记录.md。

## 读题疑问核对

有OCR辅助且存在疑问时，复用一次仅原题source_review，逐U编号裁决并引用明确文字。未决项必须保留；不能按关键词清空。图示只能辅助，解除必须存在对应question_text原文。结果存source-question-review.json，见evaluation/source-review/验收记录.md。

## 文字修图异议裁决

- Runner.review 将 diagram 文字意见（R编号）与失败断言（A编号）一并交独立 adjudicate；只有逐条明确裁决的意见才能撤销或进入修图。原source/math异议逐字保留，不得连带清空unknown/needs_input。
- R编号必须绑定真实小问和对象；仅浏览器渲染成功不是裁决依据。schema和scope错误保留失败记录，不自动猜字段填充。
- 裁决阶段误带expected只产生query_only错误；必须按同图、tab、参数、关系、点序重新执行不含expected的查询，才能解除。该阶段没有有效expected，不能用此规则放宽普通复核的同expected要求。
- 最后一次请求保留工具声明并设置tool_choice=none，只提交阶段JSON；这不是额外预算或自动恢复，也不保证剩余所有阶段足够。
- 当前证据与尚未完成的端到端验收见 evaluation/objection-gate/验收记录.md。

## 原图文字区域与原文证据

- source_views只根据question角色OCR框裁出原始像素，随首次source请求发送；不能把框用于几何计算，不能补画或从答案图补题设。整图与主动局部读图工具均保留。
- Condition.quote为原文、text为解释；校验只能兼容明确排版差异，数字、撇号、负号、上标不得消除。失败必须回本阶段并保留真实未知。
- 最新完整运行/超时与独立识题实验分开记录在evaluation/endtoend-objection/验收记录.md；Pro实验未通过人工识题验收，生产继续Flash。

## 无效查询独立裁决

- 普通执行错误仍须同图同参数有效重做。已知关系的错误点数查询或明确的basis_validation依据错误不能要求原样重做，也不能自动丢弃；partition_pending交独立adjudicate逐条裁决，原source/math异议、未知项、真实断言失败保留。
- math_repair仅返回solutions，保留board/controls，重新生成讲解和证据后必须再观察、复核；原数学异议随上下文传入。
- 当前修复与实验边界见evaluation/endtoend-objection/恢复机制修复.md；完整3～4分钟验收未达标，不得用恢复单项成功替代。


## 跨问证明依赖

proof_dependencies仅追踪模型声明basis_ids的传递条件，辅助独立复核；out_of_scope_conditions不是自动错误，不得一律禁用合法跨问继承。仍需核验漏写依据和数学真伪。classic review、reference math_review、graph_review接入，缓存包含模块哈希；Linux实验记录见evaluation/endtoend-objection/复核取证优化.md。不能把数学单阶段成功写成完整网页验收。


## 精确几何计算工具

symbolic_geometry只做SymPy坐标旋转/平移/中点和测量表达式，不生成图、不替换JSXGraph，也不证明所选坐标符合原题。degree非负且方向显式，符号参数条件随结果返回；零叉积/点积不能自动视为非退化几何关系证明。数学和复核Agent必须检查原图朝向、各小问范围与退化。真实模型使用效果另见evaluation/endtoend-objection/复核取证优化.md。


## 多副本子进程

以python -m启动的子进程必须cwd=父模块ROOT，不能继承调用者目录选择同名旧包。输出/data目录必须先转绝对路径。新任务runtime-manifest.json记录代码来源；隔离实验不可只核对父脚本路径。已纠正的历史实验解释见evaluation/endtoend-objection/复核取证优化.md。

## 当前优先路线：精简流程 + high（用户2026-10-19明确要求）

用户希望减少Agent环节并使用high思考。优先使用现有classic LangGraph三阶段：source→solve（数学+JSXGraph）→review（实际浏览器观察后的统一复核）。不默认叠加outline/expand/reference_transcript/split/proof_audit/review_plan等实验阶段。保留原始图片、数学工具、原生构图、独立复核和实际异议修复；数学问题不能只修图。配置预设deploy/profiles/compact-high.env：solve/review/diagram high，source按已有快速识别策略；最多一次修复，总240秒，12次模型请求预算（工具往返计入）。实际端到端结果以evaluation/endtoend-objection/compact-high-v1为准，不把三阶段误说成固定三次HTTP请求。尚未通过验收不自动宣称已替换线上版本。


## 速度与正确性优先（用户2026-10-19纠正）
用户没有降低token用量的要求。compact-high恢复每请求32000全局额度，阶段额度与预留提前终止关闭。优化优先消除无效往返，不能将更早失败当作提速成功。验收需同时给出准确性与完整端到端时间；为观察完整结果而显式延长诊断任务截止时，必须标明这不代表4分钟目标达标。

## 数学纠错优先（2026-10-19接续）

统一review已有实质source/math异议时，图形或非法检查争议连同原版本完整暂存，先回对应Agent纠正。暂存不是解除；当前版本重新观察、独立复核后，deferred_review逐条裁决，绑定原/当前哈希与当前小问/对象/依据。未决义务不能写成功缓存或发布，显式恢复也要加载存档，不能自动重发付费请求。

compact模式math_repair现在只返回updates（Q编号→reason+完整proof）；未提交问的证明与全部几何对象由服务器保留。非compact仍用原solutions契约。数学修正不自动意味着图已正确；重新渲染与复核、真实异议分流保持。实测记录见evaluation/repair-priority/，生产未自动替换。

## 串行局部数学复核实验

`AGENT_INCREMENTAL_MATH_REVIEW`默认关闭，需compact。只有原图实际字节、完整题设、代码版本和原生构图未变、旧条件全pass且无unknown、原数学异议可定位时，才能按新旧依赖闭包重审修改问；其他问须逐字未变且旧检查明确pass。全部条件和画板仍可见，tab不重编号，任何新异议、工具失败、proof_guard及deferred义务仍阻断发布。首次复核不缩范围，缺依据/无法定位/构图或题设变化回完整复核。收据随缓存保存并校验，不能称形式化证明。验证及一次Linux完整验收见evaluation/math-review-scope/。

第20题实测发现零长度segment被当成无定义line误报；本机观察器已区分，但支撑直线和无定义派生点仍阻断。审计seconds改为任务累计，模型单请求时间存duration_seconds。实模完整验收仍失败，原Q1在180°相似证明漏边界；异议已存档，不能把结论核对或本地重渲染当成教学通过。详见evaluation/math-review-scope/验收报告.md；后续付费先报告上一轮结果与费用，等待用户指示，不自动重跑。

## Agent选择的静态旋转只读取证

review提供`probe_rotation_rule`，Agent显式选择真实步骤、三角形与完整旋转组及角度，只生成原生假设副本。不能传任意spec、部分移动对应顶点、把假设当题设或把共线当默认图错误。工具失败不是通过；已观察反例与unobserved前提都交原有adjudicate/deferred规则。没有新增固定审查阶段，也不自动调用模型。仅本机代码与离线/浏览器接入验证，未证明DeepSeek自主调用成功，未部署生产。已返回用量费用后仍等用户指示才能新增付费请求。记录见evaluation/rotation-probe/验收记录.md。

## inspect_scene参数格式恢复（2026-10-20）

格式无效请求不执行。参数校验须返回Schema路径及可唯一绑定的整批检查目标（当前spec哈希、tab、参数、关系、点顺序、expected），后续同图同目标真实成功才能解除该执行错误；不自动改拼写、不改expected或删原断言。无法绑定的错误仍阻断。运行成功但数学结果false仍保留原失败进入裁决，错点数/非法依据及其他diagram/math异议不可连带清除。Runner各只读阶段和SceneTools入口共用schema_failure；回归417项通过，付费复测另以q22-full-v2实际记录为准。

复测q22-full-v2含恢复修复，116.389秒因相机边缘点裁切失败，未进入review，不可称实模恢复验收通过。随后adapter.fitView增加12px屏幕留白，保留完整数学范围、坐标及等比例，真正越界仍拒绝；419项完整回归通过。本轮已修图最终候选5页离线重绘通过，原始solve非法bbox顺序仍拒绝。留白未再付费实测、未部署生产；详见evaluation/random-deepseek-20261020/schema-recovery-fix/修复与复测.md。
