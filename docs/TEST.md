# テスト手順

## 通知テスト（DynamoDBからモデルを削除して新規検出をシミュレート）

### 概要

DynamoDBに保存されているモデル一覧から特定のモデルを削除することで、次回のLambda実行時にそのモデルが「新規追加」として検出され、メール通知が送信されます。

### 前提条件

- AWS CLIがインストール済み
- AWS認証が完了していること（`aws login`）

### 手順

#### 1. AWS認証

```bash
aws login
```

#### 2. 現在のモデル一覧を確認

```bash
# 東京リージョンのモデル一覧を確認
aws dynamodb get-item \
  --table-name bedrock-model-detector \
  --region us-east-1 \
  --key '{"pk": {"S": "MODEL_STATE"}, "region": {"S": "ap-northeast-1"}}' \
  --query 'Item.model_ids.L[*].S' \
  --output json | jq .
```

#### 3. 特定のモデルを削除してテスト

以下のPythonスクリプトを実行して、指定したモデルをDynamoDBから削除します。

```bash
python3 << 'EOF'
import json
import boto3

# 設定
REGION = "ap-northeast-1"  # 削除対象のリージョン
MODEL_TO_DELETE = "anthropic.claude-sonnet-4-5-20250929-v1:0"  # 削除するモデルID

# DynamoDB から現在のモデルリストを取得
dynamodb = boto3.client('dynamodb', region_name='us-east-1')
response = dynamodb.get_item(
    TableName='bedrock-model-detector',
    Key={
        'pk': {'S': 'MODEL_STATE'},
        'region': {'S': REGION}
    }
)

# 現在のモデルリスト
current_models = [item['S'] for item in response['Item']['model_ids']['L']]
print(f"現在のモデル数: {len(current_models)}")

# 指定モデルを削除
if MODEL_TO_DELETE in current_models:
    filtered_models = [m for m in current_models if m != MODEL_TO_DELETE]
    print(f"削除後のモデル数: {len(filtered_models)}")

    # DynamoDB を更新
    model_ids_dynamo = [{"S": m} for m in filtered_models]
    dynamodb.update_item(
        TableName='bedrock-model-detector',
        Key={
            'pk': {'S': 'MODEL_STATE'},
            'region': {'S': REGION}
        },
        UpdateExpression='SET model_ids = :models',
        ExpressionAttributeValues={
            ':models': {'L': model_ids_dynamo}
        }
    )
    print(f"✅ {MODEL_TO_DELETE} を削除しました")
else:
    print(f"⚠️ {MODEL_TO_DELETE} は見つかりませんでした")
EOF
```

#### 4. 通知を待つ

- EventBridge Schedulerが1分おきにLambdaを実行
- 最大1分後にメール通知が届く

#### 5. 確認ポイント

- [ ] メールが1通だけ届くこと
- [ ] 削除したモデルが「新規モデル」として通知されること
- [ ] 件名と本文が適切にフォーマットされていること

---

## よく使うモデルID

| モデル | モデルID |
|--------|----------|
| Claude Sonnet 4.5 | `anthropic.claude-sonnet-4-5-20250929-v1:0` |
| Claude Haiku 4.5 | `anthropic.claude-haiku-4-5-20251001-v1:0` |
| Claude Opus 4.5 | `anthropic.claude-opus-4-5-20251101-v1:0` |
| Claude Opus 4.6 | `anthropic.claude-opus-4-6-v1` |

---

## ログの確認

### Lambda関数のログ

```bash
aws logs tail /aws/lambda/bedrock-model-detector --region us-east-1 --follow
```

### AgentCore Runtimeのログ

```bash
# ロググループ名を確認
aws logs describe-log-groups \
  --region us-east-1 \
  --log-group-name-prefix "/aws/bedrock-agentcore/runtimes/bedrock_model_detector" \
  --query 'logGroups[*].logGroupName' \
  --output text

# ログを確認（ロググループ名は上記で確認したものを使用）
aws logs tail "/aws/bedrock-agentcore/runtimes/bedrock_model_detector_agent-lkmZVaGCZ8-DEFAULT" \
  --region us-east-1 \
  --follow
```

### 通知送信回数の確認

```bash
aws logs filter-log-events \
  --log-group-name "/aws/bedrock-agentcore/runtimes/bedrock_model_detector_agent-lkmZVaGCZ8-DEFAULT" \
  --region us-east-1 \
  --start-time $(echo "$(date -u +%s) - 900" | bc)000 \
  --filter-pattern "Notification sent" \
  --query 'events[*].message' \
  --output text | grep -c "Notification sent"
```
