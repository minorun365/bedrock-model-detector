# Bedrock Model Detector - 詳細仕様書

## 1. システム概要

Amazon Bedrockに新しいモデルが追加されたことを自動検知し、Eメールで通知するシステム。

### 1.1 技術スタック
- **IaC**: AWS CDK (TypeScript)
- **Lambda**: Python 3.13
- **AgentCore Runtime**: L2 Construct (`@aws-cdk/aws-bedrock-agentcore-alpha`)
- **データストア**: DynamoDB
- **通知**: Amazon SNS (Email)
- **スケジューラ**: EventBridge Scheduler

---

## 2. アーキテクチャ

```
┌─────────────────────────────────────────────────────────────────────┐
│                        EventBridge Scheduler                         │
│                         (5分おきに実行)                              │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         Lambda関数 (Python 3.13)                     │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │ 1. ListFoundationModels API (3リージョン並列)               │    │
│  │ 2. DynamoDB から前回のモデル一覧を取得                      │    │
│  │ 3. 差分を計算                                               │    │
│  │ 4. 差分あり → AgentCore Runtime を呼び出し                  │    │
│  │ 5. DynamoDB を更新                                          │    │
│  └─────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                            (差分ありの場合)
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    AgentCore Runtime (Strands Agent)                 │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │ 1. 新モデル情報を受け取る                                   │    │
│  │ 2. Strands Agent がメール本文を生成                         │    │
│  │ 3. send_notification ツールで SNS に送信                    │    │
│  └─────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                           Amazon SNS                                 │
│                    Email サブスクリプション                          │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. 監視対象リージョン

設定ファイルで変更可能とする（デフォルト値）:

| リージョン | 名前 | 説明 |
|-----------|------|------|
| us-east-1 | バージニア北部 | 最も早くモデルが追加される |
| us-west-2 | オレゴン | 2番目に追加されることが多い |
| ap-northeast-1 | 東京 | 日本リージョン |

---

## 4. コンポーネント詳細仕様

### 4.1 Lambda関数（モデル検出）

#### 基本情報
- **ランタイム**: Python 3.13
- **メモリ**: 256 MB
- **タイムアウト**: 60秒
- **トリガー**: EventBridge Scheduler (5分おき)

#### 環境変数
| 変数名 | 説明 | 例 |
|--------|------|-----|
| TARGET_REGIONS | カンマ区切りのリージョン一覧 | `us-east-1,us-west-2,ap-northeast-1` |
| DYNAMODB_TABLE_NAME | DynamoDBテーブル名 | `bedrock-model-detector` |
| AGENTCORE_RUNTIME_ARN | AgentCore RuntimeのARN | `arn:aws:bedrock-agentcore:...` |

#### 処理フロー
```python
def handler(event, context):
    # 1. 対象リージョンを取得
    regions = os.environ['TARGET_REGIONS'].split(',')

    # 2. 各リージョンのモデル一覧を並列取得
    current_models = {}
    for region in regions:
        client = boto3.client('bedrock', region_name=region)
        response = client.list_foundation_models()
        current_models[region] = {m['modelId'] for m in response['modelSummaries']}

    # 3. DynamoDBから前回のモデル一覧を取得
    previous_models = get_previous_models_from_dynamodb()

    # 4. 差分を計算
    new_models = calculate_diff(previous_models, current_models)

    # 5. 差分があればAgentCore Runtimeを呼び出し
    if new_models:
        invoke_agentcore_runtime(new_models)

    # 6. DynamoDBを更新
    update_dynamodb(current_models)
```

#### IAM権限
```yaml
- Effect: Allow
  Action:
    - bedrock:ListFoundationModels
  Resource: "*"

- Effect: Allow
  Action:
    - dynamodb:GetItem
    - dynamodb:PutItem
    - dynamodb:UpdateItem
  Resource: !GetAtt DynamoDBTable.Arn

- Effect: Allow
  Action:
    - bedrock-agentcore:InvokeAgentRuntime
  Resource:
    - !GetAtt AgentCoreRuntime.Arn
    - !Sub "${AgentCoreRuntime.Arn}/*"
```

---

### 4.2 DynamoDB テーブル

#### テーブル設計
- **テーブル名**: `bedrock-model-detector`
- **キャパシティモード**: オンデマンド

| 属性 | 型 | キー | 説明 |
|-----|-----|-----|------|
| pk | String | PK | 固定値: `MODEL_STATE` |
| region | String | SK | リージョン名 |
| model_ids | StringSet | - | モデルIDのセット |
| last_updated | String | - | ISO 8601形式 |

#### アイテム例
```json
{
  "pk": "MODEL_STATE",
  "region": "us-east-1",
  "model_ids": ["anthropic.claude-3-sonnet", "anthropic.claude-3-haiku", ...],
  "last_updated": "2026-02-03T10:00:00Z"
}
```

---

### 4.3 AgentCore Runtime（通知エージェント）

#### 基本情報
- **認証モード**: IAM（Lambdaから呼び出し）
- **使用モデル**: Claude Sonnet 4.5 (`us.anthropic.claude-sonnet-4-5-20250929-v1:0`)
- **フレームワーク**: Strands Agents

#### 環境変数
| 変数名 | 説明 |
|--------|------|
| SNS_TOPIC_ARN | 通知先SNSトピックのARN |

#### システムプロンプト
```
あなたはAmazon Bedrockの新モデル通知アシスタントです。
新しく追加されたモデルの情報を受け取り、分かりやすい日本語で通知メッセージを作成してください。

