from __future__ import annotations

from pathlib import Path

from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output" / "pdf" / "はじめにお読みください.pdf"

PAGE_WIDTH, PAGE_HEIGHT = A4
LEFT = 54
RIGHT = PAGE_WIDTH - 54
CONTENT_WIDTH = RIGHT - LEFT

NAVY = HexColor("#123b5d")
BLUE = HexColor("#159bd7")
PALE_BLUE = HexColor("#eaf6fc")
GREEN = HexColor("#16865c")
PALE_GREEN = HexColor("#e9f7f0")
ORANGE = HexColor("#d98a00")
PALE_ORANGE = HexColor("#fff5dc")
RED = HexColor("#c33c3c")
PALE_RED = HexColor("#fff0f0")
TEXT = HexColor("#263746")
MUTED = HexColor("#687786")
LINE = HexColor("#cdd9e1")
PANEL = HexColor("#f5f8fa")


def register_fonts() -> tuple[str, str]:
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont

    pdfmetrics.registerFont(UnicodeCIDFont("HeiseiKakuGo-W5"))
    return "HeiseiKakuGo-W5", "HeiseiKakuGo-W5"


FONT, BOLD = register_fonts()


def wrapped_lines(text: str, font: str, size: float, width: float) -> list[str]:
    lines: list[str] = []
    current = ""
    for character in text:
        if character == "\n":
            lines.append(current)
            current = ""
            continue
        candidate = current + character
        if current and pdfmetrics.stringWidth(candidate, font, size) > width:
            lines.append(current)
            current = character
        else:
            current = candidate
    if current or not lines:
        lines.append(current)
    return lines


def paragraph(
    pdf: canvas.Canvas,
    text: str,
    x: float,
    y: float,
    width: float,
    *,
    size: float = 10,
    leading: float = 15,
    color=TEXT,
    font: str = FONT,
) -> float:
    pdf.setFont(font, size)
    pdf.setFillColor(color)
    for line in wrapped_lines(text, font, size, width):
        pdf.drawString(x, y, line)
        y -= leading
    return y


def page_title(pdf: canvas.Canvas, number: str, title: str, y: float = 770) -> float:
    pdf.setFillColor(NAVY)
    pdf.setFont(BOLD, 20)
    pdf.drawString(LEFT, y, f"{number}  {title}" if number else title)
    return y - 34


def footer(pdf: canvas.Canvas, page_number: int) -> None:
    pdf.setStrokeColor(LINE)
    pdf.line(LEFT, 42, RIGHT, 42)
    pdf.setFillColor(MUTED)
    pdf.setFont(FONT, 7.5)
    pdf.drawString(LEFT, 26, "写真まとめて整理　かんたん操作ガイド")
    pdf.drawRightString(RIGHT, 26, str(page_number))


def rounded_box(
    pdf: canvas.Canvas,
    x: float,
    y_top: float,
    width: float,
    height: float,
    *,
    fill,
    stroke,
    radius: float = 9,
) -> None:
    pdf.setFillColor(fill)
    pdf.setStrokeColor(stroke)
    pdf.setLineWidth(0.8)
    pdf.roundRect(x, y_top - height, width, height, radius, fill=1, stroke=1)


def info_box(
    pdf: canvas.Canvas,
    title: str,
    body: str,
    y_top: float,
    *,
    fill=PALE_BLUE,
    stroke=BLUE,
    title_color=NAVY,
    height: float = 82,
) -> float:
    rounded_box(pdf, LEFT, y_top, CONTENT_WIDTH, height, fill=fill, stroke=stroke)
    pdf.setFillColor(title_color)
    pdf.setFont(BOLD, 11)
    pdf.drawString(LEFT + 15, y_top - 22, title)
    paragraph(
        pdf,
        body,
        LEFT + 15,
        y_top - 44,
        CONTENT_WIDTH - 30,
        size=9,
        leading=13,
    )
    return y_top - height - 14


