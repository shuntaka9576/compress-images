from __future__ import annotations

import tkinter as tk
from tkinter import font, ttk


# アプリのヘルプは外部ビューアーや配布PDFがなくても読めるようにする。
HELP_SECTIONS = (
    (
        "基本の使い方",
        (
            ("1. 写真を選ぶ", "「写真を選択…」で、処理したい写真を複数選べます。写真やフォルダを水色の枠へドロップする方法も使えます。\nフォルダを選ぶ場合は「フォルダ選択…」を押してください。"),
            ("2. 一覧の写真と枚数を確認する", "一覧には写真のサムネイルが常に表示されます。行をクリックすると右側に大きく表示します。\n「処理対象」欄でチェックの入った「対象」の写真だけを処理します。チェックを外すと「対象外」と表示され、行は薄い色で残ります。写真を見たり、再びチェックを入れたりできます。Spaceキーでもチェックを切り替えられます。"),
            ("3. 処理内容と保存方法を選ぶ", "画面上部で「圧縮・JPEG変換」または「撮影日時で名前を整理」を選びます。\n左の実行ボタンは元の写真を残して保存先へ出力します。右の実行ボタンは、確認画面の後に元の場所で写真を変更します。"),
            ("4. 結果を確認する", "処理後は成功・失敗の枚数と、一覧の結果を確認してください。「保存先を開く」で処理したフォルダを開けます。\n元の場所で変更した後は、二重の処理を防ぐため対象が解除されます。続ける場合は、処理する写真にもう一度チェックを入れてください。"),
        ),
    ),
    (
        "圧縮・JPEG変換",
        (
            ("画像サイズと画質", "初期設定は幅・高さ20%、JPEG品質80です。画像サイズと品質はスライダーや数値欄で変更できます。縦横比は変わりません。\n容量を指定したい場合だけ「ファイル容量を指定する（任意）」をONにします。予想サイズを見たいときだけ「サイズを計算」を押します。写真の選択や設定変更だけでは計算しません。計算せずに変換することもできます。"),
            ("元の写真を残して変換", "元の写真を変更せず、保存先フォルダへJPEGを出力します。保存先の初期値は converted です。\n同名ファイルがある場合は _2、_3 などを付けて保存します。"),
            ("元の写真を上書き変換…", "確認画面に表示された写真を、元の場所で変更します。JPEGはファイル名と拡張子を維持して上書きします。HEIC・PNGなどは同じ場所へJPEGを保存した後、元ファイルを削除します。\n同名の別JPEGがある写真は変更せず、エラーを表示します。"),
            ("上書き前に確認してください", "上書き変換は元に戻せません。どちらの保存方法でも、変換後のJPEGから撮影日時・GPSなどのEXIF情報を除去します。\n撮影日時による名前整理も使う場合は、先に名前を整理してください。"),
            ("対応する写真", "HEIC、HEIF、JPEG、PNG、WebPに対応しています。写真の向きは補正します。圧縮モードでフォルダを選んだ場合、サブフォルダ内の写真は処理しません。"),
        ),
    ),
    (
        "名前の整理",
        (
            ("撮影日時から新しい名前を作る", "EXIF撮影日時のあるJPEGが対象です。標準の名前は、例えば 2025_10_17_1117_00.jpg になります。\n一覧は「今のファイル名」と「変更後のファイル名」で見比べられます。撮影日時のない写真や読み込めない写真は「選択不可」と表示し、変更できない理由を名前欄に表示します。"),
            ("名前の部品を並べる", "標準の部品は「撮影日時 → 連番」です。「メーカー名」「機種名」「自由入力」を追加できます。\n部品を選んで左右ボタンを押すか、横にドラッグして並べ替えます。「自由入力」には「お台場」「渋谷」などの文字を指定できます。連番は必須です。"),
            ("名前を付けてコピー", "元のJPEGを残し、新しい名前で保存先へコピーします。保存先の初期値は converted です。\n「サブフォルダも含める」をONにすると、元のフォルダ構成も保存先へ引き継ぎます。"),
            ("元の写真の名前を変更…", "元のフォルダ内で名前だけ変更します。画像の内容やEXIF情報は変わりません。既存ファイルを上書きしないように連番を決めます。\n保存先が異なるため、コピー用のプレビューと連番が違う場合があります。実行前の確認画面で、実際の変更名を確認してください。"),
        ),
    ),
    (
        "困ったとき",
        (
            ("写真が見つからない", "写真を選び直してください。名前整理モードの対象はJPEGだけです。写真が子フォルダにある場合は「サブフォルダも含める」をONにします。"),
            ("対象から外した写真を戻したい", "一覧に残っている写真のチェックをONにしてください。「すべてチェック」でまとめて戻せます。チェックを外す操作で元の写真が削除されることはありません。"),
            ("途中で止めたい", "「中止」を押すと、次の写真から処理を止めます。処理済みの保存・上書き・名前変更は取り消されません。\nアプリを閉じる場合は、中止して処理が止まるまで待ってください。"),
            ("エラーやスキップが表示された", "一覧の理由を確認してください。上書き変換で同名の別JPEGがある場合や、名前整理で撮影日時がない場合などは、その写真を変更しません。"),
            ("解決しないとき", "この画面上部のバージョンと、一覧のエラー内容、処理できなかった写真のファイル名をお知らせください。\n配布ZIPには、アプリを開く前に読める「はじめにお読みください.pdf」も同梱しています。"),
        ),
    ),
)


