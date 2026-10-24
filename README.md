# Linux 初中数学 Agent

> 源码发布说明：本仓库不包含生产凭据、服务器连接信息、原始任务数据和实验日志。文中 `evaluation/` 路径对应私有开发记录，未随源码发布。历史单题结果不代表当前版本的整体准确率或3～4分钟耗时目标已达标。配置与数据边界见 [PUBLICATION.md](PUBLICATION.md)。

这是可独立运行的 Linux 服务：题目文字/题图 + 可选答案图 → PaddleOCR 文字/公式（可配置）→ DeepSeek 对照原图识别 → 解题与数学工具 → 重新对照原图复核 → JSXGraph 原生对象生成在线交互讲解。

**当前版本 0.4.0：数学证据记录 + 复核自纠错 + 局部原图查看。第48题真实整题已生成并通过核验，包含一次显式原生构图修订；不代表题库整体准确率已达标。** 最终四问使用JSXGraph原生rotation/translation，保留全部讲解。真实过程、耗时、费用与限制见 [本轮验收](evaluation/evidence-agent/验收报告.md)，[打开成品](evaluation/evidence-agent/final/result.html)。部署见 [部署说明](deploy/README.md)。

此版本调用云端模型，Linux 机器不需要 GPU，也不需要先训练模型。题图、答案图和题目内容会发送到配置的模型 API。服务本身负责调度、核验、缓存和渲染。

## Agent 的实际控制范围

2026-10-18读题优化：OCR文字框仅用于附加原图局部像素，首次识题同时看整图和文字区域；引用校验区分原文quote与释义，仅兼容全半角排版差异。线上仍用Flash。最新未达标项及真实完整耗时见[完整输入验收](evaluation/endtoend-objection/验收记录.md)，历史成功页不能替代当前版本验收。

2026-10-18新增文字修图异议独立裁决：每条意见先绑定题设、小问和对象，再决定是否修图。原数学/读题异议和未知项保留；最后一次模型调用只提交结果。局部实测与完整生成限制见 [异议裁决验收](evaluation/objection-gate/验收记录.md)。

2026-10-18阶段隔离实验已完成，见[隔离验收记录](evaluation/isolation-v1/验收记录.md)：正确数学输入下构图仍会失败；关闭思考可更快但会生成错误证明。实验未达到整题目标，未切换线上默认流程。

实验流程可通过 `AGENT_REFERENCE_MODE=true` 启用：题设识别 → 整理参考解法 → 独立数学核验 → 原生构图 → 浏览器观察 → 图文核验。数学通过后记录题设与解答的哈希；纯构图异议只更新相关图，不重新生成数学解答。新数学或读题异议仍回到对应阶段并使旧核验失效。该记录是模型核验记录，不是形式化证明。

此实验仅接收带答案图片的旋转/平移题，不支持时明确失败，不自动切换到另一条付费流程；显式恢复旧任务仍使用原有流程。模型仍可自主选择局部读图、代数验证及浏览器观察工具。开启实验模式与旧流程使用不同缓存键。当前是否达到 240 秒目标，以 `evaluation/reference-v1/` 的真实测试记录为准。

`math_agent/flow.py` 用 LangGraph StateGraph 管理读题→解题→浏览器观察→复核及条件修复分支；`math_agent/agent_loop.py` 用第二层 StateGraph 执行“模型选择工具→工具观察→模型继续”的循环。模型自主选择算什么、观察哪些点和参数；服务控制预算和发布条件。它不是通用编码代理，没有任意文件/终端权限。

- `preview_scene`：解题/构图阶段可把草稿交给JSXGraph观察。
- `inspect_scene`：复核阶段只读检查当前候选，不能另换一张图。
- `algebra_batch`、`geometry_check`、`knowledge_search`：代数、数值关系、本地方法检索。
- `view_image_region`：按模型选择放大原题/答案局部，下一轮直接查看真实像素。
- `read_evidence`、`record_hypothesis`：按小问查看证据和记录待检验猜想，猜想不能作为已知。
- `adjudicate`：失败断言交给独立上下文审查，区分错误检查、真实问题和未决问题，保留依据与裁决记录。