def step_card(
    pdf: canvas.Canvas,
    number: int,
    title: str,
    body: str,
    y_top: float,
    *,
    height: float = 72,
) -> float:
    rounded_box(pdf, LEFT, y_top, CONTENT_WIDTH, height, fill=PALE_BLUE, stroke=LINE)
    center_x = LEFT + 30
    center_y = y_top - height / 2
    pdf.setFillColor(BLUE)
    pdf.circle(center_x, center_y, 17, fill=1, stroke=0)
    pdf.setFillColor(white)
    pdf.setFont(BOLD, 12)
    pdf.drawCentredString(center_x, center_y - 4, str(number))
    pdf.setFillColor(NAVY)
    pdf.setFont(BOLD, 11)
    pdf.drawString(LEFT + 60, y_top - 24, title)
    paragraph(
        pdf,
        body,
        LEFT + 60,
        y_top - 45,
        CONTENT_WIDTH - 76,
        size=8.5,
        leading=12,
    )
    return y_top - height - 11


def bullet(pdf: canvas.Canvas, text: str, y: float) -> float:
    pdf.setFillColor(NAVY)
    pdf.circle(LEFT + 6, y + 3, 2.4, fill=1, stroke=0)
    return paragraph(pdf, text, LEFT + 16, y + 7, CONTENT_WIDTH - 16, size=9.5)


def draw_mode_switch(pdf: canvas.Canvas, y_top: float, rename: bool) -> float:
    rounded_box(pdf, LEFT, y_top, CONTENT_WIDTH, 42, fill=PANEL, stroke=LINE)
    pdf.setFont(BOLD, 9)
    pdf.setFillColor(NAVY)
    pdf.drawString(LEFT + 14, y_top - 25, "処理内容")
    items = [("圧縮・JPEG変換", not rename), ("撮影日時で名前を整理", rename)]
    x = LEFT + 95
    for label, selected in items:
        pdf.setFillColor(BLUE if selected else white)
        pdf.setStrokeColor(BLUE if selected else LINE)
        pdf.roundRect(x, y_top - 33, 135, 25, 6, fill=1, stroke=1)
        pdf.setFillColor(white if selected else TEXT)
        pdf.setFont(BOLD if selected else FONT, 8)
        pdf.drawCentredString(x + 67.5, y_top - 24, label)
        x += 145
    return y_top - 54


def page_one(pdf: canvas.Canvas) -> None:
    pdf.setFillColor(NAVY)
    pdf.setFont(BOLD, 29)
    pdf.drawCentredString(PAGE_WIDTH / 2, 690, "写真まとめて整理")
    pdf.setFont(BOLD, 24)
    pdf.drawCentredString(PAGE_WIDTH / 2, 642, "かんたん操作ガイド")
    paragraph(
        pdf,
        "写真の圧縮・JPEG変換と、撮影日時によるファイル名整理を、ひとつの画面で安全に行えます。",
        90,
        590,
        PAGE_WIDTH - 180,
        size=11,
        leading=18,
        color=MUTED,
    )
    y = info_box(
        pdf,
        "圧縮・JPEG変換",
        "HEICなどの写真を、小さなJPEGへまとめて変換します。初期設定は幅・高さ20%、品質80です。",
        520,
        height=78,
    )
    y = info_box(
        pdf,
        "撮影日時で名前を整理",
        "Jpegrm V4の標準名を引き継ぎ、メーカー名・機種名・自由入力などの部品を好きな順番へ動かせます。実行前に新しい名前を一覧で確認できます。",
        y,
        fill=PALE_GREEN,
        stroke=GREEN,
        title_color=GREEN,
        height=88,
    )
    y = info_box(
        pdf,
        "元の写真を残す方法・直接変更する方法",
        "通常は converted へ保存し、元の写真を残します。元の場所で上書き・名前変更するボタンもあります（6ページ）。",
        y,
        fill=PALE_ORANGE,
        stroke=ORANGE,
        title_color=ORANGE,
        height=78,
    )
    pdf.setFillColor(NAVY)
    pdf.setFont(BOLD, 12)
    pdf.drawString(LEFT, y - 6, "用意するもの")
    y -= 28
    for text in (
        "Windowsパソコン",
        "処理したい写真が入ったフォルダ",
        "配布された ImageCompressor.exe",
    ):
        y = bullet(pdf, text, y) - 4
    paragraph(
        pdf,
        "最初は、数枚の写真で試すことをおすすめします。",
        145,
        95,
        PAGE_WIDTH - 290,
        size=10,
        color=MUTED,
    )


