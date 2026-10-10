# Worker

Worker is a persistent, single-worker coding service. It accepts an unrestricted prompt and an approved existing GitHub repository, gives the task to a headless Hermes process, independently runs pytest, routes up to five failed validations back to Hermes, then publishes a dedicated branch and notifies Telegram.

The five-return limit counts failed independent validations. The fifth failed validation is terminal; it does not start a sixth development attempt. No Render deployment, coverage enforcement, frontier escalation, or parallel jobs are implemented.

If a job includes `deployment_env`, Worker stores the supplied `.env` content in a protected file outside the checkout and uses it only for local Docker/Compose validation. It is never sent to Hermes, persisted in graph state, returned by the API, logged, or committed. Docker repositories must build, start, complete their configured smoke run, and produce no configured fatal log patterns before publication. Deployment repair attempts are separate from the five pytest returns.

The independent tester selects a runner deterministically: `TEST_COMMAND` overrides detection; otherwise it uses `uv run pytest -q` for Python projects with pytest files, `.venv/bin/python -m pytest` when uv is unavailable, `npm test` when `package.json` defines a test script, `go test ./...` for Go test files, or `cargo test` for Rust test sources. Unsupported projects or projects without detectable tests fail validation explicitly.

## Install on Ubuntu

Install Python 3.11+, Git, and `uv`, configure the already-installed Hermes/Ollama runtime, then:

```bash
uv sync --locked
cp .env.example .env
# edit .env; use a real API token and approved canonical GitHub URL
uv run pytest
uv run ruff check .
uv run python -m autodev.main
```

The default bind is `127.0.0.1:8000`. FastMCP is mounted on the same ASGI application. Use `POST /jobs` with `{"prompt":"...", "repo_url":"https://github.com/owner/repo.git"}` and poll `GET /jobs/{job_id}`. The MCP endpoint is exposed by FastMCP at its default `/mcp` route. Keep the service bound to localhost or protect it with an upstream network control if exposing it remotely; V1 does not require a separate AutoDev API key.

Set `AUTODEV_DATA_DIR` outside a Git checkout. SQLite jobs and logs/state survive restarts. Jobs are durably inserted before the HTTP response and execution is serialized; queued jobs wait for the active job. A production restart should reconcile nonterminal jobs before starting new work; the current V1 conservatively keeps the durable record and requires an operator to resubmit a nonterminal job after an interrupted process.

Hermes receives no Git or Telegram credentials. Its command is invoked with argument arrays, `stdin=DEVNULL`, a bounded timeout, explicit checkout cwd, and no shell interpolation. Hermes is a high-trust coding process and V1's workspace isolation is not a complete OS sandbox.

For systemd, create `/etc/systemd/system/worker.service`:

```ini
[Unit]
After=network-online.target
[Service]
WorkingDirectory=/opt/worker
ExecStart=/usr/local/bin/uv run python -m autodev.main
Restart=always
EnvironmentFile=/opt/worker/.env
[Install]
WantedBy=multi-user.target
```

Then run `sudo systemctl daemon-reload && sudo systemctl enable --now worker`.

## Verification

The test suite uses fake Hermes, pytest, Git, and Telegram integrations, so it does not require GitHub, Telegram, or model credentials. Real Hermes CLI flags must be checked against the installed Hermes version before enabling production execution; an optional real integration is intentionally not enabled by default.
The Docker Compose setup keeps SQLite, LangGraph checkpoints, logs, and workspaces in the host-backed ./data directory and restarts independently of terminal sessions.
Run: docker compose up -d --build, docker compose logs -f worker, docker compose stop, and docker compose start.
It mounts the installed Hermes executable/configuration and routes the container to the host model endpoint through host.docker.internal:8000.

For GitHub publication, set `GITHUB_TOKEN` in `.env` to a fine-grained token scoped only to the target repository with Contents read/write permission. `GITHUB_USERNAME` normally remains `x-access-token`. The token is supplied only to Git clone/push subprocesses through Git askpass and is removed from Hermes's environment; it is never included in repository URLs, logs, checkpoints, or API responses. Do not mount SSH keys or a broad `.gitconfig` into this container because Hermes runs in the same container.

Automated commits use `GIT_AUTHOR_NAME` and `GIT_AUTHOR_EMAIL` (defaulting to `Worker` and `worker@users.noreply.github.com`). These identify the commit and are separate from GitHub token authentication.

Runtime state and backups

The `./data` directory is intentionally not committed. It contains the SQLite job index, LangGraph checkpoints, redacted logs, and cloned job workspaces. Back it up while the service is stopped:

```bash
docker compose stop
tar -czf worker-data-$(date +%Y%m%d-%H%M%S).tgz data
docker compose start
```

Do not run `docker compose down -v` as a routine cleanup command. The current Compose configuration uses the host-backed directory, but older deployments may still have state in the `worker_worker_data` Docker volume. Git credentials are deliberately not mounted into the Worker container because Hermes runs there; configure a narrowly scoped noninteractive Git credential mechanism only after reviewing that security tradeoff.