每个任务记录图节点、工具参数与返回值、模型用量（接口提供时）、观察与修复原因。LangGraph没有自动重放中断请求；本地任务审计保留，云追踪关闭。

## 已实现的流程

1. 题图与答案图分开上传、分开标记。服务解码图片后转 PNG，保留图片编号和内容哈希。
2. 识别出独立的条件清单、小问清单、来源和不确定项。条件不得引用答案图充当题设；看不清时返回 `needs_input`。
3. 模型按小问给出“前提、依据、结论、分类、边界”，可调用 SymPy 代数、坐标关系检查和本地方法检索。
4. 先实际渲染，再让新的模型上下文重新读取原图、浏览器坐标和截图，选择需要进一步观察的参数与关系，逐条件、逐小问复核；发现遗漏题设也必须提出异议。浏览器断言必须引用适用条件或推导；失败后先审查断言本身的依据。复核意见按读题、推导、构图分别回送；构图修复不能更改数学解答。
5. 解答统一填充网页步骤和结论。模型仅提供声明式对象 JSON；JSXGraph 负责几何构造与绘图，Chromium 回读原生对象并检查参数采样、未定义对象和可见点裁切；包含靠近端点的额外采样，仍不是完整区间证明。
6. 默认缓存已通过复核且成功渲染的模型数据。相同输入命中 Redis 后只重新跑引擎；`force=true` 才重新问模型。缓存键还包含模型、接口、题图角色、提示词版本、数据契约和工具版本。

读题、解题、复核的结构校验失败时，把具体错误和原输出交回同阶段纠正一次，计入原有模型调用预算；不会删除未知条件或异议来强行放行。每题有模型调用上限、修复次数上限和总时间上限。没有悄悄换模型或自动无限重试；HTTP 错误、截断、空结果都会明确失败。进程重启后，运行中任务标记为中断，不会自动再花一次模型费用。

## 在 Linux 上部署

准备 Docker Engine 和 Docker Compose 插件。代码里配置 Worker 使用最多 2 CPU / 3 GiB 内存，API 与 Redis 另占内存；给整机留出操作系统和浏览器余量。先在已有普通 CPU 服务器试运行，尚未测过最低配置。

把整个目录传到 Linux，例如 `/opt/math-agent`。不用传 `.venv/`、`data/`、`.git/`。

```bash
cd /opt/math-agent
python3 scripts/init_env.py
chmod 600 .env
```

该脚本只生成服务访问令牌，不生成 DeepSeek Key。编辑 `.env` 填入：

```dotenv
DEEPSEEK_API_KEY=你的DeepSeekKey
DEEPSEEK_MODEL=deepseek-flash
```

`AGENT_ACCESS_TOKEN` 是调用你自己网站接口的令牌，与 DeepSeek Key 是两件事，初始化脚本已经生成。不要把 DeepSeek Key 写到网页、提交到 Git 或发给浏览器。

```bash
docker compose config --quiet
docker compose up -d --build
docker compose exec worker python -m math_agent.cli doctor
docker compose ps
```

首次构建需要联网下载 Python 包、Chromium 和中文字体。`doctor` 不会调用付费模型，只检查配置、浏览器启动和 Redis。模型是否可用须真实请求验证。

修改 Key 或模型后重新创建容器，单纯 `restart` 不会重新加载 Compose 环境变量：

```bash
docker compose up -d --force-recreate api worker
```

默认只绑定 `127.0.0.1:8000`。在你自己的电脑建立 SSH 转发即可测试：

```bash
ssh -N -L 8000:127.0.0.1:8000 用户名@服务器IP
```

