# Bedrock Model Detector - 要件定義案

## 1. プロジェクト概要

Amazon Bedrockに新しいモデルが追加されたことを自動検知し、Eメールで通知するシステム。

### 1.1 背景
- 既存: Lambda + DynamoDB + AWS Chatbot（Slack通知）
- 新規: Strands Agents + Bedrock AgentCore を活用し、柔軟な通知メッセージを生成

### 1.2 目的
- 3リージョン（us-east-1, us-west-2, ap-northeast-1）のBedrockモデルを監視
- 新モデル追加時にSNS経由でメール通知
- AIエージェントによる自然な日本語メッセージ生成

---

## 2. 監視対象リージョン

| リージョン | 名前 |
|-----------|------|
| us-east-1 | バージニア北部 |
| us-west-2 | オレゴン |
| ap-northeast-1 | 東京 |

---

## 3. アーキテクチャ案

### 案A: Lambda + AgentCore Runtime（ハイブリッド）

```
EventBridge Scheduler (5分おき)
    ↓
Lambda関数
    ├── ListFoundationModels API (3リージョン)
    ├── DynamoDB (差分管理)
    └── 差分あり → AgentCore Runtime呼び出し
                        ↓
                  Strands Agent (メール本文生成)
                        ↓
                  SNS → Email
```

**メリット**:
- Lambdaの高速起動（コールドスタート短い）
- AgentCore Runtimeは通知時のみ起動（コスト効率◎）
- DynamoDBとの連携がシンプル

**デメリット**:
- Lambda + AgentCore の2つのコンポーネント管理

---

### 案B: AgentCore Runtime のみ（フルサーバーレス）

```
EventBridge Scheduler (5分おき)
    ↓
AgentCore Runtime (Universal Target)
    ├── Strands Agent内で
    │   ├── ListFoundationModels API (3リージョン)
    │   ├── /tmp ファイルで差分管理
    │   │   （または DynamoDB ツール）
    │   └── 差分あり → メール本文生成 → SNS
```

**メリット**:
- Lambdaレス（コンポーネント少ない）
- EventBridge → AgentCore 直接呼び出し可能

**デメリット**:
- AgentCoreの起動が毎回必要（Lambdaより遅い）
- /tmpは15分のコンテナライフサイクル内のみ有効
- 差分管理にDynamoDBが必要になる可能性

---

### 案C: Lambda（差分検出）+ Lambda（通知）

```
EventBridge Scheduler (5分おき)
    ↓
Lambda関数 (検出)
    ├── ListFoundationModels API (3リージョン)
    ├── DynamoDB (差分管理)
    └── 差分あり → SNS (通知トピック)
                        ↓
                  Lambda関数 (通知) ← SNSトリガー
                        ├── AgentCore Runtime呼び出し
                        │   └── メール本文生成
                        └── SNS → Email
```

**メリット**:
- 責務の分離（検出 vs 通知）
- 検出Lambdaは高速（エージェント不要）

**デメリット**:
- コンポーネントが多い

---

## 4. 推奨アーキテクチャ

### ⭐ 案A: Lambda + AgentCore Runtime（ハイブリッド）を推奨

**理由**:
1. **5分おき実行**: Lambdaの高速起動が有利
2. **コスト効率**: AgentCore Runtimeは通知時のみ起動
3. **シンプル**: DynamoDBとの連携が自然
4. **信頼性**: Lambdaの実績ある定期実行パターン

---

## 5. コンポーネント詳細

### 5.1 Lambda関数（モデル検出）

**役割**:
- 3リージョンのListFoundationModels API呼び出し
- DynamoDBと比較して差分検出
- 差分があればAgentCore Runtimeを呼び出し

**技術スタック**:
- Python 3.12
- boto3

**DynamoDBテーブル設計**:
```
テーブル名: bedrock-model-detector
パーティションキー: region (String)
属性:
  - model_ids: Set<String> - モデルIDのセット
  - last_updated: String - 最終更新日時
```

### 5.2 AgentCore Runtime（通知エージェント）

**役割**:
- 新モデル情報を受け取り、自然な日本語でメール本文を生成
- SNSトピックにパブリッシュ

**システムプロンプト（案）**:
```
あなたはAmazon Bedrockの新モデル通知アシスタントです。
新しく追加されたモデルの情報を受け取り、分かりやすく通知メッセージを作成してください。

通知には以下を含めてください：
- どのリージョンに追加されたか
- モデル名（分かりやすい名前）
- モデルID
- 簡単な説明（可能であれば）
```

