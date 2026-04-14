# アーキテクチャ

## モジュール構成

```
src/kindle_pdf_capture/
  __init__.py        # バージョン
  main.py            # CLI エントリーポイント（click）
  orchestrator.py    # セッション状態・スキップロジック・終了判定
  window_capture.py  # Kindle ウィンドウ検出とスクリーンショット（Quartz）
  page_turner.py     # 右矢印キーイベント送信（Quartz Event Services）
  render_wait.py     # フレーム差分ポーリングによる描画完了待機
  cropper.py         # コンテンツ領域検出（OpenCV 輪郭解析）
  normalize.py       # リサイズ・白補正・シャープ化・JPEG 保存（Pillow）
  pdf_builder.py     # JPEG → PDF 組み立て（img2pdf）と最適化（pikepdf）
  ocr.py             # ocrmypdf サブプロセスラッパー
```

## キャプチャループ（1 ページあたり）

```
find_kindle_window()
  -> CGWindowList フィルタ: PID, layer=0, 画面上, 最大面積
  -> キャプチャ + コンテンツページ検証（輝度 + エッジ密度）

各ページで:
  capture_window()           # スクリーンショット取得
  _find_header_bottom()      # Kindle ヘッダー区切り線を検出
  detect_content_region()    # ヘッダー除去後の画像で輪郭解析
  normalize_image()          # リサイズ・白補正・シャープ化
  save_jpeg()                # cropped/page_XXXX.jpg に保存
  send_page_turn_key()       # ページ送り（左 or 右）
  wait_for_render()          # フレーム差分が安定するまでポーリング
  record_duplicate()         # 16x16 ダウンスケールの MD5 で終端検出

build_pdf(dpi=300)           # img2pdf: JPEG → PDF（書籍サイズ）
optimise_pdf()               # pikepdf: ストリーム圧縮、アトミック上書き
run_ocr()                    # ocrmypdf サブプロセス（任意）
```

## テスタビリティ設計

macOS 固有の呼び出し（Quartz, AppKit）はすべて依存注入可能な関数パラメータとして抽象化されています。テストではモックを注入するため、Screen Recording や Accessibility 権限なしにどのプラットフォームでもテストスイートが実行できます。

```python
# プロダクション
find_kindle_window()

# テスト時
find_kindle_window(
    get_pid_fn=lambda _: 1234,
    list_windows_fn=lambda: [fake_window_info],
    capture_fn=lambda w: np.zeros((900, 1200, 3), dtype=np.uint8),
)
```

## 終端検出（end-of-book detection）

セッションは重複フレームのストリークを追跡します。ページ送り後の新しいフレームをハッシュ化（16x16 ダウンスケールのグレースケール画像の MD5）し、同じハッシュが `_DUPLICATE_STREAK_LIMIT`（= 3）回連続して現れたらループを停止します。

## CI / テスト戦略

- テスト：pytest、macOS 権限不要
- リント：ruff check + ruff format
- マトリックス：Python 3.11 と 3.12、macos-latest
- ユニットテストはすべてモックで完結、E2E は実 Kindle セッションが必要（手動のみ）