需要接入现有云网站时，让网站后端带服务令牌访问此 API。公网部署时用现有 HTTPS 反向代理转发到本机 8000，上传大小至少 200 MiB；不要把服务令牌写入公开前端。当前是单租户服务，持有令牌即可查看所有任务，不包含教师账号、用户隔离、计费或管理后台。

## 浏览器上传与在线预览

启动后访问 `http://127.0.0.1:8000/`，输入 `.env` 中的 `AGENT_ACCESS_TOKEN`，上传题图和答案图或输入文字，点击“生成讲解”。页面展示进度，完成后在隔离 iframe 中在线预览。可以凭任务编号恢复查看、取消任务，或勾选强制重新问模型。

令牌仅保留在当前页面内存，不写浏览器存储或 URL。集成云网站时应由网站后端代理鉴权，不要向所有访客公开服务令牌。当前工作台是单租户。

## API 与命令行

客户端 Python 3.11+，本项目本地开发验证使用 Python 3.12：

```bash
python3.12 -m venv .venv
.venv/bin/pip install -c constraints.txt -e '.[test]'
export AGENT_ACCESS_TOKEN='服务器.env里的服务访问令牌'
.venv/bin/math-agent submit \
  --question '/本机路径/题图.png' \
  --answer '/本机路径/答案图.png' \
  --output './downloads'
```

客户端提交图片给服务，不需要 DeepSeek Key。多图重复使用 `--question` 或 `--answer`；无答案可省略；纯文字用 `--text '题目内容'`。同题重新询问模型加 `--force`，会重新计费。

也可以直接用 HTTP：

```bash
curl -sS http://127.0.0.1:8000/api/jobs \
  -H "Authorization: Bearer $AGENT_ACCESS_TOKEN" \
  -F 'question=@/本机路径/题图.png' \
  -F 'answer=@/本机路径/答案图.png' \
  -F 'force=false'
```

| 接口 | 用途 |
| --- | --- |
| `GET /` | 上传与在线预览工作台，不包含密钥或任务数据 |
| `GET /api/jobs/{id}/preview` | 完成后的受保护 inline HTML，供工作台隔离预览 |
| `GET /healthz` | 进程存活，不需要令牌 |
| `GET /readyz` | 配置与 Worker 心跳检查，需要令牌；不验证云端 Key 的有效性 |
| `POST /api/jobs` | multipart 表单：`question`/`answer` 文件、`text`、`force` |
| `GET /api/jobs/{id}` | 状态、阶段、摘要、最多50条事件和下载路径 |
| `POST /api/jobs/{id}/cancel` | 取消排队或运行任务；已发出的模型请求仍可能计费 |
| `GET /api/jobs/{id}/artifacts/result.html` | 完成后下载单文件网页 |
| `GET /api/jobs/{id}/artifacts/preview.png` | 完成后下载预览 |
| `GET /api/jobs/{id}/artifacts/report.json` | 完成或失败后的核验与工具记录；硬终止可能来不及生成，状态接口仍保留原因 |

一次最多6张静态 PNG/JPEG/WebP，每张原始文件≤8 MiB，像素≤1600万，长边≤10000。请裁剪到完整题目，太小的字仍可能无法识别。服务默认串行处理，最多20个排队/运行任务。

状态有 `queued`、`running`、`completed`、`failed`、`needs_input`、`cancelled`、`interrupted`。失败不会开放半成品网页下载。

## 本机开发和无 Key 演示

Linux/macOS 可以跑开发环境。正式交付以 Linux 为目标；Windows 建议使用 WSL2 + Linux Docker，本版没有原生 Windows Worker。

```bash
python3.12 -m venv .venv
.venv/bin/pip install -c constraints.txt -e '.[test]'
.venv/bin/python -m playwright install chromium
# Linux 缺浏览器依赖时：.venv/bin/python -m playwright install --with-deps chromium
.venv/bin/pytest -q
.venv/bin/python scripts/offline_demo.py
```

