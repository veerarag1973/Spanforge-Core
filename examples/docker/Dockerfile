# syntax=docker/dockerfile:1
# ── spanforge Docker image ───────────────────────────────────────────────────
# Multi-stage build: build wheel, then copy into a slim runtime image.
#
# Usage:
#   docker build -t spanforge-app .
#   docker run --rm -e SPANFORGE_SERVICE_NAME=my-agent spanforge-app
#
# To export events to a host directory:
#   docker run --rm \
#     -v "$(pwd)/events:/data" \
#     -e SPANFORGE_EXPORTER=jsonl \
#     -e SPANFORGE_ENDPOINT=/data/events.jsonl \
#     spanforge-app

# ── Stage 1: builder ─────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build
COPY pyproject.toml README.md ./
COPY src/ ./src/

RUN pip install --upgrade pip build \
 && python -m build --wheel --outdir /dist

# ── Stage 2: runtime ─────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

# Create a non-root user for the application
RUN useradd --uid 1001 --gid 0 --no-create-home --shell /sbin/nologin appuser

WORKDIR /app

# Copy the built wheel and install it
COPY --from=builder /dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl \
 && rm /tmp/*.whl

# Copy application code (replace with your own app entry point)
COPY examples/ ./examples/

# Default environment — override at runtime
ENV SPANFORGE_SERVICE_NAME=spanforge-app \
    SPANFORGE_ENV=production \
    SPANFORGE_EXPORTER=console \
    SPANFORGE_ON_EXPORT_ERROR=warn

USER 1001

# Default command: run the health-check CLI
CMD ["spanforge", "check"]
