#!/usr/bin/env python3
"""CSV と JSON が同じことを言っているかを確かめる。

標準ライブラリのみ。data/ の中で `python3 check.py` として実行する。

確かめること
  1. 件数が一致する
  2. 全列・全行が一致する
  3. 假記番号が 2603-18 から 2603-27 まで欠けも重複もなく並ぶ
  4. entry_marker が「最初の一件だけ假記、以降は同」になっている
  5. rank_source が printed の行より前に ditto の行が来ていない
     （引き継ぐ元がない ditto は、翻刻の取りこぼしを意味する）
  6. ditto の行の階級が、直前の printed 行と同じ
  7. 論文が確定させた大谷（2603-25）の階級が、この連鎖から実際に導ける
  8. 出典表記が、リポジトリ内の四箇所で一字一句同じ
  9. 原資料のスキャン画像が混入していない

出典表記はアジア歴史資料センターの規定する形式です。同じ文字列を README・データ辞書・
JSON・CITATION.cff に置いているので、片方だけ直すと食い違います。8 はそれを防ぎます。

9 は運用上の線です。JACAR の案内では、防衛省防衛研究所提供資料の「資料画像」を出版物等に
用いる場合、所蔵機関への照会が求められます。このリポジトリはテキストの翻刻と自作の論文
だけを収めており、原画像は含みません。画像を加えるなら、その前に防衛研究所戦史研究センター
への確認が要ります。9 は、確認しないまま画像が入ってしまうことを防ぎます。
"""

import csv
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
COLUMNS = [
    "entry_no", "entry_marker", "rank_ja", "rank_en", "rank_source",
    "name_as_printed", "surname", "given_name", "subheading_ja",
    "order_class", "decoration",
]

failures = []


def check(label, ok, detail=""):
    print(("  OK   " if ok else "  FAIL ") + label + (" — " + detail if detail else ""))
    if not ok:
        failures.append(label)


with open(os.path.join(HERE, "investiture-1943-09-11.csv"), encoding="utf-8") as fh:
    rows = list(csv.DictReader(fh))

with open(os.path.join(HERE, "investiture-1943-09-11.json"), encoding="utf-8") as fh:
    doc = json.load(fh)
entries = doc["entries"]

print("1. 件数")
check("CSV と JSON の件数が一致する", len(rows) == len(entries),
      "CSV %d / JSON %d" % (len(rows), len(entries)))
check("JSON の scope が申告する件数と一致する",
      doc["scope"]["entries_transcribed"] == len(entries),
      "申告 %d / 実際 %d" % (doc["scope"]["entries_transcribed"], len(entries)))

print("2. 内容")
diffs = []
for row, entry in zip(rows, entries):
    for col in COLUMNS:
        a = row[col]
        b = entry[col]
        b = "" if b is None else b
        if a != b:
            diffs.append("%s.%s: CSV %r / JSON %r" % (row["entry_no"], col, a, b))
check("全列が一致する", not diffs, "; ".join(diffs) if diffs else "%d 行 × %d 列" % (len(rows), len(COLUMNS)))

print("3. 假記番号")
nums = [int(r["entry_no"].split("-")[1]) for r in rows]
check("2603-18 から連番で欠けがない", nums == list(range(18, 18 + len(nums))),
      "%d – %d" % (nums[0], nums[-1]))
check("重複がない", len(set(nums)) == len(nums))

print("4. 番号欄の繰り返し記号")
markers = [r["entry_marker"] for r in rows]
check("最初の一件が 假記", markers[0] == "假記", markers[0])
check("以降はすべて 同", set(markers[1:]) == {"同"}, "".join(markers[1:]))

print("5–6. 階級の引き継ぎ")
carried = None
bad_order = []
bad_carry = []
for row in rows:
    if row["rank_source"] == "printed":
        carried = row["rank_ja"]
    elif row["rank_source"] == "ditto":
        if carried is None:
            bad_order.append(row["entry_no"])
        elif row["rank_ja"] != carried:
            bad_carry.append("%s: %s ≠ %s" % (row["entry_no"], row["rank_ja"], carried))
    else:
        bad_order.append("%s: 未知の rank_source %r" % (row["entry_no"], row["rank_source"]))
check("引き継ぐ元のない ditto がない", not bad_order, "; ".join(map(str, bad_order)))
check("ditto の階級が直前の printed と一致する", not bad_carry, "; ".join(bad_carry))

