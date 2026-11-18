#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib/core';
import { BedrockModelDetectorStack } from '../lib/bedrock-model-detector-stack';

const app = new cdk.App();

// CDK Contextから設定を取得
const notificationEmail = app.node.tryGetContext('notificationEmail');
if (!notificationEmail) {
  throw new Error(
    'notificationEmail が指定されていません。\n' +
    '使用方法: cdk deploy -c notificationEmail=your-email@example.com'
  );
}

const targetRegions = app.node.tryGetContext('targetRegions') || 'us-east-1,us-west-2,ap-northeast-1';

const stack = new BedrockModelDetectorStack(app, 'BedrockModelDetectorStack', {
  env: {
    account: process.env.CDK_DEFAULT_ACCOUNT,
    region: 'us-east-1', // バージニア北部にデプロイ
  },
  notificationEmail,
  targetRegions,
});

// SCP必須タグを追加
cdk.Tags.of(stack).add('Project', 'presales');
