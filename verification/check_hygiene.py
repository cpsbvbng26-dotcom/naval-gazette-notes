#!/usr/bin/env python3
"""リポジトリの衛生を、標準ライブラリだけで確かめる。

    python3 verification/check_hygiene.py

見るのは七つである。

  依存     外部のパッケージは、hygiene.toml の packages に挙げたものだけを使う。
           import / require、pip install / npm install、package.json・pyproject.toml・
           requirements*.txt のどこに出ても同じに数える。
  権限     .github/workflows/ のどのファイルも、先頭の階層に permissions: を置く。
           書き込みの権限は、hygiene.toml の writes に挙げたものだけを許す。
  固定     外部のアクションは、40 桁のコミットの値で固定し、後ろに「# 版」を書く。
           action.yml の中の uses: も同じに見る。
  走査     追跡しているテキストのファイルに、秘密の鍵・トークン・許していない
           メールアドレスが無い。
  要旨     日本語の要旨と英語の要旨が、同じ数とローマ字の語を挙げる。
  数       ほかの検査が拾っていなかった散文の数を、数え直すか、もとの数と突き合わせる。
  規約     .github/workflows/ のどのファイルも、法令の点検の記録（docs/legal-audit-2026-11-12.md）の
           「八度目の見落とし」の表に行を持ち、GitHub の追加製品の規約の Actions の節に照らして判定してある。

この七つは、ほかのリポジトリと同じ一本のスクリプトで見る。違うのは hygiene.toml だけである。
このファイルは各リポジトリで一字一句同じにしてある。直すときは全部直す。
"""
from __future__ import annotations

import ast
import glob
import json
import os
import re
import subprocess
import sys
import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CONF_PATH = os.path.join(HERE, "hygiene.toml")

passed = 0
failed: list[str] = []


def ok(label: str, cond: bool, detail: str = "") -> None:
    global passed
    if cond:
        passed += 1
        print("  通  " + label)
    else:
        failed.append(label)
        print("  落  " + label + (" —— " + detail if detail else ""))


def tracked() -> list[str]:
    """git が追跡しているファイル。git が無ければ、.git を除いて歩く。"""
    try:
        out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout
        files = [f for f in out.decode("utf-8").split("\0") if f]
        return [f for f in files if os.path.isfile(os.path.join(ROOT, f))]
    except (OSError, subprocess.CalledProcessError):
        files = []
        for d, dirs, names in os.walk(ROOT):
            dirs[:] = [x for x in dirs if x not in (".git", "node_modules", "site", "__pycache__")]
            files += [os.path.relpath(os.path.join(d, n), ROOT) for n in names]
        return sorted(files)


def read(rel: str) -> str:
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


with open(CONF_PATH, "rb") as f:
    CONF = tomllib.load(f)
PACKAGES = set(CONF.get("packages", []))
WRITES = set(CONF.get("writes", []))
FILES = tracked()

# ------------------------------------------------------------------
print("1. 依存")
# ------------------------------------------------------------------
local = set()
for f in FILES:
    if f.endswith(".py"):
        local.add(os.path.splitext(os.path.basename(f))[0])
        parts = f.split("/")
        local.update(parts[:-1])
stdlib = set(sys.stdlib_module_names)

py_foreign = []
for f in [x for x in FILES if x.endswith(".py")]:
    try:
        tree = ast.parse(read(f), filename=f)
    except SyntaxError as e:
        ok(f + " を読める", False, str(e))
        continue
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names = [node.module]
        for n in names:
            top = n.split(".")[0]
            if top not in stdlib and top not in local and top not in PACKAGES and top != "__future__":
                py_foreign.append(f + " " + top)
ok("Python の import は、標準ライブラリ・このリポジトリのファイル・許したパッケージだけ", not py_foreign, ", ".join(py_foreign))