## 通知メッセージの要件
- 件名は簡潔に（例: 「Bedrockに新しいモデルが追加されました」）
- 本文には以下を含める:
  - どのリージョンに追加されたか（日本語名も併記）
  - モデル名（可能な限り分かりやすい名前で）
  - モデルID
  - 複数のモデル/リージョンがある場合はまとめて記載

## 出力
必ず send_notification ツールを使って通知を送信してください。
```

#### ツール定義
```python
@tool
def send_notification(subject: str, body: str) -> str:
    """SNSトピックに通知を送信します。

    Args:
        subject: メールの件名（100文字以内）
        body: メールの本文

    Returns:
        送信結果のメッセージ
    """
    # SNS_TOPIC_ARNからリージョンを抽出（AgentCore Runtime内ではAWS_REGIONが未設定のため）
    topic_arn = os.environ['SNS_TOPIC_ARN']
    region = topic_arn.split(':')[3] if topic_arn else 'us-east-1'

    sns = boto3.client('sns', region_name=region)
    sns.publish(
        TopicArn=topic_arn,
        Subject=subject[:100],  # SNSの件名上限
        Message=body
    )
    return "通知を送信しました"
```

**注意**: AgentCore Runtimeのコンテナ内では `AWS_REGION` 環境変数が設定されていないため、boto3クライアント作成時にリージョンを明示的に指定する必要がある。

#### 入力ペイロード
```json
{
  "prompt": "以下の新しいモデルについて通知してください:\n\n{new_models_json}"
}
```

#### IAM権限
```yaml
- Effect: Allow
  Action:
    - bedrock:InvokeModel
    - bedrock:InvokeModelWithResponseStream
  Resource:
    - arn:aws:bedrock:*::foundation-model/*
    - arn:aws:bedrock:*:*:inference-profile/*

- Effect: Allow
  Action:
    - sns:Publish
  Resource: !Ref SNSTopic
```

---

### 4.4 Amazon SNS

#### トピック設定
- **トピック名**: `bedrock-model-detector-notifications`
- **タイプ**: Standard

#### サブスクリプション
- **プロトコル**: Email
- **エンドポイント**: パラメータで指定（`NotificationEmail`）

---

### 4.5 EventBridge Scheduler

#### スケジュール設定
- **名前**: `bedrock-model-detector-schedule`
- **スケジュール式**: `rate(5 minutes)`
- **ターゲット**: Lambda関数
- **フレキシブルタイムウィンドウ**: OFF

---

## 5. CDK構成

### ディレクトリ構造
```
bedrock-model-detector/
├── cdk/
│   ├── bin/
│   │   └── app.ts
│   ├── lib/
│   │   └── bedrock-model-detector-stack.ts
│   ├── cdk.json
│   ├── package.json
│   └── tsconfig.json
├── lambda/
│   ├── detector/
│   │   ├── handler.py
│   │   └── requirements.txt
├── runtime/
│   ├── agent.py
│   ├── requirements.txt
│   └── Dockerfile
└── docs/
    ├── PLAN.md
    ├── SPEC.md
    ├── TODO.md
    └── KNOWLEDGE.md
```

### CDK Context（設定値）
| Context名 | 説明 | デフォルト値 |
|-----------|------|-------------|
| notificationEmail | 通知先メールアドレス | 必須 |
| targetRegions | 監視対象リージョン（カンマ区切り） | `us-east-1,us-west-2,ap-northeast-1` |

### デプロイコマンド
```bash
cd cdk
npm install

# 初回デプロイ
AWS_PROFILE=sandbox cdk deploy -c notificationEmail=your-email@example.com

# リージョンを変更する場合
AWS_PROFILE=sandbox cdk deploy -c notificationEmail=your-email@example.com -c targetRegions=us-east-1,us-west-2
```

**注意**: dotenvは使用しない（CDK出力との相性問題があるため）

---

## 6. 通知メッセージ例

### 単一リージョン・単一モデル
```
件名: Bedrockに新しいモデルが追加されました

本文:
東京リージョン（ap-northeast-1）に新しいモデルが追加されました！

■ Claude Sonnet 5
  モデルID: anthropic.claude-sonnet-5-20260101-v1:0

---
Bedrock Model Detector
```

### 複数リージョン・複数モデル
```
件名: Bedrockに新しいモデルが追加されました（3件）

本文:
複数のリージョンに新しいモデルが追加されました！

■ バージニア北部（us-east-1）
  • Claude Sonnet 5
    モデルID: anthropic.claude-sonnet-5-20260101-v1:0
  • Llama 4
    モデルID: meta.llama4-70b-instruct-v1:0

■ 東京（ap-northeast-1）
  • Claude Sonnet 5
    モデルID: anthropic.claude-sonnet-5-20260101-v1:0

---
Bedrock Model Detector
```

---

## 7. エラーハンドリング

### ListFoundationModels API失敗時
- リトライして成功するまで待つ（指数バックオフ）
- 最大リトライ回数を超えた場合はログに記録し、次回実行に持ち越し

### AgentCore Runtime失敗時
- ログに記録し、次回実行時に再試行
- DynamoDBは更新しない（差分が残る）

### SNS送信失敗時
- ログに記録
- DynamoDBは更新する（無限ループ防止）

---

## 8. 決定事項

| 項目 | 決定 |
|------|------|
| AgentCore使用モデル | Claude Sonnet 4.5 (`us.anthropic.claude-sonnet-4-5-20250929-v1:0`) |
| API失敗時の挙動 | リトライして成功するまで待つ |
| CDKデプロイ先リージョン | us-east-1（バージニア北部） |
| cdk bootstrap | 済み |
| SCPタグ | `Project: presales`（Organizations必須） |
| InvokeAgentRuntime レスポンス処理 | `.read()` で一括取得（ストリーミング不使用） |
