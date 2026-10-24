# 8666 Linux 独立部署

目标目录 `/opt/math-agent-8666`，用户 `math8666`，持久数据 `/var/lib/math-agent-8666`。

- 公网工作台/API：8666；鉴权仍使用服务访问令牌。
- PaddleOCR：127.0.0.1:18666，仅内网调用，使用相同服务令牌；常驻模型避免每题重新加载。
- Redis：127.0.0.1:16366，独立缓存，不接触原有项目。
- 四个 systemd 服务：`math8666-api`、`math8666-worker`、`math8666-ocr`、`math8666-redis`。
- API 与 OCR 使用分离的 Python 3.12 环境，避免 PaddleOCR 与 Agent 依赖冲突。

`bootstrap.sh` 是本服务器安装记录：需要 root、`/tmp/math-agent-uv`，并使用该服务器已有的本地下载代理 `127.0.0.1:7890`。换服务器时先调整下载网络配置。它不是通用的一键安装器。默认镜像安装 CPU Paddle，不需要 CUDA。

## OCR 选型

PaddleOCR 3.4.0 / PaddlePaddle 3.2.2 / PaddleX 3.4.3；PP-StructureV3 版面解析 + PP-OCRv5 mobile_det/server_rec + PP-FormulaNet_plus-S。不启动表格、印章、图表转表格等无关模块。公式 S 版适合先测 CPU 成本，但中文混合公式和复杂公式需实测，不能承诺准确率。

OCR仅处理题图；答案原图完整保留，供解题与复核直接查看，不再串行等待答案长图OCR。读题上下文和局部裁图工具均隔离答案图。OCR结果是供模型复核的证据，保留原图和问题/答案角色。几何图的点名、垂直/平行标记不能仅凭 OCR 或外观推断。当前版本没有裁图纯文本优化，因此不保证节省视觉 token 或端到端时间。读题关闭深度思考（8000 输出额度）；解题与复核使用低思考强度（部署配置32000）。这些额度是每次请求上限，并非实际输出量或总费用预算。

OCR缓存按白底RGBA转换后的RGB像素、尺寸和模型配置版本计算；变更模型/参数需要同步升级 service.py 的 PROFILE 和 AGENT_OCR_PROFILE，防止旧识别/模型结果复用。缓存不包含题/答案角色；角色由每次任务传入，不能从缓存继承。OCR辅助读题有未决问题时，会在总模型调用预算内最多重读一次原题，去掉OCR和答案干扰；仍不确定则needs_input。OCR不可用会停止图片任务，不会静默改走其他付费路径。纯文字题跳过OCR。

## 浏览器下载记录

默认 Playwright 下载在服务器上很慢；本次从其官方 Chrome for Testing 地址下载同版本 Chromium 156.0.8078.4，按 HTTP Range 分段续传并通过 ZIP CRC 校验。部署使用 `MATH_AGENT_CHROMIUM_EXECUTABLE=/opt/math-agent-8666/browser-manual/chrome-linux64/chrome`。下载脚本保留在 `download_browser.py`，目标为本次固定版本；不要把它当作自动更新器。完整包 SHA256 见验收目录。生产升级时应同步 Playwright 和浏览器版本并重新运行 doctor。

## 管理

```bash
systemctl status math8666-api math8666-worker math8666-ocr math8666-redis
journalctl -u math8666-ocr -n 50 --no-pager
systemctl restart math8666-api math8666-worker
```

`.env` 含密钥，权限 root:math8666 0640；不打进发布包。服务令牌必须与 DeepSeek Key 分开。公网当前使用 HTTP，正式教师使用建议配置域名和 HTTPS；远程维护和测试可通过 SSH 隧道。

OCR证据位于任务目录 `ocr.json`，终态任务可经鉴权接口 `/api/jobs/{id}/artifacts/ocr.json` 获取，也可在工作台展开“查看文字与公式识别结果”。失败任务不开放半成品讲解网页。

安装时使用独立 APT 源文件，不替换系统 sources.list。只修改新服务对应文件，不重启或替换旧应用。模型缓存约数百MB至数GB，具体看实际下载；缓存与任务文件需定期备份和清理。

## 运行时限与耗时优化

实验开关 `AGENT_REFERENCE_MODE=true` 将数学和构图分阶段处理：读题、参考解法整理、构图、修图、图文核验关闭深度思考；独立数学核验仍遵从 `DEEPSEEK_THINKING`。每次输出额度不变。需要答案图片，当前仅验收旋转/平移题；不支持时不会自动回退另一条付费流程。修改 `.env` 后待任务空闲再重启 API/Worker，不能中断运行任务后自动重试。

默认AGENT_JOB_TIMEOUT=240，从Worker启动任务进程计时，不含上传及排队；监督轮询与清理有少量开销。超时停止且不发布未核验结果，并非保证4分钟内必定成功。DEEPSEEK_DIAGRAM_THINKING=false只关闭构图修复的长思考，解题和复核仍由DEEPSEEK_THINKING控制，输出额度不缩减。当前默认仅做题图OCR，首次处理仍可能耗时数十秒，缓存耗时需单独报告。实测记录见evaluation/latency-agent。


## 长图（2026-10-20）

已统一网页和完整评测脚本的图片保存逻辑，现有题库长答案无需手工裁剪。上传单图32MiB、6400万像素，总上传200MiB；Waitress与Flask一致。API服务MemoryMax改为1G且解码串行。旧OCR服务的单次尺寸限制保留在内部，客户端对超限题图自动按2048×3072原像素分区、逐区识别并将框映射回原图；所有分区共享总OCR时限，失败不提交部分证据。答案仍直接给模型，角色不变。模型按原像素分区传输，未修改JSXGraph或数学判断。