**ツール**:
```python
@tool
def send_notification(subject: str, body: str) -> str:
    """SNSトピックに通知を送信します。"""
    sns = boto3.client('sns')
    sns.publish(
        TopicArn=os.environ['SNS_TOPIC_ARN'],
        Subject=subject,
        Message=body
    )
    return "通知を送信しました"
```

### 5.3 DynamoDB テーブル

**テーブル設計**:
| 属性 | 型 | 説明 |
|-----|-----|------|
| region | String (PK) | リージョン名 |
| model_ids | StringSet | モデルIDのセット |
| last_updated | String | ISO 8601形式のタイムスタンプ |

### 5.4 SNS トピック

**設定**:
- トピック名: `bedrock-model-detector-notifications`
- プロトコル: Email
- サブスクリプション: みのるんのメールアドレス

### 5.5 EventBridge Scheduler

**設定**:
- スケジュール: `rate(5 minutes)`
- ターゲット: Lambda関数

---

## 6. 通知メッセージ例

```
件名: 🚀 Bedrockに新しいモデルが追加されました！

本文:
東京リージョン（ap-northeast-1）とオレゴンリージョン（us-west-2）に
新しいモデルが追加されました！

📍 東京リージョン:
  • Claude Sonnet 5
    モデルID: anthropic.claude-sonnet-5-20260101-v1:0

📍 オレゴンリージョン:
  • Claude Sonnet 5
    モデルID: anthropic.claude-sonnet-5-20260101-v1:0
  • Llama 4
    モデルID: meta.llama4-70b-instruct-v1:0

---
このメッセージはBedrock Model Detectorから自動送信されています。
```

---

## 7. IaCツール

### 検討ポイント: CDK vs SAM

| 項目 | CDK | SAM |
|------|-----|-----|
| AgentCore対応 | `@aws-cdk/aws-bedrock-agentcore-alpha` | 手動でCloudFormation |
| 学習コスト | 高（TypeScript） | 低（YAML） |
| 柔軟性 | 高 | 中 |
| 既存資産 | みのるんはCDK経験あり | 参考ブログがSAM |

---

## 8. 確認事項（みのるんへの質問）

### Q1: アーキテクチャの選択
案Aの「Lambda + AgentCore Runtime（ハイブリッド）」で進めてよいですか？

### Q2: IaCツール
CDKとSAMのどちらを使いますか？
- **CDK**: AgentCore対応が楽、TypeScriptで型安全
- **SAM**: シンプル、参考ブログに近い

### Q3: 通知の頻度
- 5分おきのチェックで良いですか？
- 同じモデルが複数回通知されないようにする必要がありますか？

### Q4: SNSサブスクリプション
- メールアドレスは環境変数やパラメータで設定しますか？
- 複数のメールアドレスに通知する可能性はありますか？

### Q5: エージェントの起動方式
AgentCore Runtimeの起動方法として：
- **同期呼び出し**: Lambda内で直接呼び出し、レスポンスを待つ
- **非同期呼び出し**: SNSやSQS経由でデカップリング

どちらが良いですか？（推奨は同期呼び出し）

### Q6: 既存システムの移行
- 既存のLambda/DynamoDBは流用しますか？
- 新規で作り直しますか？

### Q7: 追加機能
将来的に追加したい機能はありますか？
- モデル削除の検知
- 特定プロバイダーのみ監視
- 通知先の追加（Slack、Teams等）

---

## 9. 次のステップ

1. 上記の確認事項について合意
2. IaCプロジェクトの初期化（CDK or SAM）
3. DynamoDBテーブルの作成
4. Lambda関数の実装
5. AgentCore Runtimeの実装
6. SNSトピック・サブスクリプションの設定
7. EventBridge Schedulerの設定
8. テスト・デプロイ

---

## 10. 参考情報

- [参考ブログ（hayao_k）](https://qiita.com/hayao_k/items/56ccb5bdd43839ad131a)
- [ListFoundationModels API](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListFoundationModels.html)
- [Bedrock AgentCore 公式ドキュメント](https://docs.aws.amazon.com/bedrock-agentcore/)
- [Strands Agents](https://strandsagents.com/)
