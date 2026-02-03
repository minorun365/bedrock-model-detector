# Bedrock Model Detector

Amazon Bedrockに新しいモデルが追加されたことを自動検知し、メールで通知するサーバーレスアプリケーションです。

## 概要

- 3リージョン（バージニア北部、オレゴン、東京）のBedrockモデルを5分おきに監視
- 新モデル追加時にAIエージェントが日本語の通知メールを自動生成
- **Tavilyウェブ検索**でモデルの特徴を調べて通知に追加
- [Strands Agents](https://strandsagents.com/) + [Bedrock AgentCore](https://docs.aws.amazon.com/bedrock/latest/userguide/agents-agentcore.html) を活用

## アーキテクチャ

```
EventBridge Scheduler (5分おき)
    │
    ▼
Lambda関数 (Python 3.13)
    ├── Bedrock ListFoundationModels API（3リージョン並列）
    ├── DynamoDB（差分管理）
    └── 差分あり → AgentCore Runtime 呼び出し
                        │
                        ▼
                  Strands Agent（メール本文生成）
                        │
                        ▼
                  Amazon SNS → Email
```

## 前提条件

- AWS CLI がインストール済み
- AWS CDK がインストール済み（`npm install -g aws-cdk`）
- Node.js 18以上
- Python 3.13
- AWS アカウントで cdk bootstrap が実行済み

## デプロイ手順

### 1. リポジトリをクローン

```bash
git clone https://github.com/minorun365/bedrock-model-detector.git
cd bedrock-model-detector
```

### 2. CDK依存関係をインストール

```bash
cd cdk
npm install
```

### 3. デプロイ

```bash
# AWS認証（必要に応じて）
aws login

# デプロイ（メールアドレスとTavily APIキーを指定）
cdk deploy \
  -c notificationEmail=your-email@example.com \
  -c tavilyApiKey=tvly-your-api-key
```

### オプション: 高速デプロイ（Hotswap）

開発中はHotswapを使うと高速にデプロイできます（本番環境では使用禁止）。

```bash
cdk deploy --hotswap \
  -c notificationEmail=your-email@example.com \
  -c tavilyApiKey=tvly-your-api-key
```

### オプション: 監視対象リージョンを変更

```bash
cdk deploy \
  -c notificationEmail=your-email@example.com \
  -c tavilyApiKey=tvly-your-api-key \
  -c targetRegions=us-east-1,us-west-2
```

### 4. SNSサブスクリプションの確認

デプロイ後、指定したメールアドレスにSNSの確認メールが届きます。
メール内のリンクをクリックしてサブスクリプションを承認してください。

## 設定パラメータ

| パラメータ | 説明 | デフォルト値 |
|-----------|------|-------------|
| `notificationEmail` | 通知先メールアドレス | 必須 |
| `tavilyApiKey` | Tavily APIキー（ウェブ検索用） | 任意 |
| `targetRegions` | 監視対象リージョン（カンマ区切り） | `us-east-1,us-west-2,ap-northeast-1` |

> **Note**: Tavily APIキーは [tavily.com](https://tavily.com/) で取得できます。

## ディレクトリ構成

```
bedrock-model-detector/
├── cdk/                    # CDK インフラコード
│   ├── bin/cdk.ts          # CDK エントリーポイント
│   └── lib/                # スタック定義
├── lambda/                 # Lambda関数
│   └── detector/           # モデル検出Lambda
├── runtime/                # AgentCore Runtime
│   ├── agent.py            # Strands Agent
│   └── Dockerfile
└── docs/                   # 設計ドキュメント
```

## 通知メールのサンプル

```
件名: Bedrockに新しいモデルが追加されました

Amazon Bedrockに新しいモデルが出現しました🚀

■ AWS東京リージョン（ap-northeast-1）
  • anthropic.claude-sonnet-5-20260101-v1:0
    → 最新のClaude Sonnet 5は、コーディング能力が大幅に向上し、
      長文コンテキストの処理も改善されています。

---
Bedrock Model Detector
```

## 削除方法

```bash
cd cdk
cdk destroy
```

## 技術スタック

- **IaC**: AWS CDK (TypeScript)
- **Lambda**: Python 3.13
- **Agent**: Strands Agents + Bedrock AgentCore Runtime
- **ウェブ検索**: Tavily API
- **データストア**: Amazon DynamoDB
- **通知**: Amazon SNS (Email)
- **スケジューラ**: Amazon EventBridge Scheduler