print("7. 大谷（2603-25）の階級")
otani = next(r for r in rows if r["entry_no"] == "2603-25")
# 論文第4節(1) の推論をそのまま辿る: 2603-25 から上へ遡り、最初に見つかる printed 行を採る。
source = None
for row in reversed(rows[: rows.index(otani) + 1]):
    if row["rank_source"] == "printed":
        source = row
        break
check("上へ遡ると階級の書かれた行に行き着く", source is not None,
      source["entry_no"] if source else "見つからない")
check("その行の階級が 海軍大尉", source is not None and source["rank_ja"] == "海軍大尉",
      "%s の %s" % (source["entry_no"], source["rank_ja"]) if source else "")
check("大谷の行に展開された階級と一致する",
      source is not None and otani["rank_ja"] == source["rank_ja"],
      otani["rank_ja"])
check("したがって 海軍少佐 ではない", otani["rank_ja"] != "海軍少佐", otani["rank_ja"])

print("8. 出典表記")
CITATION = ("JACAR（アジア歴史資料センター）Ref.C12070491000、"
            "海軍公報（部内限）號外　昭和十八年九月十一日發令（防衛省防衛研究所）")
ROOT = os.path.dirname(HERE)

check("JSON の source.citation が規定形式と一致する",
      doc["source"]["citation"] == CITATION,
      doc["source"]["citation"])

for label, path in (("README.md", os.path.join(ROOT, "README.md")),
                    ("data/README.md", os.path.join(HERE, "README.md")),
                    ("CITATION.cff", os.path.join(ROOT, "CITATION.cff"))):
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    check("%s に同じ出典表記がある" % label, CITATION in text)

check("レコードの恒久リンクが das/meta 形式",
      doc["source"]["jacar_permalink"]
      == "https://www.jacar.archives.go.jp/das/meta/C12070491000",
      doc["source"]["jacar_permalink"])

# 画像ビューアの URL（listPhoto）は恒久リンクではないので、どこにも残っていないこと。
stale = []
for dirpath, dirnames, filenames in os.walk(ROOT):
    dirnames[:] = [d for d in dirnames if d not in (".git", "pdf")]
    for name in filenames:
        if not name.endswith((".md", ".json", ".cff", ".py")):
            continue
        full = os.path.join(dirpath, name)
        with open(full, encoding="utf-8") as fh:
            if "listPhoto" in fh.read() and os.path.abspath(full) != os.path.abspath(__file__):
                stale.append(os.path.relpath(full, ROOT))
check("恒久リンクでない listPhoto 形式の URL が残っていない", not stale, ", ".join(stale))

print("9. 原資料の画像")
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".tif", ".tiff",
              ".bmp", ".webp", ".jp2", ".heic")
found_images = []
for dirpath, dirnames, filenames in os.walk(ROOT):
    dirnames[:] = [d for d in dirnames if d != ".git"]
    for name in filenames:
        if name.lower().endswith(IMAGE_EXTS):
            found_images.append(os.path.relpath(os.path.join(dirpath, name), ROOT))
check("画像ファイルが置かれていない", not found_images, ", ".join(found_images))

# PDF に画像が埋め込まれていないか。PDF ライブラリを持ち込まないので、オブジェクト辞書の
# バイト列を直接見る。辞書は圧縮されないのが通例なので実用上これで captures できるが、
# オブジェクトストリームに入れられた場合は見逃す。厳密な証明ではなく、うっかりを止める柵。
pdf_with_images = []
pdf_dir = os.path.join(ROOT, "pdf")
if os.path.isdir(pdf_dir):
    for name in sorted(os.listdir(pdf_dir)):
        if not name.lower().endswith(".pdf"):
            continue
        with open(os.path.join(pdf_dir, name), "rb") as fh:
            raw = fh.read()
        if b"/Subtype/Image" in raw or b"/Subtype /Image" in raw:
            pdf_with_images.append(name)
check("PDF に画像が埋め込まれていない（辞書のバイト列走査）",
      not pdf_with_images, ", ".join(pdf_with_images))

print()
if failures:
    print("%d 項目が通りませんでした。" % len(failures))
    for f in failures:
        print("  - " + f)
    sys.exit(1)
print("すべて通りました。")
