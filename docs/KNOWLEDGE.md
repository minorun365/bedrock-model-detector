# Bedrock Model Detector - ナレッジ

このプロジェクトで得た学びや経験を記録する。

---

## CDK関連

### dotenv 17とCDKの相性問題

**発生日**: 2026-02-03

dotenv 17.x をCDKプロジェクトで使用すると、`cdk synth` や `cdk deploy` の標準出力が表示されなくなる問題が発生。

**症状**:
- `cdk synth` を実行してもCloudFormationテンプレートが出力されない
- dotenvのtipメッセージ（`[dotenv@17.2.3] injecting env...`）だけが表示される
- `cdk.out` ディレクトリが作成されない

**原因**:
dotenv 17.x はdotenvxのAPIを使用しており、標準出力にログを出力する。これがCDKの出力をインターセプトしている可能性がある。

**解決策**:
dotenvを使わず、CDK Contextで設定を渡す方式に変更。

```typescript
// bin/cdk.ts
const notificationEmail = app.node.tryGetContext('notificationEmail');
```

```bash
# デプロイ時
cdk deploy -c notificationEmail=your-email@example.com
```

**代替案**:
- dotenv 16.x にダウングレード
- 環境変数を直接 `export` で設定

---

### CDK Contextによる設定管理

CDKで設定値を管理する標準的な方法。

```typescript
// 値の取得
const value = app.node.tryGetContext('key');

// デフォルト値付き
const value = app.node.tryGetContext('key') || 'default';
```

```bash
# コマンドラインで渡す
cdk deploy -c key=value -c key2=value2

# cdk.jsonに書く（gitにコミットしてよい値のみ）
{
  "context": {
    "key": "value"
  }
}
```

---

## AgentCore Runtime関連

### L2 ConstructのARNプロパティ

**発生日**: 2026-02-03

`@aws-cdk/aws-bedrock-agentcore-alpha` のRuntimeクラスでARNを取得する際、プロパティ名に注意。

**正しいプロパティ名**:
```typescript
agentRuntime.agentRuntimeArn  // ✅ 正しい
agentRuntime.runtimeArn       // ❌ 存在しない
```

**その他のプロパティ**:
- `agentRuntimeId` - ランタイムID
- `agentRuntimeName` - ランタイム名
- `agentRuntimeVersion` - バージョン

---

### runtimeSessionIdの最小文字数

**発生日**: 2026-02-03

`invoke_agent_runtime` APIの `runtimeSessionId` パラメータは最小33文字必要。

**エラーメッセージ**:
```
ParamValidationError: Invalid length for parameter runtimeSessionId, value: 23, valid min length: 33
```

**解決策**:
UUIDを使用して十分な長さを確保。

```python
import uuid

session_id = f"detector-{uuid.uuid4()}"  # 例: detector-550e8400-e29b-41d4-a716-446655440000
```

---

### IAM認証モード（デフォルト）

AgentCore RuntimeのIAM認証はデフォルトで有効。`authorizerConfiguration` を設定しなければIAM認証が使われる。

```typescript
const agentRuntime = new agentcore.Runtime(this, 'MyRuntime', {
  runtimeName: 'my-agent',
  agentRuntimeArtifact: artifact,
  // authorizerConfigurationを省略 → IAM認証
});
```

Lambdaから呼び出す場合は、Lambda実行ロールに以下の権限を付与：

