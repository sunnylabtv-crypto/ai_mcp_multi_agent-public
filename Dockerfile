FROM python:3.11-slim

WORKDIR /app

# 시스템 패키지
RUN apt-get update && apt-get install -y \
    gcc \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Python 패키지 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 소스 코드 복사
COPY . .

# 데이터 디렉토리 (Multi-Agent 전용)
RUN mkdir -p /app/data/multi/chromadb /app/data/multi/db /app/logs

# 환경변수
ENV MCP_MODE=sse
ENV HOST=0.0.0.0
ENV PORT=9000
ENV MCP_PORT=9000
ENV LOG_API_PORT=9001
ENV CHROMA_PERSIST_DIR=/app/data/multi/chromadb

# 포트 노출 (Multi-Agent: 9000 MCP, 9001 Log API)
EXPOSE 9000 9001

CMD ["python", "mcp_server/server.py"]
