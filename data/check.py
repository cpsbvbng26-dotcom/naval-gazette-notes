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
 10. README の「史料の外にあるもの」が、報道と家伝を史料と混ぜていない
 12. 種類と状態の札、CITATION.cff の type、Zenodo の関連する識別子が食い違っていない
 13. datapackage.json の列・型・制約・出典が、実際の CSV に合う
 14. 使い方の例が、データ辞書の写しと同じで、走らせた結果が CSV と合う
 15. 「このデータを使った」の issue の様式があり、連絡先を求めていない
 16. 典拠の所在の表が、リポジトリに現れる参照コードを過不足なく挙げる
 17. 年表の日付が、リポジトリのほかの箇所にすでに書いてある
 18. 読む順と、存命の人を書き足さない線が、頁の冒頭にある
 19. README の「検査の結果」と CI の題の、正誤表の監査の数が、走らせた数と合う
 11. README が名乗る項目数が、実際に確かめた数と合う（最後に数える）

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
checked = []


def check(label, ok, detail=""):
    print(("  OK   " if ok else "  FAIL ") + label + (" — " + detail if detail else ""))
    checked.append(label)
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

CITATION_FILES = (("README.md", os.path.join(ROOT, "README.md")),
                  ("data/README.md", os.path.join(HERE, "README.md")),
                  ("CITATION.cff", os.path.join(ROOT, "CITATION.cff")))
for label, path in CITATION_FILES:
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    check("%s に同じ出典表記がある" % label, CITATION in text)

# 散文が名乗る箇所の数（「五箇所」）が、ここで確かめている数と合うこと。
# 一度、README が「三箇所」と書いたまま data/README.md が足されていた。見出しの行は数えない。
import re
KANJI = "〇一二三四五六七八九"
with open(os.path.join(HERE, "datapackage.json"), encoding="utf-8") as fh:
    pkg = json.load(fh)
check("datapackage.json の sources に同じ出典表記がある",
      [x.get("title") for x in pkg.get("sources", [])][:1] == [CITATION])
places = 2 + len(CITATION_FILES)      # JSON の source.citation と datapackage.json と上の三つ
said = []
for label, path in CITATION_FILES[:2]:
    with open(path, encoding="utf-8") as fh:
        prose = "\n".join(l for l in fh.read().splitlines() if not l.startswith("#"))
    said += ["%s: %s箇所" % (label, n) for n in re.findall(r"([一二三四五六七八九])箇所", prose)]
check("散文が名乗る出典表記の箇所の数が、確かめている数（%s箇所）と合う" % KANJI[places],
      bool(said) and all(s.endswith(KANJI[places] + "箇所") for s in said),
      " / ".join(said) if said else "名乗りが無い")

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

print("10. 史料の外にあるもの")
# 家に伝わることと、家にあった物は、史料に当たっていない。確かめたことと同じ書き方を
# しないよう、節を分けている。分けたことを、ここで固める。
import re
with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as fh:
    readme = fh.read()
m = re.search(r"^## 史料の外にあるもの\n(.*?)(?=^## )", readme, re.S | re.M)
outside = m.group(1) if m else ""
check("README に「史料の外にあるもの」の節がある", bool(outside))
check("その節が、どれも一次史料に当たっていないと書いている",
      "どれも一次史料には当たっていません" in outside)

# 報道で分かったことは、行ごとに根拠を持つ。根拠の欄が空の行は、出どころの無い事実になる。
news = re.search(r"### 報道と照会で分かったこと\n(.*?)(?=^### |\Z)", outside, re.S | re.M)
news_text = news.group(1) if news else ""
news_rows = [r for r in re.findall(r"^\| ([^|]+?) \| ([^|]+?) \| ([^|]*?) \|$", news_text, re.M)
             if r[0] not in ("事項", "---")]
check("報道の表の全行に根拠がある",
      bool(news_rows) and all(r[2].strip() for r in news_rows),
      "%d 行" % len(news_rows) if news_rows else "表が読めない")

# 少佐は報道の側へ移した。家伝の側にも残すと、根拠が二つあるように読める。
lore = re.search(r"### 家伝\n(.*?)(?=^### |\Z)", outside, re.S | re.M)
check("最終階級が、家伝と報道の両方に置かれていない",
      bool(lore) and "少佐" not in lore.group(1) and any(r[0] == "最終階級" for r in news_rows))