def page_two(pdf: canvas.Canvas) -> None:
    y = page_title(pdf, "1", "アプリを使えるようにする")
    y = paragraph(
        pdf,
        "特別なインストール作業はありません。配布されたZIPファイルを展開して、アプリを開くだけです。",
        LEFT,
        y,
        CONTENT_WIDTH,
        size=10.5,
        leading=16,
    ) - 12
    y = step_card(
        pdf,
        1,
        "ダウンロードしたZIPファイルを探す",
        "通常は「ダウンロード」フォルダにあります。ファイル名は ImageCompressor-windows.zip です。",
        y,
    )
    y = step_card(
        pdf,
        2,
        "ZIPファイルを展開する",
        "ZIPを右クリックし、「すべて展開」を選びます。表示された画面で「展開」を押します。",
        y,
    )
    y = step_card(
        pdf,
        3,
        "アプリを開く",
        "展開したフォルダの ImageCompressor.exe をダブルクリックします。追加のソフトは不要です。",
        y,
    )
    y = info_box(
        pdf,
        "青い警告画面が出たとき",
        "配布元が正しいことを確認してから、「詳細情報」→「実行」の順に押します。不明な場所から入手したファイルは実行しないでください。",
        y - 5,
        fill=PALE_ORANGE,
        stroke=ORANGE,
        title_color=ORANGE,
        height=82,
    )
    pdf.setFillColor(NAVY)
    pdf.setFont(BOLD, 12)
    pdf.drawString(LEFT, y - 2, "覚えておくこと")
    y -= 24
    for text in (
        "使うたびに ImageCompressor.exe をダブルクリックします。",
        "Python、uv、ImageMagickなどを入れる必要はありません。",
        "削除するときは、展開したフォルダを削除するだけです。",
    ):
        y = bullet(pdf, text, y) - 3


def page_three(pdf: canvas.Canvas) -> None:
    y = page_title(pdf, "2", "写真をまとめて圧縮・変換する")
    y = draw_mode_switch(pdf, y, rename=False)
    rounded_box(pdf, LEFT, y, CONTENT_WIDTH, 190, fill=PANEL, stroke=LINE)
    pdf.setFillColor(NAVY)
    pdf.setFont(BOLD, 12)
    pdf.drawString(LEFT + 18, y - 25, "圧縮・JPEG変換")
    rounded_box(
        pdf, LEFT + 18, y - 42, CONTENT_WIDTH - 36, 42, fill=PALE_BLUE, stroke=BLUE
    )
    pdf.setFont(BOLD, 9)
    pdf.setFillColor(NAVY)
    pdf.drawCentredString(PAGE_WIDTH / 2, y - 68, "ここに写真またはフォルダをドロップ")
    pdf.setFont(FONT, 8)
    pdf.drawString(LEFT + 20, y - 107, "保存先　C:\\Users\\...\\Pictures\\converted")
    pdf.drawString(LEFT + 20, y - 135, "画像サイズ　20%　　　　　JPEG品質　80")
    pdf.drawString(LEFT + 20, y - 161, "□ ファイル容量を指定する（必要な場合のみ）")
    y -= 210
    y = step_card(
        pdf,
        1,
        "写真を選択、またはドロップする",
        "一覧に写真が表示されます。クリックで拡大し、チェックした写真だけを処理します。予想サイズは「サイズを計算」を押したときだけ計算します。",
        y,
        height=65,
    )
    y = step_card(
        pdf,
        2,
        "保存先を確認する",
        "自動で converted が入ります。通常はそのままでかまいません。",
        y,
        height=65,
    )
    y = step_card(
        pdf,
        3,
        "「○枚を元を残して変換」を押す",
        "初期設定は20%、品質80です。処理後は「保存先を開く」でJPEGを確認します。",
        y,
        height=70,
    )
    info_box(
        pdf,
        "写真の向きと位置情報",
        "向きは正しく補正します。GPSなどの撮影情報は、変換後のJPEGには含めません。",
        y - 2,
        fill=PALE_GREEN,
        stroke=GREEN,
        title_color=GREEN,
        height=68,
    )


