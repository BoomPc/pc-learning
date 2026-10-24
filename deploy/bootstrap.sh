#!/bin/bash
set -euo pipefail
cd /opt/math-agent-8666
export UV_PYTHON_INSTALL_DIR=/opt/math-agent-runtime
export UV_DEFAULT_INDEX=https://mirrors.aliyun.com/pypi/simple/
export UV_HTTP_TIMEOUT=180
UV=/tmp/math-agent-uv
HTTPS_PROXY=http://127.0.0.1:7890 "$UV" python install 3.12
"$UV" venv --python 3.12 .venv
"$UV" pip install --python .venv/bin/python -c constraints.txt -e .
"$UV" venv --python 3.12 .ocr-venv
"$UV" pip install --python .ocr-venv/bin/python -r deploy/ocr/requirements.txt
cat > /opt/math-agent-8666/ubuntu.list <<'EOF'
deb https://mirrors.aliyun.com/ubuntu/ jammy main universe restricted multiverse
deb https://mirrors.aliyun.com/ubuntu/ jammy-updates main universe restricted multiverse
deb https://mirrors.aliyun.com/ubuntu/ jammy-security main universe restricted multiverse
EOF
APT_ARGS=(-o DPkg::Lock::Timeout=600 -o Acquire::ForceIPv4=true -o Dir::Etc::sourcelist=/opt/math-agent-8666/ubuntu.list -o Dir::Etc::sourceparts=- -o Acquire::Retries=1 -o Acquire::https::Timeout=30)
DEBIAN_FRONTEND=noninteractive apt-get "${APT_ARGS[@]}" update -qq
DEBIAN_FRONTEND=noninteractive apt-get "${APT_ARGS[@]}" install -y fonts-noto-cjk libgomp1 libgl1 libglib2.0-0 redis-server
PLAYWRIGHT_BROWSERS_PATH=/opt/math-agent-8666/browsers HTTPS_PROXY=http://127.0.0.1:7890 .venv/bin/python -m playwright install chromium
id math8666 >/dev/null 2>&1 || useradd --system --home-dir /var/lib/math-agent-8666 --shell /usr/sbin/nologin math8666
install -d -o math8666 -g math8666 -m 700 /var/lib/math-agent-8666 /var/lib/math-agent-8666/jobs /var/lib/math-agent-8666/models /var/lib/math-agent-8666/ocr-cache /var/lib/math-agent-8666/redis
chown root:math8666 .env
chmod 640 .env
cp deploy/systemd/*.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now math8666-redis math8666-ocr math8666-api math8666-worker
