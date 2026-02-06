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
def search_web(query: str, recent_days: int = 0, search_x: bool = False) -> str:
    """ウェブ検索を実行して、AIモデルに関する最新情報を取得します。

    新モデルのリリース情報を調べる際は、以下のようなクエリが効果的です:
    - X速報: search_web("Anthropic Claude Opus 4.6", recent_days=3, search_x=True)
    - 公式リリース: search_web("Anthropic Claude Opus 4.6 release announcement", recent_days=3)
    - モデルの特徴: search_web("Anthropic Claude Opus capabilities benchmark")

    Args:
        query: 検索クエリ（英語推奨。ベンダー名+モデル名を必ず含めること）
        recent_days: 検索対象を直近N日以内に限定（0=制限なし、リリース情報には3を推奨）
        search_x: Trueの場合、X（旧Twitter）に限定して検索する（速報・反響の収集に有効）

    Returns:
        検索結果（タイトル・URL・内容を含む）
    """
    if not TAVILY_API_KEY:
        return "エラー: TAVILY_API_KEY が設定されていません"

    try:
        params = {
            "query": query,
            "search_depth": "advanced",
            "max_results": 3,
            "include_answer": not search_x,
        }
        if recent_days > 0:
            params["days"] = recent_days
        if search_x:
            params["include_domains"] = ["x.com", "twitter.com"]

        response = requests.post(
            "https://api.tavily.com/search",
            headers={
                "Authorization": f"Bearer {TAVILY_API_KEY}",
                "Content-Type": "application/json"
            },
            json=params,
            timeout=30
        )
        response.raise_for_status()
        data = response.json()

        # 回答 + ソース付き検索結果を両方返す
        parts = []

        if data.get("answer"):
            parts.append(f"【要約】{data['answer']}")

        results = data.get("results", [])
        if results:
            parts.append("【検索結果】")
            for r in results[:3]:
                title = r.get('title', 'No title')
                url = r.get('url', '')
                content = r.get('content', '')[:300]
                parts.append(f"- {title}\n  URL: {url}\n  {content}")

        return "\n\n".join(parts) if parts else "検索結果が見つかりませんでした"

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

## モデルIDからベンダー・シリーズを推定

モデルIDのプレフィックスからベンダー名とモデルシリーズを推定してください:

| プレフィックス | ベンダー | モデルシリーズ例 |
|--------------|---------|----------------|
| anthropic.claude-* | Anthropic | Claude (Opus/Sonnet/Haiku) |
| meta.llama-* | Meta | Llama |
| amazon.titan-* | Amazon | Titan |
| amazon.nova-* | Amazon | Nova |
| mistral.* | Mistral AI | Mistral/Mixtral |
| cohere.* | Cohere | Command |
| ai21.* | AI21 Labs | Jamba |
| stability.* | Stability AI | Stable Diffusion |
| deepseek.* | DeepSeek | DeepSeek |

## 検索戦略（3段階検索）

新しいモデルはリリース直後のため、検索を工夫しないと正確な情報が見つかりません。
以下の手順で検索してください。**検索クエリは必ず英語で**書いてください。

### ステップ1: X（旧Twitter）で速報を検索（直近3日以内）
```
search_web("{ベンダー名} {モデル名}", recent_days=3, search_x=True)
```
例: search_web("Anthropic Claude Opus 4.6", recent_days=3, search_x=True)

→ 公式アカウントのツイートや、ベンチマーク結果・業界の反響を収集する。

### ステップ2: 公式リリース情報を検索（直近3日以内）
```
search_web("{ベンダー名} {モデル名} release announcement blog", recent_days=3)
```
例: search_web("Anthropic Claude Opus 4.6 release announcement blog", recent_days=3)

→ ベンダーの公式ブログやプレスリリースを探す。

### ステップ3: モデルシリーズの特徴を検索（補足が必要な場合のみ）
```
search_web("{ベンダー名} {モデルシリーズ} capabilities features benchmark")
```
例: search_web("Anthropic Claude Opus capabilities features benchmark")

→ モデルシリーズの一般的な特徴を把握する。

### 注意
- 同じモデルシリーズが複数リージョンに出た場合、検索は1セットで十分です
- ステップ1〜2で十分な情報が得られた場合、ステップ3は省略してOKです

## メール作成

### 件名
- 簡潔に（例: 「Bedrockに新しいモデルが出現しました！」）
- 複数モデルがある場合は件数を含める（例: 「Bedrockに新しいモデルが出現しました！3件）」）

### 本文の構成
1. 冒頭の挨拶（1行）
2. リージョンごとのモデル一覧
   - リージョン名（日本語名も併記）
   - 各モデルのモデルID
   - **モデルの特徴**（ウェブ検索で調べた情報を2〜3行で簡潔に）
3. 情報ソースURL（検索結果で見つかった公式ブログ等があれば末尾に記載）

### フォーマット例
```
Amazon Bedrockに新しいモデルが出現しました🚀

■ AWS東京リージョン（ap-northeast-1）
  • anthropic.claude-opus-4-6-v1
    → Anthropic最新のClaude Opus 4.6は、エージェント型コーディングや複雑なマルチステップワークフローで業界トップの性能を発揮します。

📎 参考: https://www.anthropic.com/news/claude-opus-4-6
```

**注意**: → の後は改行せず、説明文は1行で続けてください（スマホ表示で読みやすくするため）。

## 重要
- まず search_web で検索してから、通知を作成してください
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
