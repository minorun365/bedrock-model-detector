"""
Bedrock Model Detector - Lambda関数
各リージョンのBedrockモデルをチェックし、新モデルを検知してAgentCore Runtimeを呼び出す
"""

import json
import os
import logging
import uuid
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

# ロギング設定
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# 環境変数
TARGET_REGIONS = os.environ.get('TARGET_REGIONS', 'us-east-1,us-west-2,ap-northeast-1').split(',')
DYNAMODB_TABLE_NAME = os.environ.get('DYNAMODB_TABLE_NAME', 'bedrock-model-detector')
AGENTCORE_RUNTIME_ARN = os.environ.get('AGENTCORE_RUNTIME_ARN', '')

# DynamoDBクライアント
dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table(DYNAMODB_TABLE_NAME)

# リトライ設定
RETRY_CONFIG = Config(
    retries={
        'max_attempts': 5,
        'mode': 'adaptive'
    }
)


def get_bedrock_models(region: str) -> set[str]:
    """
    指定リージョンのBedrockモデル一覧を取得
    """
    client = boto3.client('bedrock', region_name=region, config=RETRY_CONFIG)

    try:
        response = client.list_foundation_models()
        model_ids = {model['modelId'] for model in response.get('modelSummaries', [])}
        logger.info(f"[{region}] {len(model_ids)} models found")
        return model_ids
    except ClientError as e:
        logger.error(f"[{region}] Failed to list models: {e}")
        raise


def get_previous_models(region: str) -> set[str]:
    """
    DynamoDBから前回のモデル一覧を取得
    """
    try:
        response = table.get_item(
            Key={
                'pk': 'MODEL_STATE',
                'region': region
            }
        )
        item = response.get('Item', {})
        return set(item.get('model_ids', []))
    except ClientError as e:
        logger.error(f"[{region}] Failed to get previous models: {e}")
        return set()


def save_models(region: str, model_ids: set[str]) -> None:
    """
    DynamoDBにモデル一覧を保存
    """
    try:
        table.put_item(
            Item={
                'pk': 'MODEL_STATE',
                'region': region,
                'model_ids': list(model_ids),
                'last_updated': datetime.now(timezone.utc).isoformat()
            }
        )
        logger.info(f"[{region}] Saved {len(model_ids)} models to DynamoDB")
    except ClientError as e:
        logger.error(f"[{region}] Failed to save models: {e}")
        raise


def invoke_agentcore_runtime(new_models: dict[str, list[str]]) -> None:
    """
    AgentCore Runtimeを呼び出してメール通知を生成
    """
    if not AGENTCORE_RUNTIME_ARN:
        logger.error("AGENTCORE_RUNTIME_ARN is not set")
        return

    client = boto3.client('bedrock-agentcore', config=RETRY_CONFIG)

    # プロンプトを構築
    models_info = json.dumps(new_models, ensure_ascii=False, indent=2)
    prompt = f"""以下の新しいBedrockモデルが検出されました。通知メールを送信してください。

検出されたモデル:
{models_info}

リージョン名の日本語対応:
- us-east-1: バージニア北部
- us-west-2: オレゴン
- ap-northeast-1: 東京

必ず send_notification ツールを使ってメールを送信してください。"""

    payload = json.dumps({'prompt': prompt})

    try:
        # セッションIDは最小33文字必要
        session_id = f"detector-{uuid.uuid4()}"
        response = client.invoke_agent_runtime(
            agentRuntimeArn=AGENTCORE_RUNTIME_ARN,
            runtimeSessionId=session_id,
            payload=payload.encode('utf-8'),
            qualifier="DEFAULT"
        )

        # レスポンスを一括取得（バッチ処理なのでストリーミング不要）
        response_body = response['response'].read()
        response_data = json.loads(response_body)
        logger.info(f"AgentCore response: {json.dumps(response_data, ensure_ascii=False)[:500]}...")

        logger.info("AgentCore Runtime invoked successfully")
    except ClientError as e:
        logger.error(f"Failed to invoke AgentCore Runtime: {e}")
        raise


def handler(event, context):
    """
    Lambda ハンドラー
    """
    logger.info(f"Starting model detection for regions: {TARGET_REGIONS}")

    # 各リージョンのモデルを並列取得
    current_models: dict[str, set[str]] = {}

    with ThreadPoolExecutor(max_workers=len(TARGET_REGIONS)) as executor:
        future_to_region = {
            executor.submit(get_bedrock_models, region): region
            for region in TARGET_REGIONS
        }

        for future in as_completed(future_to_region):
            region = future_to_region[future]
            try:
                current_models[region] = future.result()
            except Exception as e:
                logger.error(f"[{region}] Error getting models: {e}")
                # エラーが発生したリージョンはスキップ
                continue

    # 差分を検出
    new_models: dict[str, list[str]] = {}
    previous_models: dict[str, set[str]] = {}

    for region, models in current_models.items():
        previous = get_previous_models(region)
        previous_models[region] = previous
        new = models - previous

        if new:
            new_models[region] = sorted(list(new))
            logger.info(f"[{region}] New models detected: {new}")

    # 新モデルがあればAgentCore Runtimeを呼び出し
    if new_models:
        logger.info(f"New models found: {new_models}")
        invoke_agentcore_runtime(new_models)
    else:
        logger.info("No new models detected")

    # DynamoDBを更新（和集合方式: APIから一時的に消えたモデルもDBに残す）
    for region, models in current_models.items():
        previous = previous_models.get(region, set())
        save_models(region, models | previous)

    return {
        'statusCode': 200,
        'body': json.dumps({
            'message': 'Model detection completed',
            'new_models': {k: list(v) for k, v in new_models.items()} if new_models else {}
        })
    }
