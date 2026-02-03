# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## プロジェクト概要

Amazon Bedrockに新しいモデルが追加されたことを自動検知し、メールで通知するサーバーレスアプリケーション。Strands Agents + Bedrock AgentCoreを活用。

## コマンド

```bash
# CDK依存関係インストール
cd cdk && npm install

# ビルド
cd cdk && npm run build

# テスト
cd cdk && npm test

# デプロイ（必須パラメータ: notificationEmail）
cdk deploy -c notificationEmail=your-email@example.com -c tavilyApiKey=tvly-xxx

# 高速デプロイ（開発用）
cdk deploy --hotswap -c notificationEmail=xxx -c tavilyApiKey=xxx

# 削除
cdk destroy
```

## アーキテクチャ

```
EventBridge Scheduler (5分おき)
    ↓
Lambda (Python 3.13) ─── DynamoDB（差分管理）
    │
    └─ 新モデル検出 → AgentCore Runtime
                            ↓
                      Strands Agent
                        ├─ Tavily検索
                        └─ SNS通知
```

**監視リージョン**: us-east-1, us-west-2, ap-northeast-1（3リージョン並列処理）

## 主要ファイル

| ファイル | 役割 |
|---------|------|
| `cdk/lib/bedrock-model-detector-stack.ts` | CDKスタック定義（全リソース） |
| `lambda/detector/handler.py` | モデル検出・差分比較・AgentCore呼び出し |
| `runtime/agent.py` | Strands Agent（メール本文生成・SNS送信） |

## 重要な実装パターン

### CDK Context による設定管理
dotenvは使わない（CDKとの相性問題あり）。設定は `-c key=value` で渡す。

### AgentCore Runtime IAM認証
Lambda実行ロールには `agentRuntimeArn` と `agentRuntimeArn/*` 両方のリソースを許可する必要あり。

### AgentCore内でのboto3
リージョン明示指定が必須（環境変数が設定されていない）。ARNから抽出するパターンを使用。

### runtimeSessionId
最小33文字必要。`f"detector-{uuid.uuid4()}"` を使用。

### SCPタグ
Organizations配下では `Project` タグが必須。`cdk.Tags.of(stack).add('Project', 'presales')` で付与。

## テスト方法

`docs/TEST.md` 参照。DynamoDBから特定モデルを削除して新規検出をシミュレート可能。

```bash
# Lambda手動実行
aws lambda invoke --function-name bedrock-model-detector --region us-east-1 /tmp/response.json

# AgentCoreログ確認
aws logs tail "/aws/bedrock-agentcore/runtimes/bedrock_model_detector_agent-xxx-DEFAULT" --region us-east-1 --follow
```
