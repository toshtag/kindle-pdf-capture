# コントリビューション

## 開発環境のセットアップ

```bash
git clone https://github.com/toshtag/kindle-pdf-capture.git
cd kindle-pdf-capture
uv sync
```

## テストの実行

```bash
uv run pytest
uv run pytest --cov=kindle_pdf_capture --cov-report=term-missing
```

すべてのテストはモックを使った閉じた環境で実行されます。macOS の権限や Kindle の起動は不要です。

## リントとフォーマット

```bash
uv run ruff check .
uv run ruff format .
```

## コミット規約

[Conventional Commits](https://www.conventionalcommits.org/) に従ってください。

```
feat(scope): 新機能の追加
fix(scope): バグ修正
test(scope): テストの追加・更新
docs: ドキュメントの更新
chore: メンテナンス
ci: CI/CD の変更
refactor(scope): 挙動を変えないコードの整理
```

## ブランチと PR のワークフロー

1. ブランチを作成する：`git checkout -b feat/my-feature`
2. TDD に従って変更する（テストコミット → 実装コミットの順）
3. プルリクエストを作成する（日英バイリンガルテンプレートを使用）
4. CI（Python 3.11 および 3.12）がパスしていることを確認する
5. マージコミットでマージする（スカッシュとリベースは無効化済み）

## Issue の報告

[GitHub Issues](https://github.com/toshtag/kindle-pdf-capture/issues) を使用してください。バグ報告の際は、macOS バージョン・Python バージョン・完全なエラー出力を含めてください。