# 一覧に、公報が記録する大谷の勲章が入っていないこと。入っていないと散文に書いているので、
# 表とデータの両方から確かめる。等級と勲章は JSON の大谷の行から取る。
held = re.search(r"### 親族の家にあった勲章と記章\n(.*?)(?=^### |\Z)", outside, re.S | re.M)
held_rows = re.findall(r"^\| ([^|]+?) \| \d+ \|$", held.group(1) if held else "", re.M)
recorded = otani["order_class"] + otani["decoration"]          # 四等瑞寶章
recorded_modern = "勲" + otani["order_class"] + otani["decoration"].replace("寶", "宝")
check("一覧に、公報が記録する大谷の勲章（%s）が入っていない" % recorded,
      bool(held_rows) and all(recorded_modern not in r and recorded not in r for r in held_rows),
      " / ".join(held_rows) if held_rows else "一覧が読めない")

# 存命の人は「両親」という語まで（CLAUDE.md の決めごと 10）。家の物の話は、
# 誰か一人を指す語に寄りやすい。節の中に、それを置かない。
check("その節に、存命の誰か一人を指す語（父・母）が無い",
      bool(outside) and not re.search(r"[父母]", outside.replace("祖父", "")),
      "".join(sorted(set(re.findall(r".?[父母].?", outside)))))


print("12. 種類と状態の札")
LABEL_LINE = "種類：史料研究・事例研究　状態：凍結"
lines = readme.splitlines()
first = next((l for l in lines[1:] if l.strip()), "")
check("README の題のすぐ下に、種類と状態の札がある",
      lines[:1] == ["# Naval Gazette Notes"] and first == LABEL_LINE, first)
with open(os.path.join(ROOT, "CITATION.cff"), encoding="utf-8") as fh:
    cff = fh.read()
with open(os.path.join(ROOT, ".zenodo.json"), encoding="utf-8") as fh:
    zen = json.load(fh)
check("CITATION.cff の type が dataset", re.search(r"^type: dataset$", cff, re.M) is not None)
check(".zenodo.json の upload_type が dataset", zen.get("upload_type") == "dataset")
rel = {(r.get("relation"), r.get("identifier")) for r in zen.get("related_identifiers", [])}
note_doi = re.search(r"^    doi: (10\.\S+)$", cff, re.M)
check("Zenodo の記録が、史料ノートの DOI に isSupplementTo でつながる",
      note_doi is not None and ("isSupplementTo", note_doi.group(1)) in rel,
      note_doi.group(1) if note_doi else "CITATION.cff に史料ノートの DOI が無い")
check("Zenodo の記録が、JACAR のレコードに isDerivedFrom でつながる",
      ("isDerivedFrom", doc["source"]["jacar_permalink"]) in rel)
check("関連する識別子の種類が、isSupplementTo と isDerivedFrom の二つに限られる",
      {r for r, _ in rel} <= {"isSupplementTo", "isDerivedFrom"}, ", ".join(sorted({r for r, _ in rel})))

print("13. datapackage.json")
res = {r.get("name"): r for r in pkg.get("resources", [])}
tab = res.get("investiture-csv", {})
fields = tab.get("schema", {}).get("fields", [])
with open(os.path.join(HERE, "investiture-1943-09-11.csv"), encoding="utf-8") as fh:
    header = next(csv.reader(fh))
check("datapackage.json の列が、CSV の列と check.py の列と同じ順で並ぶ",
      [f.get("name") for f in fields] == header == COLUMNS, "%d 列" % len(fields))
check("datapackage.json の資源が、実在する CSV と JSON を指す",
      tab.get("path") == "investiture-1943-09-11.csv"
      and res.get("investiture-json", {}).get("path") == "investiture-1943-09-11.json"
      and all(os.path.exists(os.path.join(HERE, r.get("path", ""))) for r in res.values()))
bad = []
for f in fields:
    n, c = f.get("name"), f.get("constraints", {})
    vals = [r[n] for r in rows]
    filled = [v for v in vals if v != ""]
    if c.get("required") and len(filled) != len(vals):
        bad.append("%s: 空欄" % n)
    if c.get("unique") and len(set(filled)) != len(filled):
        bad.append("%s: 重複" % n)
    if "pattern" in c and any(not re.fullmatch(c["pattern"], v) for v in filled):
        bad.append("%s: 形が合わない" % n)
    if "enum" in c and not set(filled) <= set(c["enum"]):
        bad.append("%s: 表に無い値 %s" % (n, sorted(set(filled) - set(c["enum"]))))