def page_four(pdf: canvas.Canvas) -> None:
    y = page_title(pdf, "3", "撮影日時でファイル名を整理する")
    y = draw_mode_switch(pdf, y, rename=True)
    rounded_box(pdf, LEFT, y, CONTENT_WIDTH, 218, fill=PANEL, stroke=LINE)
    x = LEFT + 16
    pdf.setFillColor(NAVY)
    pdf.setFont(BOLD, 9)
    pdf.drawString(x, y - 22, "新しいファイル名を、左から順に組み立てます")
    chip_y = y - 36
    chips = [
        ("撮影日時（標準）\n2025_10_17_1117", 150, True),
        ("連番（必須）\n00", 80, False),
        (".jpg", 54, False),
    ]
    chip_x = x
    for index, (label, width, selected) in enumerate(chips):
        rounded_box(
            pdf,
            chip_x,
            chip_y,
            width,
            45,
            fill=BLUE if selected else white,
            stroke=BLUE if selected else LINE,
            radius=4,
        )
        lines = label.split("\n")
        pdf.setFillColor(white if selected else TEXT)
        pdf.setFont(BOLD, 7.5)
        pdf.drawCentredString(chip_x + width / 2, chip_y - 17, lines[0])
        if len(lines) > 1:
            pdf.setFont(FONT, 7)
            pdf.drawCentredString(chip_x + width / 2, chip_y - 33, lines[1])
        chip_x += width
        if index < len(chips) - 1:
            pdf.setFillColor(MUTED)
            pdf.setFont(BOLD, 9)
            pdf.drawCentredString(chip_x + 12, chip_y - 27, "＋")
            chip_x += 24
    pdf.setFillColor(MUTED)
    pdf.setFont(FONT, 7.5)
    pdf.drawString(x, y - 96, "部品をクリックして選択。横にドラッグして移動できます。")
    action_x = x + 210
    for label, width in (("← 左へ", 62), ("右へ →", 62), ("選択した部品を外す", 116)):
        rounded_box(
            pdf, action_x, y - 81, width, 23, fill=white, stroke=LINE, radius=4
        )
        pdf.setFillColor(TEXT)
        pdf.setFont(FONT, 7)
        pdf.drawCentredString(action_x + width / 2, y - 96, label)
        action_x += width + 5
    pdf.setFillColor(NAVY)
    pdf.setFont(BOLD, 9)
    pdf.drawString(x, y - 128, "部品を追加")
    button_x = x + 74
    for label in ("＋ メーカー名", "＋ 機種名", "＋ 自由入力"):
        rounded_box(pdf, button_x, y - 114, 92, 24, fill=white, stroke=LINE, radius=4)
        pdf.setFillColor(TEXT)
        pdf.setFont(FONT, 7.5)
        pdf.drawCentredString(button_x + 46, y - 130, label)
        button_x += 98
    pdf.setFillColor(BLUE)
    pdf.setFont(BOLD, 8)
    pdf.drawString(
        x,
        y - 172,
        "仕上がり例  IMG_1001.JPG → 2025_10_17_1117_00.jpg",
    )
    pdf.setFillColor(MUTED)
    pdf.setFont(FONT, 7.5)
    pdf.drawString(
        x,
        y - 198,
        "撮影日時の形式は、Jpegrm V4と同じ YYYY_MM_DD_HHMM です。",
    )
    y -= 237
    y = step_card(
        pdf,
        1,
        "JPEGまたはフォルダを選ぶ",
        "新しい名前とスキップ理由が、実行前に一覧表示されます。",
        y,
        height=61,
    )
    y = step_card(
        pdf,
        2,
        "部品を追加し、横の順番を選ぶ",
        "標準はV4と同じ「撮影日時 → 連番」です。自由入力も好きな位置へ動かせます。",
        y,
        height=68,
    )
    y = step_card(
        pdf,
        3,
        "「○枚を別名でコピー」を押す",
        "確認画面の後、converted へコピーします。元のJPEG名は変わりません。",
        y,
        height=65,
    )
    info_box(
        pdf,
        "サブフォルダも含める場合",
        "初期状態はOFFです。ONにすると、converted 内にも元のフォルダ構成を保ちます。converted 自体は再走査しません。",
        y - 2,
        fill=PALE_ORANGE,
        stroke=ORANGE,
        title_color=ORANGE,
        height=68,
    )


