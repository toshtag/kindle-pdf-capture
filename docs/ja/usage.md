# 使い方

## 基本的な使い方

Kindle for Mac を開いて本の最初のページに移動してから、以下を実行します。

```bash
kpc --out output/my-book
```

`--start-delay`（デフォルト 3 秒）の間に Kindle にフォーカスを切り替えてください。

## 全オプション

| オプション | デフォルト | 説明 |
|-----------|-----------|------|
| `--out PATH` | （必須） | 出力ディレクトリ |
| `--max-pages N` | 1000 | N ページで停止 |
| `--resize-width N` | 1800 | 各ページの横幅（ピクセル） |
| `--jpeg-quality N` | 80 | JPEG 品質（1-95） |
| `--save-raw` | オフ | トリミング前のスクリーンショットも保存 |
| `--start-delay N` | 3 | キャプチャ開始までの待機時間（秒） |
| `--direction DIR` | `right` | ページ送り方向: LTR は `right`、RTL（マンガ等）は `left` |
| `--pdf-dpi N` | 300 | PDF ページサイズの DPI（300 で 1800 px = 6 インチ幅） |
| `--ocr` | オフ | PDF に Tesseract テキストレイヤーを埋め込む（`[ocr]` extra が必要 — [インストール](installation.md#ocr-付きでインストール)参照。下記の注記も参照） |
| `--ocr-lang LANG` | `jpn+eng` | Tesseract の言語指定 |
| `--ocr-optimize N` | 1 | OCR 最適化レベル（0-3） |
| `--manual-crop` | オフ | ドラッグ選択UIで表紙領域を手動指定（真っ白な表紙など自動検出が失敗する場合に使用） |
| `--retry-failed` | オフ | `logs/failed_pages.json` のページのみ再キャプチャ |
| `--debug` | オフ | デバッグログを有効化 |

## 出力ディレクトリ構成

```
output/my-book/
  cropped/          # page_0001.jpg, page_0002.jpg, ...
  raw/              # トリミング前のスクリーンショット（--save-raw 時のみ）
  pdf/
    book.pdf        # 組み立て済み PDF
    book_ocr.pdf    # OCR 版（--ocr 時のみ）
  logs/
    metadata.json   # 実行サマリ
    failed_pages.json
```

## OCR と macOS Live Text

**このツールは macOS 専用であり、ほとんどの場合 `--ocr` は不要です。**

`book.pdf` はテキストデータを一切含まない JPEG 画像の集合体です。しかし macOS の Preview などの PDF ビューアは Apple の Live Text エンジンを使って画面上の文字をリアルタイムに認識するため、追加作業なしでテキスト選択・コピー・右クリック検索が可能です。Apple の日本語認識精度は Tesseract より概して高いです。

`--ocr` を使うと、Tesseract が生成したテキストレイヤーが `book_ocr.pdf` に直接埋め込まれます。PDF ビューアは Live Text の代わりにその埋め込みレイヤーを使用するため、Tesseract の文字位置が実際のグリフ位置からずれていると、テキスト選択がずれたり誤った文字が選ばれたりすることがあります。

**`--ocr` が有効な場面:**

- Windows・Linux・Live Text 非対応の古い macOS でも PDF を検索可能にしたい場合
- 全文インデクサやスクリーンリーダーなど、独自 OCR を持たず埋め込みテキストを読むツールに PDF を渡す場合

## 失敗ページの再試行

一部のページが失敗（白紙やエラー）した場合は `--retry-failed` で再実行します。

```bash
kpc --out output/my-book --retry-failed
```

`logs/failed_pages.json` に記録されたページのみを再キャプチャし、他のページはそのまま保持します。

## 使用例

```bash
# 最大 300 ページ、高品質でキャプチャ
kpc --out output/my-book --max-pages 300 --jpeg-quality 90

# 右から左に読む本（マンガ等）をキャプチャ
kpc --out output/my-manga --direction left

# OCR 付きでキャプチャ（日本語 + 英語）
kpc --out output/my-book --ocr --ocr-lang jpn+eng

# 真っ白な表紙の本をキャプチャ（表紙領域を手動指定）
kpc --out output/my-book --manual-crop

# デバッグログと生スクリーンショットを有効にしてキャプチャ
kpc --out output/my-book --save-raw --debug
```