check("datapackage.json の制約を、CSV の全行が満たす", not bad, "; ".join(bad))
enum = {f["name"]: f.get("constraints", {}).get("enum") for f in fields}
check("rank_source の値の表が、printed と ditto の二つ", enum.get("rank_source") == ["printed", "ditto"])
check("datapackage.json の主キーが entry_no", tab.get("schema", {}).get("primaryKey") == "entry_no")
check("datapackage.json のライセンスが CITATION.cff と同じ（CC-BY-4.0）",
      [l.get("name") for l in pkg.get("licenses", [])] == ["CC-BY-4.0"]
      and re.search(r"^license: CC-BY-4.0$", cff, re.M) is not None)
check("datapackage.json の出典の所在が、JACAR の恒久リンク",
      [x.get("path") for x in pkg.get("sources", [])][:1] == [doc["source"]["jacar_permalink"]])

print("14. 使い方の例")
import subprocess
with open(os.path.join(HERE, "example.py"), encoding="utf-8") as fh:
    example = fh.read()
with open(os.path.join(HERE, "README.md"), encoding="utf-8") as fh:
    dic = fh.read()
m = re.search(r"^## 使い方の例\n.*?^```python\n(.*?)^```$", dic, re.S | re.M)
check("データ辞書の例が data/example.py と一字一句同じ", m is not None and m.group(1) == example)
try:
    out = subprocess.run([sys.executable, os.path.join(HERE, "example.py")],
                         capture_output=True, text=True, timeout=60)
    ran, got = out.returncode == 0, out.stdout.splitlines()
except Exception as exc:                                    # noqa: BLE001
    ran, got = False, [str(exc)]
check("data/example.py が走る", ran)
want = {"全件 %d" % len(rows),
        "%s %s %s %s" % (otani["entry_no"], otani["name_as_printed"],
                         otani["rank_ja"], otani["rank_source"])}
for col in ("rank_ja", "rank_source"):
    for v in set(r[col] for r in rows):
        want.add("%s %d" % (v, sum(r[col] == v for r in rows)))
check("data/example.py の出力が、CSV の中身と合う", set(got) == want, " / ".join(got))

print("15. 使ったことを知らせる窓口")
tpath = os.path.join(ROOT, ".github", "ISSUE_TEMPLATE", "used-this-data.yml")
tmpl = open(tpath, encoding="utf-8").read() if os.path.exists(tpath) else None
check("「このデータを使った」の issue の様式があり、README がつないでいる",
      tmpl is not None and "name: このデータを使った" in tmpl
      and "template=used-this-data.yml" in readme)
check("その様式が連絡先を求めていない",
      tmpl is not None and not re.search(r"(?i)e-?mail|メール|電話|住所", tmpl))

print("16. 典拠の所在")
src = re.search(r"^## 典拠の所在\n(.*?)(?=^## )", readme, re.S | re.M)
src_text = src.group(1) if src else ""
listed = re.findall(r"^\| [^|]+ \| JACAR Ref\.(C\d{11}) \|", src_text, re.M)
seen = set()
for dirpath, dirnames, filenames in os.walk(ROOT):
    dirnames[:] = [d for d in dirnames if d not in (".git", "pdf", "__pycache__")]
    for name in filenames:
        if name.endswith((".md", ".json", ".cff", ".py", ".toml", ".yml")):
            with open(os.path.join(dirpath, name), encoding="utf-8") as fh:
                seen |= set(re.findall(r"(?<![0-9A-Za-z])(C\d{11})(?!\d)", fh.read()))
check("リポジトリに現れる JACAR の参照コードが、すべて典拠の表にある",
      bool(listed) and seen == set(listed),
      "表 %s / リポジトリ %s" % (sorted(listed), sorted(seen)))
m = re.search(r"参照コードを持つ典拠は(.)件です", src_text)
check("散文が名乗る典拠の件数が、表の行数と合う",
      m is not None and m.group(1) == KANJI[len(listed)],
      "名乗り %s / 表 %d 行" % (m.group(1) if m else "無い", len(listed)))
check("典拠の表が、簿冊名と整理番号を未確認と書き、課題につないでいる",
      "未確認（[#26](https://github.com/cpsbvbng26-dotcom/naval-gazette-notes/issues/26)）" in src_text)

