"""Generate only the local API token. Never asks for/prints a model key."""
from pathlib import Path
import secrets
import os

os.umask(0o077)
root = Path(__file__).resolve().parents[1]
target = root / ".env"
if target.exists():
    raise SystemExit(".env 已存在，未覆盖。请编辑原文件。")
text = (root / ".env.example").read_text().replace("AGENT_ACCESS_TOKEN=\n", "AGENT_ACCESS_TOKEN=" + secrets.token_urlsafe(36) + "\n")
with target.open("x") as file: file.write(text)
target.chmod(0o600)
print("已创建 .env 并生成服务访问令牌。收到 Key 后填写 DEEPSEEK_API_KEY。")
