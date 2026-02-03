"""
Bedrock Model Detector - 通知エージェント
Strands Agentsを使用してメール本文を生成し、SNSに送信する
"""

import os
import logging

import boto3
import requests
from strands import Agent, tool
from bedrock_agentcore.runtime import BedrockAgentCoreApp

# ロギング設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 環境変数
SNS_TOPIC_ARN = os.environ.get('SNS_TOPIC_ARN', '')
TAVILY_API_KEY = os.environ.get('TAVILY_API_KEY', '')

# SNS_TOPIC_ARNからリージョンを抽出（例: arn:aws:sns:us-east-1:123456789:topic-name）
def get_region_from_arn(arn: str) -> str:
    """ARNからリージョンを抽出"""
    if arn:
        parts = arn.split(':')
        if len(parts) >= 4:
            return parts[3]
    return 'us-east-1'  # デフォルト

# SNSクライアント（リージョンを明示的に指定）
sns_client = boto3.client('sns', region_name=get_region_from_arn(SNS_TOPIC_ARN))

# AgentCoreアプリ
app = BedrockAgentCoreApp()


@tool
def search_web(query: str) -> str:
    """ウェブ検索を実行して、AIモデルに関する情報を取得します。

    Args:
        query: 検索クエリ（例: "Claude Sonnet 4.5 特徴"）

    Returns:
        検索結果の要約
    """
    if not TAVILY_API_KEY:
        return "エラー: TAVILY_API_KEY が設定されていません"

    try:
        response = requests.post(
            "https://api.tavily.com/search",
            headers={
                "Authorization": f"Bearer {TAVILY_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "query": query,
                "search_depth": "basic",
                "max_results": 3,
                "include_answer": True
            },
            timeout=30
        )
        response.raise_for_status()
        data = response.json()

        # LLM生成の回答があればそれを返す
        if data.get("answer"):
            return data["answer"]

        # なければ検索結果を整形して返す
        results = data.get("results", [])
        if not results:
            return "検索結果が見つかりませんでした"

        summary = []
        for r in results[:3]:
            summary.append(f"- {r.get('title', 'No title')}: {r.get('content', '')[:200]}...")

        return "\n".join(summary)

    except Exception as e:
        error_msg = f"ウェブ検索に失敗しました: {str(e)}"
        logger.error(error_msg)
        return error_msg


@tool
def send_notification(subject: str, body: str) -> str:
    """SNSトピックに通知メールを送信します。

    Args:
        subject: メールの件名（100文字以内、簡潔に）
        body: メールの本文（新モデルの詳細情報を含む）

    Returns:
        送信結果のメッセージ
    """
    if not SNS_TOPIC_ARN:
        return "エラー: SNS_TOPIC_ARN が設定されていません"

    try:
        # SNSの件名は100文字制限
        truncated_subject = subject[:100] if len(subject) > 100 else subject

        response = sns_client.publish(
            TopicArn=SNS_TOPIC_ARN,
            Subject=truncated_subject,
            Message=body
        )

        message_id = response.get('MessageId', 'unknown')
        logger.info(f"Notification sent successfully. MessageId: {message_id}")
        return f"通知を送信しました (MessageId: {message_id})"

    except Exception as e:
        error_msg = f"通知の送信に失敗しました: {str(e)}"
        logger.error(error_msg)
        return error_msg


def create_agent() -> Agent:
    """通知エージェントを作成"""

    system_prompt = """あなたはAmazon Bedrockの新モデル通知アシスタントです。
新しく追加されたモデルの情報を受け取り、分かりやすい日本語で通知メールを作成してください。

## 処理フロー

1. **ウェブ検索**: 各モデルについて search_web ツールで特徴を調べる
2. **メール作成**: 調べた情報をもとに通知メールを作成
3. **送信**: send_notification ツールで1通のメールを送信

## 通知メッセージの要件

### 件名
- 簡潔に（例: 「Bedrockに新しいモデルが追加されました」）
- 複数モデルがある場合は件数を含める（例: 「Bedrockに新しいモデルが追加されました（3件）」）

### 本文の構成
1. 冒頭の挨拶（1行）
2. リージョンごとのモデル一覧
   - リージョン名（日本語名も併記）
   - 各モデルのモデルID
   - **モデルの特徴**（ウェブ検索で調べた情報を2〜3行で簡潔に）

### フォーマット例
```
Amazon Bedrockに新しいモデルが出現しました🚀

■ AWS東京リージョン（ap-northeast-1）
  • anthropic.claude-sonnet-5-20260101-v1:0
    → 最新のClaude Sonnet 5は、コーディング能力が大幅に向上し、
      マルチモーダル対応も強化されています。
```

## 重要
- まず search_web でモデルの特徴を調べてから、通知を作成してください
- **通知は必ず1通にまとめてください**（リージョンごとに分けて複数回送らないこと）
- すべてのリージョンの新モデルを1つのメール本文にまとめて、send_notification を1回だけ呼び出してください
- ツールを呼び出さずに終了しないでください"""

    return Agent(
        model="us.anthropic.claude-sonnet-4-5-20250929-v1:0",
        system_prompt=system_prompt,
        tools=[search_web, send_notification],
    )


@app.entrypoint
async def invoke(payload=None):
    """AgentCoreエントリーポイント"""
    try:
        prompt = payload.get('prompt', '') if payload else ''

        if not prompt:
            return {
                "status": "error",
                "error": "prompt is required"
            }

        logger.info(f"Received prompt: {prompt[:200]}...")

        agent = create_agent()
        response = agent(prompt)

        # レスポンスからテキストを抽出
        result_text = ""
        if hasattr(response, 'message') and response.message:
            content = response.message.get('content', [])
            for block in content:
                if isinstance(block, dict) and 'text' in block:
                    result_text += block['text']

        logger.info(f"Agent response: {result_text[:200]}...")

        return {
            "status": "success",
            "response": result_text
        }

    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error in invoke: {error_msg}")
        return {
            "status": "error",
            "error": error_msg
        }


if __name__ == "__main__":
    app.run()