print("17. 年表")
tl = re.search(r"^## 年表\n(.*?)(?=^## )", readme, re.S | re.M)
tl_text = tl.group(1) if tl else ""
others = readme.replace(tl_text, "")
for dirpath, dirnames, filenames in os.walk(ROOT):
    dirnames[:] = [d for d in dirnames if d not in (".git", "pdf", "__pycache__")]
    for name in filenames:
        full = os.path.join(dirpath, name)
        if name.endswith((".md", ".json", ".cff")) and os.path.relpath(full, ROOT) != "README.md":
            with open(full, encoding="utf-8") as fh:
                others += fh.read()
missing, n_dates = [], 0
for cell in re.findall(r"^\| ([^|]+?) \| [^|]+ \| [^|]+ \|$", tl_text, re.M):
    if cell in ("日付", "---"):
        continue
    d = re.match(r"(\d{4})年(?:(\d+)月)?(?:(\d+)日)?", cell)
    if not d:
        missing.append(cell)
        continue
    n_dates += 1
    y, mo, da = d.groups()
    forms = {d.group(0)}
    if mo:
        iso = "%s-%02d" % (y, int(mo)) + ("-%02d" % int(da) if da else "")
        forms.add(iso)
    if not any(f in others for f in forms):
        missing.append(cell)
check("年表の日付が、すべてリポジトリのほかの箇所にすでにある",
      n_dates > 0 and not missing, ", ".join(missing) or "%d 行" % n_dates)

print("18. 読む順と、扱う人")
heads = re.findall(r"^## (.+)$", readme, re.M)
check("「読む順」と「扱う人」が、史料ノートの節より前にある",
      "読む順" in heads and "扱う人" in heads and "史料ノート" in heads
      and heads.index("読む順") < heads.index("史料ノート")
      and heads.index("扱う人") < heads.index("史料ノート"))
check("README とデータ辞書が、存命の人を書き足さないと述べている",
      "このリポジトリは、著者のほかに存命の人を書き足しません。" in readme
      and "存命の人を書き足すことはしません。" in dic)
check("README とデータ辞書が、大谷恒のほかの受章者の生没を確かめていないと述べている",
      "大谷恒のほかの受章者の生没は、確かめていません。" in readme
      and "大谷恒のほかの受章者の生没は、確かめていません。" in dic)

print("19. 検査の結果")
try:
    out = subprocess.run([sys.executable, os.path.join(ROOT, "verification", "check_errata.py")],
                         capture_output=True, text=True, timeout=600, cwd=ROOT)
    m = re.search(r"(\d+) 件すべて通りました。", out.stdout)
    n_errata = int(m.group(1)) if m else None
    why = "" if m else (out.stderr.strip().splitlines() or ["出力に数が無い"])[-1]
except Exception as exc:                                    # noqa: BLE001
    n_errata, why = None, str(exc)
m = re.search(r"^\| `verification/check_errata\.py` \| (\d+) \| すべて通る \|$", readme, re.M)
# CI の題も同じ数を名乗る。項目を増やさず、ここに畳む（data/check.py の数は README と他の頁が名乗っている）。
with open(os.path.join(ROOT, ".github", "workflows", "verify.yml"), encoding="utf-8") as fh:
    ci = [int(x) for x in re.findall(r"正誤表の監査 (\d+) 項目", fh.read())]
said_errata = ([int(m.group(1))] if m else []) + ci
check("README の表と CI の題の check_errata.py の数が、走らせた数と合う（pypdf が要る）",
      m is not None and len(ci) > 0 and n_errata is not None and set(said_errata) == {n_errata},
      "名乗り %s / 実際 %s %s" % (",".join(map(str, said_errata)) or "無い", n_errata, why))

print("11. 名乗る項目数")
claimed = re.search(r"(\d+) 項目を確かめます", readme)
total = len(checked) + 1
table = re.search(r"^\| `data/check\.py` \| (\d+) \| すべて通る \|$", readme, re.M)
check("README が名乗る項目数が実際と合う（散文と、検査の結果の表）",
      claimed is not None and int(claimed.group(1)) == total
      and table is not None and int(table.group(1)) == total,
      "名乗り %s・%s / 実際 %d" % (claimed.group(1) if claimed else "無い",
                                 table.group(1) if table else "無い", total))

print()
if failures:
    print("%d 項目が通りませんでした。" % len(failures))
    for f in failures:
        print("  - " + f)
    sys.exit(1)
print("すべて通りました。")
