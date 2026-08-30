# 写真まとめて圧縮

HEICなどのスマホ写真を、Windows上でまとめて縮小し、JPEGとして保存する小さなデスクトップアプリです。

既定の設定は次のとおりです。

- 幅・高さを20%に縮小
- JPEG品質の上限は80
- 初期状態では自動調整せず、20%・品質80をそのまま適用
- 必要な場合のみ「ファイル容量を指定する（任意）」を開き、150KB以下などを指定可能
- 縦横比を必ず維持し、写真を引き伸ばさない
- 元画像は変更せず、保存先の `converted` フォルダへ出力
- 写真の向きは画素へ反映し、GPSなどの撮影情報は出力しない
- 同名ファイルがある場合は `_2`、`_3` を付け、上書きしない

## 利用者向け

リリースから `ImageCompressor-windows.zip` をダウンロードして展開します。中にある「はじめにお読みください.pdf」を開き、記載された順番で操作してください。

配布された `ImageCompressor.exe` をダブルクリックします。利用者側でPython、uv、ImageMagick、WindowsのHEIF画像拡張機能をインストールする必要はありません。HEICの読み込みに必要なライブラリもexeへ同梱します。

exeは現時点ではコード署名をしないため、ダウンロード後の初回起動時にWindows SmartScreenの警告が表示される場合があります。

1. HEIC写真を複数まとめて、または写真フォルダごと、水色の枠へドラッグ＆ドロップします。ドラッグが難しい場合は「フォルダ選択…」を使います。
2. 保存先は自動的に `converted` になります。必要なら変更します。
3. 「まとめて変換」を押します。
4. 完了後に「保存先を開く」を押してJPEGを確認します。

写真を選ぶと、画面下の一覧へファイルごとの現在サイズと変換後の予想サイズが表示されます。画像サイズとJPEG品質はスライダーで調整でき、指を離すと予想サイズが自動で再計算されます。数値欄へ直接入力することもできます。

対象はドロップした `.heic`、`.heif`、`.jpg`、`.jpeg`、`.png`、`.webp` です。フォルダをドロップした場合は、そのフォルダ直下の写真を処理します。サブフォルダは処理しません。

初期状態では、Windowsフォトと同様に20%・品質80で保存します。写真の内容によってファイルサイズは変わります。容量の上限が決まっている場合だけ「ファイル容量を指定する（任意）」へチェックを付けると、目標サイズの入力欄が表示されます。

## Windowsで実行・ビルドする

開発環境と依存ライブラリは `uv` で管理しています。まず[uvの公式手順](https://docs.astral.sh/uv/getting-started/installation/)でuvをインストールしてください。Python本体はuvが自動で用意します。

`run.bat` をダブルクリックするとソースから実行できます。初回のみPythonと必要なライブラリをインストールします。

配布用の単体exeを作る場合は `build.bat` をダブルクリックします。完成物は `dist\ImageCompressor.exe` です。ビルドはWindows上で行ってください。

公開GitHubリポジトリでは、Actionsの「Build Windows app」を手動実行すると、次の2ファイルをまとめた `ImageCompressor-windows.zip` をダウンロードできます。

- `ImageCompressor.exe`
- `はじめにお読みください.pdf`（非エンジニア向けの導入・操作手順書）

CIは `windows-latest` 上でテストとexe生成を行い、完成したexe自身でHEICからJPEGへの変換テストを通してからZIPを作成します。`v` で始まるタグをpushした場合は、同じZIPをGitHub Releaseにも添付します。

## 開発

```bash
uv sync --frozen --all-groups
uv run --frozen pytest
uv run --frozen python app.py --self-test
uv run --frozen python app.py
```

Macでテスト用アプリを再作成する場合は `./build-mac.sh` を実行します。固有のバンドルIDとアプリアイコンを設定した `dist/ImageCompressor.app` が作成されます。

依存バージョンは `uv.lock` に固定し、リポジトリへコミットします。HEICの読み込みには `pillow-heif`、画像処理には Pillow、Windows用exeの作成には PyInstallerを使っています。
