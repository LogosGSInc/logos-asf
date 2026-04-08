FROM python:3.11-slim

WORKDIR /app

COPY abigail_hardened_enhanced.py /app/abigail_hardened_enhanced.py
COPY entrypoint.sh /app/entrypoint.sh

RUN python -m pip install --no-cache-dir \
    groq \
    anthropic \
    httpx \
    flask \
    prompt_toolkit \
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
