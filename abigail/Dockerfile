FROM python:3.11-slim

WORKDIR /app

COPY abigail/abigail_hardened_enhanced.py /app/abigail_hardened_enhanced.py
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
