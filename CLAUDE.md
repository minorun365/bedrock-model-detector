# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## プロジェクト概要

Amazon Bedrockに新しいモデルが追加されたことを自動で検知し、メールで通知するサーバーレスアプリケーションで、Strands AgentsとBedrock AgentCoreを使っている。

## コマンド

```bash
# CDK依存関係インストール
cd cdk && npm install

# ビルド
cd cdk && npm run build

# デプロイ（必須パラメータ: notificationEmail）
cdk deploy -c notificationEmail=your-email@example.com

# 高速デプロイ（開発用・CloudFormation経由せずLambda/Dockerを直接更新）
cdk deploy --hotswap -c notificationEmail=xxx

# 削除
cdk destroy
```

## アーキテクチャ

```
EventBridge Scheduler (1分おき)
    ↓
Lambda (Python 3.13) ─── DynamoDB（差分管理）
    │
    └─ 新モデル検出 → AgentCore Runtime
                            ↓
                      Strands Agent
                        ├─ Brave Search API（モデル情報収集）
                        └─ SNS通知（1通にまとめて送信）
```

監視リージョンは us-east-1, us-west-2, ap-northeast-1 の3つで、並列に処理する。

## 主要ファイル

| ファイル | 役割 |
|---------|------|
| `cdk/lib/bedrock-model-detector-stack.ts` | 全リソースのCDKスタック定義 |
| `lambda/detector/handler.py` | モデルの検出、差分比較、AgentCoreの呼び出し |
| `runtime/agent.py` | メール本文の生成とSNS送信を行うStrands Agent |

## 重要な実装パターン

### CDK Context による設定管理
CDKとの相性に問題があるため、dotenvは使わない。設定は `-c key=value` で渡す。

### AgentCore Runtime IAM認証
Lambda実行ロールには、`agentRuntimeArn` と `agentRuntimeArn/*` の両方のリソースを許可する必要がある。

### AgentCore内でのboto3
環境変数が設定されていないため、リージョンは必ず明示的に指定する。ARNから抽出するパターンを使う。

### runtimeSessionId
最小で33文字必要になる。`f"detector-{uuid.uuid4()}"` を使う。

### SCPタグ
Organizations配下では `Project` タグが必須なので、`cdk.Tags.of(stack).add('Project', 'presales')` で付与する。

## デバッグ

詳細は `docs/TEST.md` を参照すること。DynamoDBから特定のモデルを削除すれば、新規検出をシミュレートできる。

```bash
# Lambda手動実行
aws lambda invoke --function-name bedrock-model-detector --region us-east-1 /tmp/response.json && cat /tmp/response.json

# Lambdaログ確認
aws logs tail /aws/lambda/bedrock-model-detector --region us-east-1 --follow

# AgentCoreロググループ名を確認（動的に変わる）
aws logs describe-log-groups --region us-east-1 \
  --log-group-name-prefix "/aws/bedrock-agentcore/runtimes/bedrock_model_detector" \
  --query 'logGroups[*].logGroupName' --output text

# AgentCoreログ確認（上記で取得したロググループ名を使用）
aws logs tail "/aws/bedrock-agentcore/runtimes/bedrock_model_detector_agent-xxx-DEFAULT" --region us-east-1 --follow
```