def page_five(pdf: canvas.Canvas) -> None:
    y = page_title(pdf, "4", "結果を確認する・困ったとき")
    y = info_box(
        pdf,
        "元の写真を残すボタンを使った場合",
        "結果は converted フォルダへ保存されます。確認が終わるまで、元の写真は削除しないでください。",
        y,
        fill=PALE_GREEN,
        stroke=GREEN,
        title_color=GREEN,
        height=74,
    )
    topics = [
        (
            "「対応する写真が見つかりません」と表示される",
            "写真があるフォルダを選び直します。名前整理ではJPEGだけが対象です。下のフォルダも探す場合は「サブフォルダも含める」をONにします。",
        ),
        (
            "「変更できません」と表示される",
            "EXIFなし、撮影日時なし、読み込み不能などの理由を一覧で確認できます。スキップした写真はコピーされません。",
        ),
        (
            "同じ名前のファイルがすでにある",
            "コピーでは連番を進めます。直接変換で同名の別JPEGがある場合は、その写真を変更せずエラーにします。",
        ),
        (
            "途中で止めたい",
            "「中止」を押すと、次の写真から処理を止めます。完了した保存・上書き・名前変更は取り消されません。",
        ),
    ]
    for title, body in topics:
        pdf.setFillColor(NAVY)
        pdf.setFont(BOLD, 11)
        pdf.drawString(LEFT, y, title)
        y = paragraph(
            pdf,
            body,
            LEFT,
            y - 22,
            CONTENT_WIDTH,
            size=9,
            leading=14,
        ) - 13
    info_box(
        pdf,
        "解決しないとき",
        "右上の「ヘルプ」でバージョンを確認し、一覧のエラー内容と写真のファイル名をお知らせください。ヘルプ内のタブで操作手順も読めます。",
        y,
        fill=PALE_RED,
        stroke=RED,
        title_color=RED,
        height=78,
    )


def page_six(pdf: canvas.Canvas) -> None:
    y = page_title(pdf, "5", "選んだ写真を元の場所で変更する")
    y = info_box(
        pdf, "チェックした写真だけが処理対象です",
        "一覧に小さな写真が常に表示され、クリックすると右側で大きく見られます。不要な写真はチェックを外します。行は薄い色で残り、再チェックで対象に戻せます。写真を見るだけではチェックは変わりません。",
        y, height=92,
    )
    y = step_card(
        pdf, 1, "写真と設定を確認する",
        "処理対象の枚数と一覧を確認します。圧縮の設定、または名前の部品・自由入力を整えます。",
        y, height=72,
    )
    y = step_card(
        pdf, 2, "元の場所で変更するボタンを押す",
        "圧縮では「○枚を上書き変換…」、名前整理では「○枚の名前を変更…」を押します。converted は使いません。",
        y, height=78,
    )
    y = step_card(
        pdf, 3, "確認画面の一覧を見て実行する",
        "元の場所と変更後の名前を確認します。取りやめる場合は「キャンセル」。完了後はチェックが解除されます。続ける写真に再びチェックを入れてください。",
        y, height=78,
    )
    y = info_box(
        pdf, "上書き変換は元に戻せません",
        "JPEGは元の名前のまま上書きします。HEIC・PNGなどは同じ場所へJPEGを保存した後、元ファイルを削除します。撮影日時・GPSなどのEXIF情報も除去されます。同名の別JPEGがある場合は元画像を残し、エラーを表示します。",
        y, fill=PALE_ORANGE, stroke=ORANGE, title_color=ORANGE, height=116,
    )
    info_box(
        pdf, "名前変更では、画像の内容・撮影情報は変わりません",
        "元のフォルダ内で名前だけ変えます。既存ファイルを避けて連番を決めるため、コピー用のプレビューと異なる場合があります。確認画面の名前が実際の変更内容です。撮影日時のないJPEGはスキップします。",
        y, fill=PALE_GREEN, stroke=GREEN, title_color=GREEN, height=100,
    )


def generate() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(OUTPUT), pagesize=A4, pageCompression=1)
    pdf.setTitle("写真まとめて整理 かんたん操作ガイド")
    pages = (page_one, page_two, page_three, page_four, page_five, page_six)
    for page_number, draw_page in enumerate(pages, start=1):
        draw_page(pdf)
        footer(pdf, page_number)
        pdf.showPage()
    pdf.save()
    print(OUTPUT)


if __name__ == "__main__":
    generate()
