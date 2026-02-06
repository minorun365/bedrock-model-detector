# テスト手順

## 通知テスト（DynamoDBからモデルを削除して新規検出をシミュレート）

### 概要

DynamoDBに保存されているモデル一覧から特定のモデルを削除することで、次回のLambda実行時にそのモデルが「新規追加」として検出され、メール通知が送信されます。

### 前提条件

- AWS CLIがインストール済み
- AWS SSO認証が完了していること

### 手順

#### 1. AWS認証

```bash
aws sso login --profile sandbox
```

#### 2. 現在のモデル一覧を確認

```bash
# 東京リージョンのモデル一覧を確認
aws dynamodb get-item \
  --table-name bedrock-model-detector \
  --profile sandbox \
  --region us-east-1 \
  --key '{"pk": {"S": "MODEL_STATE"}, "region": {"S": "ap-northeast-1"}}' \
  --query 'Item.model_ids.L[*].S' \
  --output json | jq .
```

#### 3. 特定のモデルを全リージョンから一括削除

以下のPythonスクリプトで、指定したモデルを**3リージョンすべて**のDynamoDBから一括削除します。
`MODEL_TO_DELETE` を削除したいモデルIDに変更して実行してください。

```bash
python3 << 'EOF'
import boto3

# === 設定 ===
MODEL_TO_DELETE = "anthropic.claude-opus-4-6-v1"  # 削除するモデルID
REGIONS = ["us-east-1", "us-west-2", "ap-northeast-1"]

session = boto3.Session(profile_name="sandbox", region_name="us-east-1")
dynamodb = session.resource("dynamodb")
table = dynamodb.Table("bedrock-model-detector")

for region in REGIONS:
    resp = table.get_item(Key={"pk": "MODEL_STATE", "region": region})
    item = resp["Item"]
    old_models = item["model_ids"]
    new_models = [m for m in old_models if m != MODEL_TO_DELETE]
    removed = len(old_models) - len(new_models)
    print(f"{region}: {len(old_models)} -> {len(new_models)} models (removed {removed})")
    if removed > 0:
        table.update_item(
            Key={"pk": "MODEL_STATE", "region": region},
            UpdateExpression="SET model_ids = :m",
            ExpressionAttributeValues={":m": new_models},
        )
        print(f"  -> OK!")
    else:
        print(f"  -> not found, skipping")
EOF
```

#### 4. （任意）単一リージョンのみ削除

特定リージョンだけをテストしたい場合は、上記スクリプトの `REGIONS` を変更してください。

```python
REGIONS = ["ap-northeast-1"]  # 東京リージョンのみ
```

#### 5. 通知を待つ

- EventBridge Schedulerが1分おきにLambdaを実行
- 最大1分後にメール通知が届く

#### 6. 確認ポイント

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
aws logs tail /aws/lambda/bedrock-model-detector --region us-east-1 --profile sandbox --follow
```

### AgentCore Runtimeのログ

```bash
# ロググループ名を確認（動的に変わるため毎回確認が必要）
aws logs describe-log-groups \
  --region us-east-1 \
  --profile sandbox \
  --log-group-name-prefix "/aws/bedrock-agentcore/runtimes/bedrock_model_detector" \
  --query 'logGroups[*].logGroupName' \
  --output text

# ログを確認（上記で取得したロググループ名を使用）
aws logs tail "<上記で取得したロググループ名>" \
  --region us-east-1 \
  --profile sandbox \
  --follow
```
