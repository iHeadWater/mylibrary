FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir mcp httpx pyzotero

# Copy the Zotero MCP server from the hydrolitagent package
COPY hydrolitagent/zotero/server.py /app/server.py
COPY hydrolitagent/zotero/__init__.py /app/hydrolitagent/zotero/__init__.py

EXPOSE 8002

ENV PYTHONUNBUFFERED=1

CMD ["python", "/app/server.py"]
