FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
WORKDIR /app
COPY pyproject.toml constraints.txt ./
COPY math_agent ./math_agent
RUN pip install --no-cache-dir -c constraints.txt -e . \
    && python -m playwright install --with-deps chromium \
    && apt-get update && apt-get install -y --no-install-recommends fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10001 --create-home agent \
    && mkdir -p /data && chown agent:agent /data \
    && chmod -R a+rX /ms-playwright
ENV AGENT_DATA_DIR=/data
USER agent
EXPOSE 8000
CMD ["python", "-m", "math_agent.cli", "serve", "--host", "0.0.0.0"]
