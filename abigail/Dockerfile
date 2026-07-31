FROM python:3.11-slim

ARG VCS_REF
LABEL org.opencontainers.image.revision=$VCS_REF

WORKDIR /app

COPY abigail/abigail_hardened_enhanced.py /app/abigail_hardened_enhanced.py
COPY abigail/tacit_prepass.py /app/tacit_prepass.py
COPY abigail/agent_loader.py /app/agent_loader.py
COPY agents /app/agents

# Governance stack — required for command bus (CB-01) and MM-01/02/03 orchestration
# (approval gate). Placed at /app so top-level imports resolve, matching local sys.path.
# privileged_credentials.py (C4) is imported at module load by both
# abigail_hardened_enhanced.py and command_bus.py — without it, python raises
# ImportError before Flask starts and the container restart-loops.
COPY abigail/privileged_credentials.py /app/privileged_credentials.py
COPY abigail/command_bus.py /app/command_bus.py
COPY abigail/agent_loader.py /app/agent_loader.py
COPY abigail/orchestration /app/orchestration
COPY abigail/model_router /app/model_router
COPY abigail/entrypoint.sh /app/entrypoint.sh
# Static UI (index.html, dashboard.html, intake.html)
COPY static /app/static

COPY abigail/requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt \
 && chmod +x /app/entrypoint.sh

# Audit log lives in a named volume so it survives container restarts
RUN mkdir -p /app/logs

EXPOSE 7070

# ABIGAIL_HEADLESS=1 suppresses browser open in container mode
ENV ABIGAIL_HEADLESS=1

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:7070/api/status', timeout=5)" || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python", "abigail_hardened_enhanced.py", "--web", "--port=7070"]
