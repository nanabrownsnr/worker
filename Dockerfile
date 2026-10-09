FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates openssh-client && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy

RUN pip install --no-cache-dir uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md .env.example ./
RUN uv sync --locked --no-dev --no-install-project
COPY autodev ./autodev

ENV AUTODEV_BIND_HOST=0.0.0.0 \
    AUTODEV_PORT=8000 \
    AUTODEV_DATA_DIR=/var/lib/worker/data
VOLUME ["/var/lib/worker/data"]
EXPOSE 8000
CMD ["uv", "run", "--no-dev", "python", "-m", "autodev.main"]
