# Bedrock Model Detector - TODO

## 進捗管理

- [ ] 未着手
- [x] 完了
- [~] 進行中

---

## Phase 1: プロジェクト初期化

- [x] 要件定義（PLAN.md）
- [x] 詳細仕様（SPEC.md）
- [x] CDKプロジェクト初期化
  - [x] `cdk init app --language typescript`
  - [x] 必要なパッケージのインストール
    - [x] `@aws-cdk/aws-bedrock-agentcore-alpha`
    - [x] `aws-cdk-lib`
  - [x] cdk.jsonの設定

---

## Phase 2: インフラ構築（CDK）

- [x] DynamoDBテーブル
  - [x] テーブル定義
  - [x] オンデマンドキャパシティ設定

- [x] SNSトピック
  - [x] トピック作成
  - [x] Emailサブスクリプション（CDK Context経由）

- [x] Lambda関数（検出）
  - [x] Python 3.13ランタイム
  - [x] 環境変数設定
  - [x] IAMロール・権限設定
  - [x] EventBridge Schedulerトリガー（5分おき）

- [x] AgentCore Runtime
  - [x] L2 Construct使用
  - [x] IAM認証モード設定（デフォルト）
  - [x] 環境変数設定（SNS_TOPIC_ARN）
  - [x] IAMロール・権限設定

- [x] EventBridge Scheduler
  - [x] スケジュール定義（rate(5 minutes)）
  - [x] Lambdaターゲット設定

---

## Phase 3: アプリケーション実装

- [x] Lambda関数（detector）
  - [x] handler.py
    - [x] ListFoundationModels API呼び出し（3リージョン並列）
    - [x] DynamoDB読み取り
    - [x] 差分計算ロジック
    - [x] AgentCore Runtime呼び出し
    - [x] DynamoDB更新
    - [x] リトライロジック
  - [x] requirements.txt（不要 - boto3は標準搭載）

- [x] AgentCore Runtime（agent）
  - [x] agent.py
    - [x] Strands Agent設定
    - [x] システムプロンプト
    - [x] send_notificationツール
  - [x] requirements.txt
  - [x] Dockerfile（Python 3.13ベース）

---

## Phase 4: テスト・デプロイ

- [x] CDKデプロイ
  - [x] `cdk synth`で確認
  - [x] `cdk deploy`
  - [x] SNSサブスクリプション確認メール承認

- [x] 統合テスト
  - [x] 手動でLambda実行
  - [x] AgentCore Runtime呼び出し成功
  - [x] SNS経由でメール送信成功
  - [ ] メール受信確認（みのるん待ち）
  - [ ] 5分おきの自動実行確認

---

## Phase 5: 運用準備

- [ ] ドキュメント整備
  - [ ] README.md作成
  - [ ] デプロイ手順書

- [ ] モニタリング設定（オプション）
  - [ ] CloudWatch Logsアラーム
  - [ ] Lambda エラー監視

---

## 既知の問題・修正済み

- [x] dotenv 17がCDKの標準出力を妨げる → CDK Contextに変更
- [x] runtimeSessionIdが短すぎる（最小33文字） → UUIDを使用
- [x] SCP必須のProjectタグがない → `cdk.Tags.of(stack).add('Project', 'presales')` を追加
- [x] InvokeAgentRuntime IAM権限エラー → リソースARNに `/*` サフィックスを追加
- [x] AgentCore Runtime起動時のリージョンエラー → SNSクライアント作成時にリージョンを明示
- [x] ストリーミングレスポンスの処理エラー → `.read()` で一括取得に変更

---

## 備考

- CDKデプロイ先: us-east-1（バージニア北部）
- AgentCoreモデル: Claude Sonnet 4.5（新モデル検出時のみ起動するのでコスト効率◎）
- 監視対象リージョン: us-east-1, us-west-2, ap-northeast-1
- デプロイコマンド: `cdk deploy -c notificationEmail=your-email@example.com`
