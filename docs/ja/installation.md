# インストール

## 必要要件

- macOS 12 以降
- Python 3.11 以降
- Kindle for Mac（Mac App Store からインストール）
- [uv](https://github.com/astral-sh/uv)（推奨）または pip

## uv でインストール（推奨）

```bash
uv tool install kindle-pdf-capture
```

## pip でインストール

```bash
pip install kindle-pdf-capture
```

## OCR 付きでインストール

OCR には Tesseract と Ghostscript が必要です。

```bash
# システム依存ライブラリのインストール（macOS）
brew install tesseract tesseract-lang ghostscript

# OCR オプション付きでパッケージをインストール
pip install "kindle-pdf-capture[ocr]"
```

## ソースからインストール

```bash
git clone https://github.com/toshtag/kindle-pdf-capture.git
cd kindle-pdf-capture
uv sync
uv run kpc --help
```

## macOS パーミッション

実行前に、使用しているターミナルアプリ（Terminal.app、iTerm2 など）に以下の権限を付与してください。

1. **画面収録** — システム設定 > プライバシーとセキュリティ > 画面収録
2. **アクセシビリティ** — システム設定 > プライバシーとセキュリティ > アクセシビリティ

設定手順の詳細は[パーミッション ガイド](permissions.md)をご覧ください。
