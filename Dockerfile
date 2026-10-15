# dokayuki: the one-off S2S history pull in a container (NAS, home server). Resumable; mount
# ./state and ./logs so request ids, decoded members and logs survive restarts.
#   docker build -t dokayuki .
#   docker run -d --name dokayuki-s2s --restart unless-stopped -e ECMWF_API_KEY=... \
#     -v "$PWD/state:/app/state" -v "$PWD/logs:/app/logs" dokayuki
#   docker logs -f dokayuki-s2s        # progress; "history pull complete" at the end
#   docker exec dokayuki-s2s .venv/bin/python scripts/pull_status.py   # one-screen status (add --json for an agent)
#   Optional -e GITHUB_TOKEN=... -e GITHUB_REPOSITORY=cauldnz/dokayuki: the decoded state is uploaded as a
#   release checkpoint after every loop, so progress is readable from GitHub without touching the box.
#   then on any machine with the state mounted: .venv/bin/python scripts/state_release.py upload
FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1 UV_LINK_MODE=copy
RUN pip install --no-cache-dir uv
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY config ./config
COPY scripts ./scripts
RUN uv venv .venv --python 3.13 && uv pip install --python .venv/bin/python -e ".[fetch]" && uv pip install --python .venv/bin/python eccodeslib
VOLUME ["/app/state", "/app/logs"]
ENTRYPOINT ["scripts/pull_history_s2s.sh"]
CMD ["ecmwf", "2016-10-01", "2023-04-30"]
