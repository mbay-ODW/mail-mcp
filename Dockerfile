FROM python:3.12-slim
WORKDIR /app

COPY pyproject.toml .
COPY src/ src/

RUN pip install --no-cache-dir -e .

ENV MCP_TRANSPORT=sse
ENV PORT=8000
ENV LOG_LEVEL=INFO

EXPOSE 8000
CMD ["mail-mcp"]
