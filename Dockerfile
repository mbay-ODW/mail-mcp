FROM python:3.12-slim
# Docker-Secrets: NAME_FILE=/run/secrets/... wird beim Start zu NAME geladen
COPY --chmod=0755 env-secrets.sh /usr/local/bin/env-secrets
WORKDIR /app

COPY pyproject.toml .
COPY src/ src/

RUN pip install --no-cache-dir -e .

ENV MCP_TRANSPORT=sse
ENV PORT=8000
ENV LOG_LEVEL=INFO

EXPOSE 8000
ENTRYPOINT ["/usr/local/bin/env-secrets"]
CMD ["mail-mcp"]
