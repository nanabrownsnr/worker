FROM node:22-bookworm-slim AS ui-build
WORKDIR /ui
COPY autodev/ui/tasks/package.json autodev/ui/tasks/package-lock.json ./
RUN npm ci
COPY autodev/ui/tasks/index.html autodev/ui/tasks/vite.config.js ./
COPY autodev/ui/tasks/src ./src
RUN npm run build

FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates openssh-client docker-cli nodejs npm && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy

RUN pip install --no-cache-dir uv
RUN pip install --no-cache-dir aider-chat pytest
RUN npm install -g opencode-ai
WORKDIR /app
COPY pyproject.toml uv.lock README.md .env.example ./
RUN uv sync --locked --no-dev --no-install-project
COPY autodev ./autodev
COPY --from=ui-build /ui/dist/index.html ./autodev/ui/tasks/dist/index.html
RUN mkdir -p /var/lib/worker/data /home/nbrown /tmp/uv-cache && chown -R 1001:1003 /var/lib/worker /home/nbrown /tmp/uv-cache /app
RUN chmod 0755 /app/autodev/integrations/git_askpass.py

ENV AUTODEV_BIND_HOST=0.0.0.0 \
    AUTODEV_PORT=8000 \
    AUTODEV_DATA_DIR=/var/lib/worker/data
VOLUME ["/var/lib/worker/data"]
EXPOSE 8000
CMD ["uv", "run", "--no-dev", "python", "-m", "autodev.main"]
