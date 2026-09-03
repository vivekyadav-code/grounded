# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS base

# No build step and no dependencies to install — the service is standard
# library only, which is most of why this image is small and boots fast.
WORKDIR /app

# Code and corpus are separate layers from the index below, so editing a
# document doesn't invalidate the code layer and vice versa.
COPY grounded/ ./grounded/
COPY corpus/ ./corpus/
COPY rag ./rag

# The index is BAKED AT BUILD TIME. The alternative — embedding the corpus on
# first boot — pays an API bill and a cold-start delay on every replica, every
# deploy, forever. Baking makes the image immutable and the container's first
# request as fast as its thousandth.
#
# The key is a BuildKit secret: mounted for this one layer, never written to
# the filesystem, never present in the final image or its history.
#   docker build --secret id=gemini_key,env=GEMINI_API_KEY -t grounded .
RUN --mount=type=secret,id=gemini_key \
    GEMINI_API_KEY="$(cat /run/secrets/gemini_key)" python rag ingest

# Runs unprivileged. The index is read-only at runtime; nothing needs to write.
RUN useradd --create-home --uid 10001 app && chown -R app:app /app
USER app

ENV PORT=8080 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8080

# Liveness only. Readiness is /readyz and is the orchestrator's business —
# a container that is up but not ready should be kept out of the load
# balancer, not killed and restarted.
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz',timeout=2).status==200 else 1)"

CMD ["python", "rag", "serve"]