class HelpWindow(tk.Toplevel):
    """スクロール・文字選択・キーボード操作に対応するアプリ内説明書。"""

    def __init__(self, parent: tk.Misc, version: str) -> None:
        super().__init__(parent)
        self.withdraw()
        self.title("ヘルプ・取扱説明書")
        self.transient(parent)
        self.minsize(620, 460)

        panel = ttk.Frame(self, padding=18)
        panel.pack(fill="both", expand=True)
        header = ttk.Frame(panel)
        header.pack(fill="x", pady=(0, 12))
        self.title_font = font.nametofont("TkDefaultFont").copy()
        self.title_font.configure(size=16, weight="bold")
        self.heading_font = font.nametofont("TkDefaultFont").copy()
        self.heading_font.configure(size=12, weight="bold")
        self.body_font = font.nametofont("TkDefaultFont").copy()
        self.body_font.configure(size=11)
        ttk.Label(header, text="写真まとめて整理", font=self.title_font).pack(side="left")
        ttk.Label(header, text=f"バージョン {version}").pack(side="right")

        self.notebook = ttk.Notebook(panel)
        self.notebook.pack(fill="both", expand=True)
        self.notebook.enable_traversal()
        for title, sections in HELP_SECTIONS:
            page = ttk.Frame(self.notebook, padding=8)
            self.notebook.add(page, text=title)
            body = tk.Text(
                page, wrap="word", font=self.body_font, borderwidth=0,
                padx=14, pady=12, background="white", foreground="#263746",
                cursor="arrow", width=60, height=18, takefocus=True,
                exportselection=False,
            )
            scrollbar = ttk.Scrollbar(page, orient="vertical", command=body.yview)
            scrollbar.pack(side="right", fill="y")
            body.configure(yscrollcommand=scrollbar.set)
            body.pack(fill="both", expand=True)
            body.tag_configure("heading", font=self.heading_font, foreground="#176b92", spacing1=8, spacing3=7)
            body.tag_configure("body", spacing3=15, lmargin1=2, lmargin2=2)
            for heading, paragraph in sections:
                body.insert("end", heading + "\n", "heading")
                body.insert("end", paragraph + "\n\n", "body")
            body.configure(state="disabled")

        footer = ttk.Frame(panel)
        footer.pack(fill="x", pady=(12, 0))
        ttk.Label(footer, text="タブで項目を選択できます。Escキーで閉じます。").pack(side="left")
        ttk.Button(footer, text="閉じる", command=self.destroy).pack(side="right")
        self.bind("<Escape>", lambda _event: self.destroy())
        # メイン画面の近くに開き、複数画面でも見失わないようにする。
        self.geometry(f"740x620+{max(0, parent.winfo_rootx() + 30)}+{max(0, parent.winfo_rooty() + 30)}")
        self.deiconify()
        self.lift()
        self.after_idle(self.notebook.focus_set)