离线演示输出 `data/offline-demo/output/result.html`，页面明确标注“非模型生成”。Linux 中文显示使用镜像中的 `fonts-noto-cjk`。浏览器路径可设 `MATH_AGENT_CHROMIUM_EXECUTABLE`；兼容旧 `GGB_CHROMIUM_EXECUTABLE` 仅为方便本地测试，不表示使用 GGB。

本地运行真实服务时，设置 `DEEPSEEK_API_KEY`、`AGENT_ACCESS_TOKEN` 后，在两个终端分别运行：

```bash
.venv/bin/math-agent serve
.venv/bin/math-agent worker
```

源代码运行不会自动读取 `.env`；可使用 shell 导出变量，或在可信的 `.env` 文件创建后 `set -a; . ./.env; set +a`。未配置 `REDIS_URL` 时明确禁用缓存，每次都会调用模型；Compose 会自动配置 Redis。请使用本目录 Dockerfile 或新版源码发布包；其中包含本地 JSXGraph 库与许可。

## 数据、费用和排错

- Compose 的 `jobs` 卷保存原图、结构化模型输出、核验记录、SQLite 队列和成品；`cache` 卷保存 Redis。数据默认不自动删除，需按你的业务保留周期备份和清理。`docker compose down` 保留卷，**不要用 `down -v`，除非明确要删除任务和缓存**。
- `audit.json`/`report.json` 记录阶段时间、实际工具调用、token usage、模型调用次数和异议。模型的 `reasoning_content` 仅为工具调用协议在内存里往返，不保存为学生讲解。
- 默认每题10次模型请求、最多2次修复、总时限600秒；每次最大输出12000 token。并非要求每题一定用满。费用以实际 usage 与供应商账单为准，没有预设“准确率提升多少”或“几秒完成”的承诺。
- 401：核对 Key。402：余额。403/400：核对账号权限、模型名、图片能力或请求参数。429：限流。服务不会自动重复支付。
- Redis 读取失败会停止普通任务，避免缓存故障导致意外重新花费。`force=true` 明确允许跳过读缓存。缓存写失败会记录，本次成品仍保留。
- 缓存命中后的引擎错误不会重新调用模型。修好引擎重新提交即可复用；如果确实需要改模型输出，明确 `force=true`。
- 本地进程退出不等于云端请求一定取消；这也是不自动重跑中断任务的原因。

## 模型与引擎边界

2026-10-15 核对的 DeepSeek 官方文档列出 `deepseek-flash` 支持图片、JSON 输出和工具调用，默认配置据此编写。你的账号可用性尚未真实验证；模型名或能力变化时应重新核对文档。较早的“DeepSeek 只能文本”判断不适用于此次核对到的模型版本。

