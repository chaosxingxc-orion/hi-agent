# Multi-stage Dockerfile for hi-agent.
#
# Reference deployment template for the operator-shape gate (Rule 8).
#
# Build:
#   docker build -f deploy/docker/Dockerfile -t hi-agent:local .
# Run:
#   docker run --rm -p 8080:8080 \
#     -e HI_AGENT_POSTURE=dev \
#     -v hi-agent-data:/var/lib/hi-agent \
#     hi-agent:local

# ---- Stage 1: builder ------------------------------------------------------
FROM python:3.14-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# Install build deps for any wheels that need to compile (e.g. tiktoken).
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/*

# Copy build manifest first so Docker can cache the dependency layer.
COPY pyproject.toml ./
COPY README.md ./

# Stage the runtime sources so `pip install .` can resolve the package
# without pulling in tests / docs / scripts.
COPY hi_agent/ ./hi_agent/
COPY agent_server/ ./agent_server/
COPY agent_kernel/ ./agent_kernel/

# Install hi-agent + its runtime dependencies into a dedicated prefix that we
# can copy verbatim into the final image.
RUN pip install --prefix=/install --no-cache-dir .

# ---- Stage 2: runtime ------------------------------------------------------
FROM python:3.14-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HI_AGENT_HOME=/var/lib/hi-agent \
    HI_AGENT_POSTURE=dev

# Non-root user — matches the systemd unit so volume permissions line up.
RUN groupadd --system --gid 1001 hi-agent \
 && useradd  --system --uid 1001 --gid hi-agent --home-dir /home/hi-agent \
              --create-home --shell /usr/sbin/nologin hi-agent \
 && mkdir -p /var/lib/hi-agent /var/log/hi-agent \
 && chown -R hi-agent:hi-agent /var/lib/hi-agent /var/log/hi-agent

# Pull installed packages from the builder stage.
COPY --from=builder /install /usr/local

# Copy package source so Python can locate the modules at runtime.
WORKDIR /app
COPY --from=builder /build/hi_agent     /app/hi_agent
COPY --from=builder /build/agent_server /app/agent_server
COPY --from=builder /build/agent_kernel /app/agent_kernel

USER hi-agent
EXPOSE 8080

# /health returns 200 once the server is ready; the operator-shape gate
# polls this endpoint as part of step 1.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request,sys; \
    sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3).status==200 else 1)"

# Use the module entry point so signal handling (SIGTERM → drain) works.
CMD ["python", "-m", "hi_agent", "serve", "--port", "8080"]