```typescript
// ベースARNと全サブリソースの両方を許可
lambdaFunction.addToRolePolicy(new iam.PolicyStatement({
  actions: ['bedrock-agentcore:InvokeAgentRuntime'],
  resources: [
    agentRuntime.agentRuntimeArn,
    `${agentRuntime.agentRuntimeArn}/*`,
  ],
}));
```

**注意**: `agentRuntime.agentRuntimeArn` だけでは不十分。`/runtime-endpoint/DEFAULT` などのサブリソースへのアクセスも必要なため、`/*` サフィックス付きのARNも追加する。

---

### AgentCore Runtime内でのboto3クライアント作成

**発生日**: 2026-02-04

AgentCore Runtime（コンテナ）内でboto3クライアントを作成する際、リージョンを明示的に指定しないとエラーになる。

**エラーメッセージ**:
```
botocore.exceptions.NoRegionError: You must specify a region.
```

**原因**:
AgentCore Runtimeの実行環境では `AWS_REGION` や `AWS_DEFAULT_REGION` 環境変数が自動設定されていない。

**解決策**:
ARNからリージョンを抽出するか、環境変数で明示的に渡す。

```python
# ARNからリージョンを抽出
def get_region_from_arn(arn: str) -> str:
    if arn:
        parts = arn.split(':')
        if len(parts) >= 4:
            return parts[3]
    return 'us-east-1'

sns_client = boto3.client('sns', region_name=get_region_from_arn(SNS_TOPIC_ARN))
```

---

### InvokeAgentRuntime APIのレスポンス処理

**発生日**: 2026-02-04

`invoke_agent_runtime` APIのレスポンスは、ストリーミングではなく `.read()` で一括取得できる。

```python
response = client.invoke_agent_runtime(
    agentRuntimeArn=arn,
    runtimeSessionId=session_id,
    payload=payload.encode('utf-8'),
    qualifier="DEFAULT"
)

# 一括取得（バッチ処理向け）
response_body = response['response'].read()
response_data = json.loads(response_body)
```

**注意**: ストリーミングが必要な場合は、イベントストリームとして処理する必要があるが、バッチ処理では不要。

---

## SCP（Service Control Policy）関連

### Projectタグ必須ポリシー

**発生日**: 2026-02-04

Organizations配下のアカウントでSCPにより `Project` タグが必須になっている場合、CDKデプロイ時にタグを付与しないとリソース作成が失敗する。

**エラーメッセージ**:
```
User: ... is not authorized to perform: lambda:CreateFunction ... with an explicit deny in a service control policy
```

**解決策**:
CDKでスタック全体にタグを追加。

```typescript
// bin/cdk.ts
const stack = new MyStack(app, 'MyStack', { ... });
cdk.Tags.of(stack).add('Project', 'presales');
```

---

## EventBridge Scheduler + AgentCore Runtime

EventBridge SchedulerからAgentCore Runtimeを直接呼び出すことも可能（Universal Target）。

ただし、5分おきの実行ではAgentCoreの起動オーバーヘッドが気になるため、今回はLambda経由のハイブリッド構成を採用。

**参考**:
- [Using universal targets in EventBridge Scheduler](https://docs.aws.amazon.com/scheduler/latest/UserGuide/managing-targets-universal.html)

---

## Bedrock API関連

### ListFoundationModels API

各リージョンのBedrockモデル一覧を取得するAPI。

```python
import boto3

client = boto3.client('bedrock', region_name='us-east-1')
response = client.list_foundation_models()

for model in response['modelSummaries']:
    print(model['modelId'])
```

**注意点**:
- リージョンごとに利用可能なモデルが異なる
- レスポンスには `modelId`, `modelName`, `providerName` などが含まれる
- IAM権限: `bedrock:ListFoundationModels`（リソースは `*`）

---

## デプロイ済みリソース

| リソース | 値 |
|---------|-----|
| DynamoDB | `bedrock-model-detector` |
| Lambda | `bedrock-model-detector` |
| AgentCore Runtime | `bedrock_model_detector_agent-lkmZVaGCZ8` |
| SNS Topic | `bedrock-model-detector-notifications` |
| リージョン | us-east-1 |
| CloudFormationスタック | `BedrockModelDetectorStack` |

---

## トラブルシューティング

### Lambda実行時のエラー確認

```bash
# Lambda実行
aws lambda invoke --function-name bedrock-model-detector --region us-east-1 --log-type Tail /tmp/response.json

# ログをデコード
aws lambda invoke --function-name bedrock-model-detector --region us-east-1 --log-type Tail /tmp/response.json --query 'LogResult' --output text | base64 -d
```

### CloudWatch Logsの確認

```bash
aws logs tail /aws/lambda/bedrock-model-detector --region us-east-1 --follow
```
