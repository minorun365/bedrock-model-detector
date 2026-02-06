import * as cdk from 'aws-cdk-lib';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as sns from 'aws-cdk-lib/aws-sns';
import * as subscriptions from 'aws-cdk-lib/aws-sns-subscriptions';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as scheduler from 'aws-cdk-lib/aws-scheduler';
import * as agentcore from '@aws-cdk/aws-bedrock-agentcore-alpha';
import { Construct } from 'constructs';
import * as path from 'path';

export interface BedrockModelDetectorStackProps extends cdk.StackProps {
  /** 通知先メールアドレス */
  notificationEmail: string;
  /** 監視対象リージョン（カンマ区切り） */
  targetRegions: string;
  /** Tavily API Key（ウェブ検索用） */
  tavilyApiKey?: string;
}

export class BedrockModelDetectorStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: BedrockModelDetectorStackProps) {
    super(scope, id, props);

    const { notificationEmail, targetRegions, tavilyApiKey } = props;

    // ========================================
    // DynamoDB テーブル
    // ========================================
    const modelTable = new dynamodb.Table(this, 'ModelTable', {
      tableName: 'bedrock-model-detector',
      partitionKey: { name: 'pk', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'region', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // ========================================
    // SNS トピック
    // ========================================
    const notificationTopic = new sns.Topic(this, 'NotificationTopic', {
      topicName: 'bedrock-model-detector-notifications',
      displayName: 'Bedrock新モデルお知らせくん',
    });

    // Email サブスクリプション
    notificationTopic.addSubscription(
      new subscriptions.EmailSubscription(notificationEmail)
    );

    // ========================================
    // AgentCore Runtime（通知エージェント）
    // ========================================
    const agentRuntimeArtifact = agentcore.AgentRuntimeArtifact.fromAsset(
      path.join(__dirname, '../../runtime')
    );

    const agentRuntime = new agentcore.Runtime(this, 'NotificationAgent', {
      runtimeName: 'bedrock_model_detector_agent',
      agentRuntimeArtifact: agentRuntimeArtifact,
      description: 'Bedrock新モデル通知エージェント（Tavily検索対応）',
      environmentVariables: {
        SNS_TOPIC_ARN: notificationTopic.topicArn,
        ...(tavilyApiKey && { TAVILY_API_KEY: tavilyApiKey }),
      },
      // IAM認証はデフォルト（authorizerConfigurationを設定しない）
    });

    // AgentCore RuntimeにBedrockモデル呼び出し権限を付与
    agentRuntime.addToRolePolicy(new iam.PolicyStatement({
      actions: [
        'bedrock:InvokeModel',
        'bedrock:InvokeModelWithResponseStream',
      ],
      resources: [
        'arn:aws:bedrock:*::foundation-model/*',
        'arn:aws:bedrock:*:*:inference-profile/*',
      ],
    }));

    // AgentCore RuntimeにSNS Publish権限を付与
    agentRuntime.addToRolePolicy(new iam.PolicyStatement({
      actions: ['sns:Publish'],
      resources: [notificationTopic.topicArn],
    }));

    // ========================================
    // Lambda関数（モデル検出）
    // ========================================
    const detectorFunction = new lambda.Function(this, 'DetectorFunction', {
      functionName: 'bedrock-model-detector',
      runtime: lambda.Runtime.PYTHON_3_13,
      handler: 'handler.handler',
      code: lambda.Code.fromAsset(path.join(__dirname, '../../lambda/detector')),
      timeout: cdk.Duration.seconds(60),
      memorySize: 256,
      environment: {
        TARGET_REGIONS: targetRegions,
        DYNAMODB_TABLE_NAME: modelTable.tableName,
        AGENTCORE_RUNTIME_ARN: agentRuntime.agentRuntimeArn,
      },
    });

    // Lambda に DynamoDB 読み書き権限を付与
    modelTable.grantReadWriteData(detectorFunction);

    // Lambda に Bedrock ListFoundationModels 権限を付与
    detectorFunction.addToRolePolicy(new iam.PolicyStatement({
      actions: ['bedrock:ListFoundationModels'],
      resources: ['*'],
    }));

    // Lambda に AgentCore Runtime 呼び出し権限を付与
    // ベースARNと runtime-endpoint/* 両方のパターンに対応
    detectorFunction.addToRolePolicy(new iam.PolicyStatement({
      actions: ['bedrock-agentcore:InvokeAgentRuntime'],
      resources: [
        agentRuntime.agentRuntimeArn,
        `${agentRuntime.agentRuntimeArn}/*`,
      ],
    }));

    // ========================================
    // EventBridge Scheduler（5分おきに実行）
    // ========================================
    const schedulerRole = new iam.Role(this, 'SchedulerRole', {
      assumedBy: new iam.ServicePrincipal('scheduler.amazonaws.com'),
    });

    detectorFunction.grantInvoke(schedulerRole);

    new scheduler.CfnSchedule(this, 'DetectorSchedule', {
      name: 'bedrock-model-detector-schedule',
      scheduleExpression: 'rate(1 minute)',
      flexibleTimeWindow: { mode: 'OFF' },
      target: {
        arn: detectorFunction.functionArn,
        roleArn: schedulerRole.roleArn,
      },
    });

    // ========================================
    // 出力
    // ========================================
    new cdk.CfnOutput(this, 'DynamoDBTableName', {
      description: 'DynamoDB テーブル名',
      value: modelTable.tableName,
    });

    new cdk.CfnOutput(this, 'SNSTopicArn', {
      description: 'SNS トピック ARN',
      value: notificationTopic.topicArn,
    });

    new cdk.CfnOutput(this, 'AgentRuntimeArn', {
      description: 'AgentCore Runtime ARN',
      value: agentRuntime.agentRuntimeArn,
    });

    new cdk.CfnOutput(this, 'LambdaFunctionName', {
      description: 'Lambda 関数名',
      value: detectorFunction.functionName,
    });
  }
}
