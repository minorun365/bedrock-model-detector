FROM python:3.13-slim

WORKDIR /app

# 非rootユーザーを作成
RUN useradd -m -u 1000 bedrock_agentcore

# Python依存関係をインストール
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# アプリケーションコードをコピー
COPY . .

# 非rootユーザーに切り替え
USER bedrock_agentcore

# AgentCore SDKはポート8080を使用
EXPOSE 8080

# ヘルスチェック
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8080/ping || exit 1

# OTELの自動計装を有効にして起動
CMD ["opentelemetry-instrument", "python", "agent.py"]