- [模型与能力](https://api-docs.deepseek.com/quick_start/pricing/)
- [图片输入](https://api-docs.deepseek.com/guides/vision/)
- [思考模式与工具往返](https://api-docs.deepseek.com/guides/thinking_mode/)
- [JSON 模式](https://api-docs.deepseek.com/guides/json_mode/)

当前渲染链路：`rendering.render → jsxgraph.spec.validate → jsxgraph.export → adapter.js → JXG.Board.create`。使用本地固定的 JSXGraph 1.11.1（MIT），上游代码保持原样，许可、来源和 SHA-256 见 `math_agent/jsxgraph/vendor/`。

中点、交点、垂线、平行线、垂足、轴对称、旋转、平移和受约束拖动点由 JSXGraph 创建和维护。自有适配层只允许有限声明式 JSON 与算术表达式，不执行模型提供的 JS，也不自行求交点或同步依赖坐标。参数化点和函数仍需模型提供正确表达式，关系编码仍需对照原题复核。

旧 `engine/`、`VENDOR.json` 和 `evaluation/low56/` 是历史记录，不进入当前运行链路或新版部署包。新版契约与旧缓存不兼容，缓存键已分版本：首次提交新版会重新询问模型，同一新版输入之后仍复用缓存。旧网页不会自动改变。`scripts/evaluate_jsxgraph_cases.py` 重放显式迁移的 9 个局部场景，不调用模型。

当前复核仍来自同一个模型的新上下文，可能共同犯错；工具只能检查正确编码后的计算/坐标关系，不能证明图片识别完整，也不是通用几何证明器。浏览器检查覆盖运行和基本交互，不能保证图与原题关系完全正确。上线用于教学前，需要带参考答案的真实题验收，尤其检查你最在意的漏条件、点线关系、分类边界和生成图。下一步说明见 `接续开发手册.md`。

## 精简 high 配置（2026-10-19）

按当前用户选择，优先验证三阶段经典Agent：读题 → 一次生成完整数学解答和原生JSXGraph → 浏览器观察后统一复核。`deploy/profiles/compact-high.env` 提供非敏感配置预设；解题、复核和必要修图使用high，读题沿用快速识别。关闭参考答案分阶段、展开、分问和复核预规划路线；只有实际错误才进入最多一次修复，仍计入240秒/12次请求总预算。

可用 `scripts/evaluate_compact_high.py --env <服务环境文件> --origin <已有任务图片目录> --out <新的实验目录>` 进行真实付费验收。脚本创建隔离任务、强制重新调用模型且禁用网页Redis缓存；OCR服务缓存是否命中必须另查审计。它不自动修改线上.env或重启服务。预设不是验收通过声明。

compact-high 精简输出实验：启用 `AGENT_COMPACT_TOOLS=true` 时，solve 按 source 的每个 Q 编号输出唯一对象（proof、board、可选 controls），服务端恢复统一 Candidate，再走原有构图、证据和独立复核。标题/题干及展示步骤不再让模型重复生成；缺问、多问、JSON 重复键均不能静默放行。diagram 和 math_repair 保持原契约。solve 首次请求附带最多 8 个重叠的原始像素分区，同时保留整图和主动裁图工具。该设置不保证时延或数学正确率；隔离实题结果见 `evaluation/endtoend-objection/compact-high-v3/`，未自动替换线上服务。

compact-high 阶段预算实验：`DEEPSEEK_SOLVE_MAX_TOKENS=16000`、`DEEPSEEK_REVIEW_MAX_TOKENS=12000` 为单次请求的思考＋正文总额度（0表示沿用全局），不改变 high。`AGENT_REVIEW_RESERVE_SECONDS=80` 时，从 Provider 创建时开始累计前序耗时，首次进入复核前预留80秒及5秒渲染余量；请求按剩余时间设置HTTP超时，迟到结果不能继续。剩余不足55秒的下一轮禁用工具选择、要求完整结果；未完成仍失败，不能跳过复核。HTTP读超时不是远端强制停止，总任务仍由worker硬截止；已发送请求可能计费。这是预算调度实验，不保证模型在额度内生成完整证明。新增设置默认0，不改变未启用的生产配置。

2026-10-19 速度优先修正：当前 `compact-high.env` 已撤销上一段的阶段限额实验，`DEEPSEEK_SOLVE_MAX_TOKENS=0`、`DEEPSEEK_REVIEW_MAX_TOKENS=0`、`AGENT_REVIEW_RESERVE_SECONDS=0`，沿用全局32000及high。读题提示要求直接复制Unicode原文引文，已核实的OCR误差不应写入未决疑问；服务端仍严格校验引用和真实未决问题，没有自动清空疑问。评测脚本支持显式 `--timeout` 观察完整结果；超过240秒仍不满足产品时延目标。

compact-high 局部修图：diagram 阶段现在只返回 `DiagramPatch.edits`，按tab增改/删除指定JSXGraph对象，可显式调整视野/控件；不接收数学证明和整页正文。服务端深拷贝旧Candidate，严格校验对象引用及页面契约后重新渲染、复核。缺边不再要求模型重写整份Candidate，防止cases等数学字段混入Tab。详见 `evaluation/endtoend-objection/compact-high-v5/` 的完整运行与独立修图记录；独立修图不算新的整题耗时。

`AGENT_INCREMENTAL_REVIEW=true`（当前compact-high实验启用）只在同一任务内保存已完成复核的数学记录：原图实际字节、题设、solutions、输入文字和绘图引擎版本绑定，全部条件/问题pass且只有diagram异议时，修图后使用独立`diagram_review`检查所有变化画板、控件及原异议。任何数学/题设变更、未知项或新数学异议使复用失效。新阶段保持high与完整额度，仍执行真实浏览器、工具查询恢复及异议裁决。该记录是版本绑定的模型审核证据，不是形式化证明，也不能替代首次完整复核。当前真实整题与正反控制试验见`evaluation/endtoend-objection/compact-high-v6/`；模型pass仍需人工检查辅助点线等讲解完整性。

后续复核协议修正：compact完整复核的conditions/questions按source的固定编号键输出，服务端转换回公共Review数组；发现额外题设必须报source异议。格式纠正携带本次新取得的真实工具记录。局部diagram_review工具仅允许查询变化tab且不填expected，最终判断仍由模型结合实际关系作出；首次完整review的依据断言与失败恢复保持。证书链与缓存一起保存、校验，数学版本变更后重新完整复核。

修图后的独立裁决也采用精简输出：仍逐异议独立判断，仅返回决定及明确作用域内的核验更新；服务端保留原条件、数学/读题异议和未受影响的小问，继续经过原有`validate_resolution`门禁。纯复核编号覆盖错误采用仅输出的格式纠正轮，沿用真实证据；若证据不足仍须保留unknown/异议。数学问题、失败查询等语义错误不会被归为这种格式纠正。


## 2026-10-19 晚间结构化复核实验

`AGENT_REVIEW_RESPONSES=true` 仅在DeepSeek compact模式下，将统一review改用原生Responses JSON Schema。source、solve、diagram、adjudicate及其他流水线继续原接口；生产默认关闭。保留LangGraph工具循环、原图像素、工具调用配对和思考上下文；本地仍严格校验JSON、编号、数学证据和浏览器关系。HTTP错误、截断或Schema失败不会自动回退Chat接口或重新付费。缓存键区分协议。

该能力可减少JSON形状错误，但不能保证证明正确或high推理耗时。真实验收见 `evaluation/endtoend-objection/evening-responses-v1/`；此前2.31秒探针仅为协议兼容测试。

## 2026-10-19 数学纠错优先与暂存检查

统一review同时发现实质source/math问题与图形/检查争议时，先回对应Agent修正。原检查连同当时题设、证明、图形、观察与哈希保存在任务的 `deferred-reviews.json`，不把暂存当通过。修改后先实际渲染、重新独立复核，再对暂存项逐条判定；原记录、当前版本和小问依据必须对应。未知项阻止发布，真实问题继续分流，缓存不能绕过未决义务。重启读取暂存记录，但不会自动重发模型请求。

compact模式的math_repair使用 `updates` 按小问提交完整proof及修改理由；服务器保留未提交小问与几何对象，避免局部符号错误引起整题重写。非compact模式保留原MathRepair契约。复核接收经哈希核对的实际改动范围和前次复核记录作为参考，仍覆盖全部小问，不能将旧pass当数学公理。原生Responses开关开启时，math_repair和暂存裁决也使用JSON Schema。

真实回放与付费闭环分别记录在 `evaluation/repair-priority/`。单测、诊断闭环、完整新题生成是不同验收范围，不能互相代替。生产配置尚未切换。


2026-10-19后续：新增超限长图全像素分区、命名线段平行符号编码兼容与明确点/线参数角色绑定（不改JSXGraph库）。数学纠错优先与按问修订已经完成回放及真实诊断；317项回归通过。第52题有补复核pass的诊断草稿，完整四分钟与无人审核教学交付仍未达标，人工端点证明问题保留。详见evaluation/repair-priority/验收报告.md；生产未切换。


本地后续（未新增付费调用）：显式端点沿用三角形定理时增加原生假设观察，退化反例进入现有独立裁决或数学优先暂存；不新增正常成功路径的模型阶段。识别有界，不能当任意证明器。完整330项回归及14项专项通过，真实模型是否能按反例正确纠错、四分钟完整生成仍未验证。详见evaluation/repair-priority/验收报告.md末节。

串行数学局部复核实验：`AGENT_INCREMENTAL_MATH_REVIEW=true`（需要compact）只在同一任务中按实际原图字节、代码版本、题设和完整候选绑定旧复核。数学修订后，重新核验全部条件、所有修改问及新旧跨问依赖的后继；仅未变且原检查明确pass的小问保留原证据。原图/构图改变、未知项、异议无法明确定位或依据缺失时回到完整复核。所有原始tab编号、画板、只读工具、原异议与暂存裁决保留，新发现的范围外问题仍阻断发布。收据保存在`math-review-receipts.json`，随缓存保存并核对摘要和合并；当前默认关闭，不代表四分钟实题验收通过。

统一数学复核新增可选只读工具`probe_rotation_rule`：Agent可选择静态图中完整同中心旋转组、某一步的三角形及至多四个假设角度，观察原生JSXGraph的退化前提；默认图、证明不变。不自动判定角度符合题意，不把共线直接归为图错。实际反例或未完成取证进入现有独立裁决/数学优先暂存，不增加固定模型阶段；失败和未知不能静默通过。已有滑块场景继续`inspect_scene`。工具与裁决接入经离线和真实浏览器测试，DeepSeek是否自主选对情形、是否修订成功及总耗时尚未验证，生产未部署。见`evaluation/rotation-probe/验收记录.md`。

inspect_scene参数格式错误现在在执行前记录具体Schema路径及同图检查目标。只有原tab、参数、关系、点序和expected完全一致且实际执行成功的后续查询，才能解除该执行错误；不会自动更名字段、删断言或把数学失败改pass。无法唯一识别的目标继续阻断，错点数或非法依据仍交独立裁决。所有只读复核阶段及SceneTools直接入口使用同一规则。

原生相机在请求数学范围外增加12px屏幕留白，避免边界上的合法点被5px导出裁切保护误拒；保持坐标、参数、等比例和请求范围，超出视口的真实错误点和非法bounding_box顺序仍拒绝。2026-10-20此留白只完成离线/浏览器回归，未把上一轮116秒失败的实模记录改成成功。


## 2026-10-20 长图上传修复

网页上传与当前完整评测脚本共用 `math_agent/image_input.py`，保留原像素与题目/答案角色，去掉原最长边10000及1600万像素限制。长题图自动按原像素分区送私有OCR，返回框映射回完整原图；答案不做OCR，模型传输继续使用总览与覆盖全部像素的分区，不缩整张长图代替原始文字。

运行容量为单图32MiB、6400万像素、总上传200MiB、最多6张；API与Waitress使用同一上传总量配置，上传解码串行，API内存上限1GiB。此为资源保护，不代表无限尺寸。现有60题的120张图片均在容量范围内；第29题1960×10172答案通过线上实际上传、像素一致性检查，测试任务在Worker暂停时取消，未产生模型费用。详见evaluation/upload-long-images-20261020/修复记录.md。

## 2026-10-20 小问子Agent实验（默认关闭）

`AGENT_PARALLEL_QUESTIONS=true`、`AGENT_QUESTION_CONCURRENCY=2`启用依赖调度；并发值只接受1或2，需要DeepSeek、compact工具模式且关闭reference/solve_draft。一个任务只有一份模型调用预算和整题截止时间，读题、所有小问与最终复核共用；每次请求的token额度保持原配置，不额外压缩。分支有独立工具历史和目录，使用完整题设及原图，按原Q/C编号合并。依赖不明时保守整题处理；两路模式先检查拓扑是否存在独立分支，纯依赖链直接整题求解，避免没有重叠却增加往返。显式单路实验仍按小问执行，供依赖交接测试和对照。多组不等于实际有并行机会。

仅解题分支并发，完整网页观察、独立整题复核与纠错验收仍保留。分支完成不代表数学通过；失败不自动重放，截止后返回的请求可能计费，其结果不得发布。`question-plan.json`、`question-agents/`、`audit.json`和`shared-budget.json`记录计划、各分支、实际调用与共享预算；截止时预算快照可能早于在途请求的最终usage，费用核对还须读取最终audit。

评测入口为`scripts/evaluate_full_once.py --question-agents off|serial|parallel`，分别表示原整题流程、按小问单路与最多两路。两题四次付费对照保存在`evaluation/two-question-agents-20261020/`；均未通过完整验收，不能宣称提速成功。该实验未部署到生产。第22题引文校验边界误报已在本地通用修复，原失败题设离线重验通过；这不等于修复后真实模型完整验收通过。

后续路由修复：连续、明确分隔且逐项含数学关系的①②③本问选项不再被误认为跨问引用；重复标签、未声明编号、文字指代及前问引用仍保守整题处理。该规则只决定能否调度，不证明数学独立，完整题设、依据校验与最终复核保持。实际执行策略、结构机会记录在`question-plan.json`的`execution`中。

后续一次第22题实测见`evaluation/two-question-agents-v2-20261020/`：181.202秒、4次调用、已返回用量估算0.154802元，仍失败且未复核；原题本问的“①求m”触发了保守整题路由，没有实际两路重叠。其后本地支持明确的本问编号任务标题；SVG标签按纯文字显示数学比较符号（内部SVG、parse=false、JSON嵌入转义均保留，并通过真实浏览器注入回归），不再误拒`x>0`。原输出离线继续检查仍有三问bounding_box顺序错误：未自动交换，已在compact提示与Schema说明数学视野顺序，并给出具体条件编号/画板错误供Agent纠正。后续修复没有追加付费请求或部署生产，不能声称真实题已通过。

## 2026-10-21 具名视野、集中校验与局部纠错

模型优先提交`board.view={x_min,x_max,y_min,y_max}`，服务端按字段转换成JSXGraph范围。四个值必须有限且有序，view与旧bounding_box同时填写会拒绝；不会猜测或交换非法范围。合法旧范围继续可读，JSXGraph上游与几何坐标未改。

compact解题由`submission.py`集中返回可确认的各问Schema、条件/步骤引用与本地构图问题。上游字段不合法时未执行的检查不会冒充通过；各画板会在纠正后重新完整校验。仅构图错误时走DiagramPatch，锁定出错tab且证明保持原样；混合错误使用受限updates，只允许错误清单对应Q与proof/board/controls字段。无关内容由服务端保留，越界提交拒绝。未知外层编号无法安全绑定时才保留原有完整格式纠正路径。输出纠错最多一次，共用原调用预算和截止时间；正常提交不增加模型阶段。数学和来源异议仍按原LangGraph路径修订并重新复核。

526项回归通过（含真实浏览器）。两次已授权实测分别为旧结果诊断84.386秒与全新图片任务189.793秒，两者自动渲染及完整模型复核均pass；费用按已返回用量估算合计0.573541元。全新任务关闭应用/OCR结果缓存、并发关闭，模型使用具名view，未触发格式纠正或返修。DeepSeek自身前缀缓存仍有命中，按实际用量计费。

人工检查仍发现：Q3证明用到的A/B辅助点未显示（此前“二模转写一模”判断经核查已撤回，实际原图与浏览器DOM均为二模），诊断复核记录另有一处附加数值比较错误。这轮证明自动完整流程在一题上能完成且进入3—4分钟范围，不能称人工全面质量验收通过或稳定成功率达标。原模型输出、pass与人工异议均保留；未修改已审页、未增加付费重跑、未替换生产。详见`evaluation/submission-recovery-20261021/验收记录.txt`。