JS_FILES = [x for x in FILES if x.endswith((".js", ".mjs", ".cjs"))]
js_foreign = []
if JS_FILES:
    try:
        builtins = set(json.loads(subprocess.run(
            ["node", "-p", "JSON.stringify(require('module').builtinModules)"],
            capture_output=True, check=True, text=True).stdout))
    except (OSError, subprocess.CalledProcessError, ValueError):
        builtins = None
    ok("Node.js の組み込みのモジュールの一覧を読める（JavaScript のファイルがあるので要る）", builtins is not None)
    REQ = re.compile(r"""(?:\brequire\s*\(\s*|\bimport\s*\(\s*|^\s*import\s[^'"]*?\bfrom\s*|^\s*import\s*)['"]([^'"]+)['"]""", re.M)
    for f in JS_FILES:
        for m in REQ.finditer(read(f)):
            spec = m.group(1)
            if spec.startswith((".", "/")):
                continue
            name = spec[5:] if spec.startswith("node:") else spec
            pkg = "/".join(name.split("/")[:2]) if name.startswith("@") else name.split("/")[0]
            if builtins is not None and (name in builtins or pkg in builtins):
                continue
            if pkg not in PACKAGES:
                js_foreign.append(f + " " + pkg)
ok("JavaScript の require / import は、組み込み・このリポジトリのファイル・許したパッケージだけ", not js_foreign, ", ".join(js_foreign))

manifest = []
for f in FILES:
    base = os.path.basename(f)
    if base == "package.json":
        pj = json.loads(read(f))
        for key in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies"):
            if pj.get(key):
                manifest.append(f + " " + key)
    elif base == "pyproject.toml":
        deps = tomllib.loads(read(f)).get("project", {}).get("dependencies", [])
        if deps:
            manifest.append(f + " dependencies " + ",".join(deps))
    elif re.fullmatch(r"requirements.*\.txt", base):
        for line in read(f).splitlines():
            name = re.split(r"[<>=!~\[; ]", line.split("#")[0].strip())[0]
            if name and name not in PACKAGES:
                manifest.append(f + " " + name)
ok("package.json・pyproject.toml・requirements*.txt に、許していない依存が無い", not manifest, ", ".join(manifest))

YML = [x for x in FILES if x.startswith(".github/workflows/") and x.endswith((".yml", ".yaml"))]
ACTIONS = [x for x in FILES if os.path.basename(x) in ("action.yml", "action.yaml")]
installs = []
for f in YML + ACTIONS:
    for m in re.finditer(r"\b(?:pip3?|npm)\s+install\s+([^\n#&|;]+)", read(f)):
        words = m.group(1).split()
        skip = False
        for w in words:
            if skip:
                skip = False
                continue
            if w in ("-r", "--requirement", "-c"):
                skip = True
                continue
            if w.startswith("-") or w.startswith("$"):
                continue
            # pypdf==6.19.0 も playwright@1.56.1 も、名だけにする。@scope/name は頭の @ を残す。
            name = "@" + w[1:].split("@")[0] if w.startswith("@") else re.split(r"[<>=!~\[@]", w)[0]
            if name not in PACKAGES:
                installs.append(f + " " + name)
ok("ワークフローで入れるパッケージは、許したものだけ", not installs, ", ".join(installs))

# ------------------------------------------------------------------
print("2. 権限")
# ------------------------------------------------------------------
ok(".github/workflows/ にワークフローがある", len(YML) > 0)
no_top = [f for f in YML if not re.search(r"^permissions:", read(f), re.M)]
ok("どのワークフローも、先頭の階層に permissions: を置く", not no_top, ", ".join(no_top))
everything = [f for f in YML if re.search(r"permissions:\s*write-all", read(f))]
ok("write-all を使わない", not everything, ", ".join(everything))
writes = set()
for f in YML:
    for m in re.finditer(r"^\s+([a-z-]+):\s*write\b", read(f), re.M):
        writes.add(os.path.basename(f) + ":" + m.group(1))
ok("書き込みの権限は hygiene.toml の writes に挙げたものだけ", writes <= WRITES, ", ".join(sorted(writes - WRITES)))
ok("hygiene.toml の writes に、使っていない権限が残っていない", WRITES <= writes, ", ".join(sorted(WRITES - writes)))
me = os.path.relpath(os.path.abspath(__file__), ROOT).replace(os.sep, "/")
weekly = [f for f in YML if ("python3 " + me) in read(f) and re.search(r"^\s+schedule:\s*\n\s+- cron:", read(f), re.M)]
ok("この検査を、push と PR のほかに定期にも回すワークフローがある", len(weekly) > 0, "python3 " + me + " と schedule: を持つワークフローが無い")

# ------------------------------------------------------------------
print("3. 固定")
# ------------------------------------------------------------------
loose = []
count = 0
for f in YML + ACTIONS:
    for line in read(f).splitlines():
        m = re.match(r"^\s*(?:-\s+)?uses:\s*(\S+)(.*)$", line)
        if not m:
            continue
        ref, rest = m.group(1), m.group(2)
        if ref.startswith("./"):
            continue
        count += 1
        if not re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", ref) or not re.match(r"\s+#\s*\S+", rest):
            loose.append(f + " " + ref)
ok("外部のアクションを、40 桁のコミットの値と「# 版」で固定している（" + str(count) + " 箇所）", not loose, ", ".join(loose))

# ------------------------------------------------------------------
print("4. 秘密と連絡先の走査")
# ------------------------------------------------------------------
# 型そのものをこのファイルに書くと、このファイルが引っかかる。だから切って繋ぐ。
SECRET = [
    ("秘密の鍵", re.compile("-----BEGIN " + r"[A-Z ]*PRIVATE KEY" + "-----")),
    ("GitHub のトークン", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github" + r"_pat_[A-Za-z0-9_]{22,})")),
    ("AWS の鍵", re.compile(r"\bAKI" + r"A[0-9A-Z]{16}\b")),
    ("Slack のトークン", re.compile(r"\bxox" + r"[abprs]-[A-Za-z0-9-]{10,}")),
    ("Google の鍵", re.compile(r"\bAIz" + r"a[0-9A-Za-z_-]{35}\b")),
    ("Anthropic・OpenAI の鍵", re.compile(r"\bsk-(?:an" + r"t-)?[A-Za-z0-9_-]{32,}")),
]
MAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
ALLOW = {"noreply@anthropic.com", "you@example.com"} | set(CONF.get("mails", []))
BINARY = (".pdf", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp", ".docx", ".zip", ".gz", ".woff", ".woff2", ".odt")
hits, mails = [], []
scanned = 0
for f in FILES:
    if f.lower().endswith(BINARY):
        continue
    with open(os.path.join(ROOT, f), "rb") as fh:
        raw = fh.read()
    if b"\0" in raw[:8192]:
        continue
    text = raw.decode("utf-8", errors="replace")
    scanned += 1
    for name, rx in SECRET:
        if rx.search(text):
            hits.append(f + " " + name)
    for m in MAIL.findall(text):
        if m not in ALLOW and not m.endswith("@users.noreply.github.com"):
            mails.append(f + " " + m)
ok("秘密の鍵やトークンが無い（" + str(scanned) + " ファイル）", not hits, ", ".join(hits))
ok("許したもののほかに、メールアドレスが無い", not mails, ", ".join(sorted(set(mails))[:10]))

# ------------------------------------------------------------------
print("5. 要旨の日本語と英語")
# ------------------------------------------------------------------
# 片方だけ古い、を落とす。訳の良し悪しは見ない。数と、日本語の要旨に出てくるローマ字の語
# （識別子・状態の名・道具の名）が、英語の要旨にも出てくることを見る。英語の側の数も日本語の側にあること。
JA_CHAR = re.compile(r"[぀-ヿ㐀-鿿]")


def field(spec: list[str]) -> str:
    rel, key = spec
    text = read(rel)
    if rel.endswith(".json"):
        return re.sub(r"<[^>]+>", " ", json.loads(text).get(key, ""))
    m = re.search(r"^" + re.escape(key) + r":\s*[>|][-+]?\n((?:[ \t]+.*\n|\n)+)", text, re.M)
    return " ".join(line.strip() for line in m.group(1).splitlines()) if m else ""


def part(text: str, lang: str) -> str:
    out = []
    for s in re.split(r"(?<=[。．])|(?<=[.!?])\s+", text):
        letters = [c for c in s if not c.isspace()]
        ja = letters and len(JA_CHAR.findall(s)) / len(letters) > 0.3
        if s.strip() and (ja if lang == "ja" else not ja):
            out.append(s.strip())
    return " ".join(out)


ABS = CONF.get("abstract")
if ABS:
    ja, en = part(field(ABS["ja"]), "ja"), part(field(ABS["en"]), "en")
    ok("日本語の要旨がある（" + ":".join(ABS["ja"]) + "）", len(ja) > 0)
    ok("英語の要旨がある（" + ":".join(ABS["en"]) + "）", len(en.split()) >= 20, str(len(en.split())) + " 語")
    nja, nen = set(re.findall(r"\d+", ja)), set(re.findall(r"\d+", en))
    # 日本語が漢数字で書いている数（年月日など）だけを、英語の側に許す。hygiene.toml に名指しで置く。
    nen -= set(ABS.get("en_only_numbers", []))
    ok("日本語と英語の要旨が、同じ数を挙げる", nja == nen,
       "日本語だけ " + ",".join(sorted(nja - nen)) + " / 英語だけ " + ",".join(sorted(nen - nja)))
    latin = sorted({w for w in re.findall(r"[A-Za-z][A-Za-z0-9_.-]*[A-Za-z0-9]", ja)} - {w for w in ABS.get("ja_only", [])})
    gone = [w for w in latin if w not in en]
    ok("日本語の要旨に出てくるローマ字の語が、英語の要旨にも出てくる", not gone, ", ".join(gone))
else:
    ok("hygiene.toml が、要旨を置かない理由を書いている", bool(CONF.get("no_abstract")), "[abstract] も no_abstract も無い")

# ------------------------------------------------------------------
print("6. 散文の数（決めごと 5）")
# ------------------------------------------------------------------
# 他の検査が拾っていなかった数を、ここで拾う。二つの形がある。
#   counts  数え直す。ファイルの数か、ファイルの中で型に合うものの数。
#   copies  写しの数。もとの数（別の検査が実際と突き合わせている数）と同じであること。
# 兄弟のリポジトリにある数は「../<リポジトリ>/<ファイル>」と書く。ECOSYSTEM_ROOT があればそこから読む。
# 兄弟が無ければ、見ていないと名乗って通す（CI には兄弟が無い）。
ECO = os.environ.get("ECOSYSTEM_ROOT") or os.path.dirname(ROOT)


def locate(rel: str) -> str:
    return os.path.join(ECO, rel[3:]) if rel.startswith("../") else os.path.join(ROOT, rel)


def said(spec: list[str]) -> tuple[list[int], bool]:
    """[ファイル, 型] の型に合う数のすべて。ファイルが無ければ (…, False)。"""
    p = locate(spec[0])
    if not os.path.isfile(p):
        return [], False
    with open(p, encoding="utf-8") as fh:
        return [int(x) for x in re.findall(spec[1], fh.read(), re.M)], True


for c in CONF.get("counts", []):
    files = sorted(set(glob.glob(os.path.join(ROOT, c["files"]))) - {os.path.join(ROOT, x) for x in c.get("exclude", [])})
    if "pattern" in c:
        found = set() if c.get("distinct") else []
        for f in files:
            with open(f, "rb") as fh:
                raw = fh.read()
            # PDF のような中身は、バイトを一対一に文字へ移して型を当てる。
            text = raw.decode("latin-1") if c.get("binary") else raw.decode("utf-8")
            if c.get("section"):
                m = re.search(r"^" + re.escape(c["section"]) + r"\n(.*?)(?=^## |\Z)", text, re.M | re.S)
                text = m.group(1) if m else ""
            hits = re.findall(c["pattern"], text, re.M)
            found = found | set(hits) if c.get("distinct") else found + hits
        n = len(found)
    else:
        n = len(files)
    wrong = []
    for place in c["places"]:
        nums, there = said(place)
        if not nums or any(x != n for x in nums):
            wrong.append(place[0] + " " + (",".join(map(str, nums)) or "名乗りが無い"))
    ok("%s の数（%d）を、散文が正しく名乗る" % (c["what"], n), not wrong, " / ".join(wrong))

for c in CONF.get("copies", []):
    src, there = said(c["from"])
    if not there:
        ok("%s の写し（兄弟ディレクトリに %s が無いので見ていない）" % (c["what"], c["from"][0]), True)
        continue
    wrong = []
    if len(set(src)) != 1:
        wrong.append("もとの " + c["from"][0] + " から一つの数が取れない " + ",".join(map(str, src)))
    for place in c["to"]:
        nums, _ = said(place)
        if not nums or set(nums) != set(src[:1]):
            wrong.append(place[0] + " " + (",".join(map(str, nums)) or "名乗りが無い"))
    ok("%s の写しが、もと（%s の %s）と合う" % (c["what"], c["from"][0], ",".join(map(str, sorted(set(src))))), not wrong, " / ".join(wrong))

# ------------------------------------------------------------------
print("7. ワークフローと GitHub の規約（2026-11-13）")
# ------------------------------------------------------------------
# GitHub の利用規約は I 節で追加製品の規約を取り込み、その Actions の節は、GitHub の実行環境での使い方を、リポジトリの
# ソフトウェアのプロジェクトの制作・検査・配備・公開に限る。ワークフローを足すときは、点検の記録の表に行を足して判定する。
# 行の無いワークフローも、無いワークフローの行も落とす。引いた文が記録にあることも見る。
AUDIT = "docs/legal-audit-2026-11-12.md"
EIGHTH = "\n## 2026-11-12 の続き：八度目の見落とし\n"
PURPOSE = ("If using GitHub-hosted runners, any other activity unrelated to the production, testing, deployment, "
           "or publication of the software project associated with the repository where GitHub Actions are used.")


def workflow_rows(text: str) -> tuple[list[list[str]], str]:
    i = text.find(EIGHTH)
    if i < 0:
        return [], ""
    j = text.find("\n## ", i + len(EIGHTH))
    sec = text[i: j if j >= 0 else len(text)]
    rows = [l[2:-2].split(" | ") for l in sec.splitlines() if l.startswith("| ") and not l.startswith(("| 箇所 |", "| --- |"))]
    return rows, sec


def workflow_problems(text: str, names: list[str]) -> list[str]:
    rows, sec = workflow_rows(text)
    if not sec:
        return ["記録に八度目の見落としの節が無い"]
    bad = []
    judged = {"誤り", "根拠不足", "漏れ", "表現", "問題なし"}
    for r in rows:
        if len(r) != 6 or r[4] not in judged:
            bad.append("表の形：" + r[0][:30])
        elif r[4] != "問題なし" and "2026-11-13 に Claude が決めました。" not in r[5]:
            bad.append("決めた者の無い行：" + r[0][:30])
    named = [m.group(1) for r in rows for m in [re.match(r"`\.github/workflows/([^`]+)`", r[0])] if m]
    bad += ["行の無いワークフロー：" + n for n in names if n not in named]
    bad += ["無いワークフローの行：" + n for n in named if n not in names]
    if "「" + PURPOSE + "」" not in sec:
        bad.append("Actions の節の文を引いていない")
    return bad


AUDIT_TEXT = read(AUDIT) if os.path.isfile(os.path.join(ROOT, AUDIT)) else ""
NAMES = sorted(os.path.basename(f) for f in YML)
wp = workflow_problems(AUDIT_TEXT, NAMES)
ok("ワークフロー（" + str(len(NAMES)) + " 本）が、どれも点検の記録の表に行を持ち、GitHub の追加製品の規約に照らして判定してある", not wp, ", ".join(wp))
first = NAMES[0] if NAMES else "x.yml"
broken = [
    workflow_problems(AUDIT_TEXT, NAMES + ["newsletter.yml"]),
    workflow_problems(AUDIT_TEXT, [n for n in NAMES if n != first]),
    workflow_problems(re.sub(r"\n\| `\.github/workflows/" + re.escape(first) + r"`[^\n]*", "", AUDIT_TEXT), NAMES),
    workflow_problems(AUDIT_TEXT.replace("publication of the software project", "promotion of the software project"), NAMES),
    workflow_problems(AUDIT_TEXT.replace(EIGHTH, "\n## 八度目\n"), NAMES),
]
ok("壊して確かめる：新しいワークフロー・外したワークフロー・表から外した行・引いた文の一語・節の見出しのどれでも落ちる（"
   + str(sum(1 for b in broken if b)) + " / " + str(len(broken)) + "）", all(broken))

print("\n" + "-" * 56)
if failed:
    print("%d 件が通り、%d 件が通りませんでした。" % (passed, len(failed)))
    sys.exit(1)
print("%d 件すべて通りました。" % passed)
