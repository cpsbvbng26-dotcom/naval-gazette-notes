#!/usr/bin/env python3
#
# MIT License
#
# Copyright (c) 2026 Takuya Nemoto (根本卓哉)
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
#
# この写しに加えたのは、この権利表示だけである。中身は写した版のままである。
# 原典: https://github.com/cpsbvbng26-dotcom/errata-check
"""凍結された公開物に対して、正誤表のほうを機械で監査する。

    python3 errata_check.py audit.toml

DOI が付いて公開された PDF は、もう直せない。直せるのは**正誤表のほう**である。
だから正誤表は、時間とともに一次資料からずれていく。引用が一字変わる。数え落とす。
「解決しました」と書き換わる。最終更新の日付が古いまま残る。

これは、そのずれを CI で落とすための道具である。

    引用      正誤表が「印字されている」と述べた文が、本当にその PDF にあるか
              逆に「印字されていない」と述べたものが、本当に無いか
    完全性    宣言した件数だけ引用が挙がっているか（数え落としを止める）
    不在      「同梱されている」と謳われたファイルが、本当に無いか
    数値      正誤表が名乗る件数が、実際にコマンドを走らせた結果と一致するか
    未解決    解決しないと決めた項目が、こっそり解決済みに書き換わっていないか
    凍結      一次資料そのものが差し替わっていないか（SHA-256）
    日付      最終更新が、本文に書かれたどの日付よりも古くないか

分野ごとに、紙面から決定的に確かめられるものが違う。次も見る。

    検定      印字された検定統計量と自由度から p を計算し直し、印字された p と合うか
              （t・F・χ²・r。statcheck と同じ考え方で、実装は独立）
    GRIM      整数を平均した値が、その標本数で本当に到達できる値か
              （Brown–Heathers の GRIM テストと同じ考え方）
    識別子     ORCID・ISBN・ISSN の検査数字（チェックディジット）が合っているか
    算術      印字されている数どうしの関係（内訳の和が総数に一致する、など）
    元号      和暦と西暦が対応しているか（史料を扱うときに効く）

**判定に推論を使わない。**あるか、無いか、一致するか、しないか。LLM も類似度も
使わない。だから出力を人が確かめ直す必要が無い。

PDF を読むときだけ pypdf が要る。平文（.txt / .md）だけを見るなら依存は無い。

    pip install pypdf

MIT License。© 2026 Takuya Nemoto
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import io
import json
import os
import re
import math
import subprocess
import sys
import unicodedata

__version__ = "0.2.0"
__all__ = ["Audit", "Result", "load", "run", "normalize", "extract_text",
           "p_value", "grim_ok", "checksum_ok", "era_to_gregorian"]

# ------------------------------------------------------------------ 文字の正規化

_ZERO = dict.fromkeys(map(ord, "­​‌‍﻿"), None)


def normalize(text):
    """比較の前に、取り出し方の違いで生じる差を潰す。

    PDF から取り出した文字列は、改行や空白の入り方が処理系で変わる。合字や
    幅の違う空白も混ざる。**意味を変えない差だけ**を潰す。
    文字そのものは変えない（NFKC はかけるが、置換表は持たない）。
    """
    text = unicodedata.normalize("NFKC", text)
    text = text.translate(_ZERO)
    return re.sub(r"\s+", " ", text).strip()


# ------------------------------------------------------- 分布（依存を持たない）
#
# 検定統計量から p を出すのに、scipy は使わない。単一ファイルで配れなくなるため。
# 正則化不完全ベータ・ガンマを Lentz の連分数と級数で実装する。
#
# **実装が正しいかどうかは、実装だけでは分からない。**公表されている数値表の
# 5% 点・1% 点と突き合わせて確かめてある（tests/check_tool.py の「分布」節）。


def _betacf(a, b, x):
    tiny = 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    if abs(d) < tiny:
        d = tiny
    d = 1.0 / d
    h = d
    for m in range(1, 300):
        m2 = 2 * m
        for aa in (m * (b - m) * x / ((qam + m2) * (a + m2)),
                   -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))):
            d = 1.0 + aa * d
            if abs(d) < tiny:
                d = tiny
            c = 1.0 + aa / c
            if abs(c) < tiny:
                c = tiny
            d = 1.0 / d
            h *= d * c
        if abs(d * c - 1.0) < 1e-15:
            break
    return h


def betainc(a, b, x):
    """正則化不完全ベータ関数 I_x(a, b)。"""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    ln = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    if x < (a + 1.0) / (a + b + 2.0):
        return math.exp(ln + a * math.log(x) + b * math.log1p(-x)) * _betacf(a, b, x) / a
    return 1.0 - math.exp(ln + b * math.log1p(-x) + a * math.log(x)) \
        * _betacf(b, a, 1.0 - x) / b


def gammainc_upper(s_, x):
    """正則化不完全ガンマ Q(s, x)。"""
    if x <= 0.0:
        return 1.0
    if x < s_ + 1.0:
        term = total = 1.0 / s_
        n = s_
        for _ in range(2000):
            n += 1.0
            term *= x / n
            total += term
            if abs(term) < abs(total) * 1e-16:
                break
        return 1.0 - total * math.exp(-x + s_ * math.log(x) - math.lgamma(s_))
    tiny = 1e-300
    b, c, d = x + 1.0 - s_, 1.0 / tiny, 1.0 / (x + 1.0 - s_)
    h = d
    for i in range(1, 2000):
        an = -i * (i - s_)
        b += 2.0
        d = an * d + b
        if abs(d) < tiny:
            d = tiny
        c = b + an / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        de = d * c
        h *= de
        if abs(de - 1.0) < 1e-16:
            break
    return h * math.exp(-x + s_ * math.log(x) - math.lgamma(s_))


def p_value(test, value, df, tail="two"):
    """印字された検定統計量から p を出す。

    test  't' / 'F' / 'chi2' / 'r'
    df    t と chi2 は [df]、F は [df1, df2]、r は [n]
    tail  't' と 'r' のみ 'one' が効く。F と chi2 はもともと片側
    """
    v = abs(float(value))
    if test == "t":
        p = betainc(df[0] / 2.0, 0.5, df[0] / (df[0] + v * v))
    elif test == "chi2":
        p = gammainc_upper(df[0] / 2.0, v / 2.0)
    elif test == "F":
        p = betainc(df[1] / 2.0, df[0] / 2.0, df[1] / (df[1] + df[0] * v))
    elif test == "r":
        n = df[0]
        t = v * math.sqrt((n - 2) / max(1.0 - v * v, 1e-300))
        p = betainc((n - 2) / 2.0, 0.5, (n - 2) / ((n - 2) + t * t))
    else:
        raise ValueError("知らない検定です: %s" % test)
    if tail == "one" and test in ("t", "r"):
        p /= 2.0
    return p


# --------------------------------------------------------------- GRIM
def grim_ok(mean, n, decimals, items=1):
    """整数を n 人ぶん平均した値として、その平均が到達できるか。

    合計は整数なので、平均 × n も整数でなければならない。印字は丸められて
    いるので、丸め幅の中に整数になる点があるかどうかで見る。
    """
    total = n * items
    half = 0.5 * 10 ** (-decimals)
    lo, hi = (mean - half) * total, (mean + half) * total
    return math.floor(hi) >= math.ceil(lo) and hi >= 0


# ---------------------------------------------------------- 検査数字
def _mod11_2(digits):
    """ISO 7064 MOD 11-2。ORCID と ISNI が使う。"""
    total = 0
    for ch in digits[:-1]:
        total = (total + int(ch)) * 2 % 11
    rem = (12 - total) % 11
    return ("X" if rem == 10 else str(rem)) == digits[-1].upper()


def checksum_ok(kind, value):
    """ORCID・ISBN・ISSN の検査数字を確かめる。"""
    v = re.sub(r"[\s\-]", "", str(value)).upper()
    if kind == "orcid":
        return len(v) == 16 and re.fullmatch(r"\d{15}[\dX]", v) is not None and _mod11_2(v)
    if kind == "isbn13":
        if len(v) != 13 or not v.isdigit():
            return False
        total = sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(v[:12]))
        return (10 - total % 10) % 10 == int(v[12])
    if kind == "isbn10":
        if len(v) != 10 or not re.fullmatch(r"\d{9}[\dX]", v):
            return False
        total = sum((10 - i) * int(c) for i, c in enumerate(v[:9]))
        total += 10 if v[9] == "X" else int(v[9])
        return total % 11 == 0
    if kind == "issn":
        if len(v) != 8 or not re.fullmatch(r"\d{7}[\dX]", v):
            return False
        total = sum((8 - i) * int(c) for i, c in enumerate(v[:7]))
        rem = (11 - total % 11) % 11
        return ("X" if rem == 10 else str(rem)) == v[7]
    raise ValueError("知らない識別子です: %s" % kind)


# ------------------------------------------------------------------ 元号
ERA_START = {"明治": 1868, "大正": 1912, "昭和": 1926, "平成": 1989, "令和": 2019}
_KANJI = {"〇": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
          "六": 6, "七": 7, "八": 8, "九": 9}


def _kanji_number(text):
    """漢数字を読む。元号の年なので 1〜99 まででよい。「元」は 1。"""
    text = text.strip()
    if text in ("元", "元年"):
        return 1
    text = text.rstrip("年")
    if text.isdigit():
        return int(text)
    if "十" in text:
        tens, _, ones = text.partition("十")
        t = 1 if tens == "" else _KANJI.get(tens, -1)
        o = 0 if ones == "" else _KANJI.get(ones, -1)
        if t < 0 or o < 0:
            return None
        return t * 10 + o
    return _KANJI.get(text)


def era_to_gregorian(text):
    """「昭和十八年」→ 1943。読めなければ None。

    元年は改元の年そのものなので、西暦 = 開始年 + 年数 − 1。
    改元の年は二つの元号にまたがるが、ここでは年の対応だけを見る。
    """
    m = re.match(r"\s*(明治|大正|昭和|平成|令和)\s*([0-9〇一二三四五六七八九十元]+)\s*年?", str(text))
    if not m:
        return None
    n = _kanji_number(m.group(2))
    if n is None or n < 1:
        return None
    return ERA_START[m.group(1)] + n - 1


def extract_text(path):
    """一次資料から文字を取り出す。PDF なら pypdf、それ以外は素直に読む。"""
    if path.lower().endswith(".pdf"):
        # 暗号化されていない PDF に暗号処理は要らない。環境によっては
        # cryptography の読み込みが壊れるので、先に塞いでから読む。
        sys.modules.setdefault("cryptography", None)
        try:
            from pypdf import PdfReader
        except ImportError:
            raise SystemExit(
                "PDF を読むには pypdf が要ります:  pip install pypdf")
        return "\n".join((p.extract_text() or "") for p in PdfReader(path).pages)
    with io.open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def digest(path):
    """SHA-256。凍結されているはずのものが差し替わっていないかを見るため。"""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


# ------------------------------------------------------------------ 宣言の読み込み

def load(path):
    """監査の宣言を読む。.toml（Python 3.11 以降）と .json に対応。"""
    if path.lower().endswith(".json"):
        with io.open(path, encoding="utf-8") as fh:
            return json.load(fh)
    try:
        import tomllib
    except ImportError:
        raise SystemExit("TOML には Python 3.11 以降が要ります。"
                         ".json で書くこともできます。")
    with open(path, "rb") as fh:
        return tomllib.load(fh)


# ------------------------------------------------------------------ 結果

class Result:
    """検査 1 件の結果。通ったかどうかと、外から見て分かる理由を持つ。"""

    def __init__(self, group, label, ok, detail=""):
        self.group = group
        self.label = label
        self.ok = bool(ok)
        self.detail = detail

    def line(self):
        return "  %s  %s%s" % ("PASS" if self.ok else "FAIL", self.label,
                               ("  " + self.detail) if self.detail else "")

    def as_dict(self):
        return {"group": self.group, "label": self.label,
                "ok": self.ok, "detail": self.detail}


# ------------------------------------------------------------------ 監査

class Audit:
    """宣言どおりに検査を走らせる。

    root       宣言ファイルからの相対パスの基準。既定は宣言ファイルの置き場所
    spec       load() が返した辞書
    """

    def __init__(self, spec, root="."):
        self.spec = spec
        self.root = root
        self.results = []
        self._text = {}
        self._document = None

    # -------------------------------------------------------------- 補助
    def _path(self, rel):
        return os.path.join(self.root, rel)

    def _add(self, group, label, ok, detail=""):
        self.results.append(Result(group, label, ok, detail))
        return ok

    def _source(self, sid):
        for s in self.spec.get("source", []):
            if s.get("id") == sid:
                return s
        return None

    def _source_text(self, sid):
        if sid not in self._text:
            s = self._source(sid)
            if s is None:
                return None
            self._text[sid] = normalize(extract_text(self._path(s["path"])))
        return self._text[sid]

    def document_text(self):
        """正誤表そのもの。宣言に document が無ければ None。"""
        if self._document is None:
            doc = self.spec.get("document")
            if not doc:
                return None
            with io.open(self._path(doc["path"]), encoding="utf-8") as fh:
                self._document = fh.read()
        return self._document

    # -------------------------------------------------------- 一次資料
    def check_sources(self):
        srcs = self.spec.get("source", [])
        self._add("凍結", "一次資料が宣言されている", bool(srcs),
                  "%d 件" % len(srcs))
        for s in srcs:
            path = self._path(s["path"])
            if not self._add("凍結", "%s が読める" % s["path"],
                             os.path.isfile(path)):
                continue
            got = digest(path)
            want = s.get("sha256")
            if not want:
                # 宣言が無いことを「通った」と数えない。書き足せるように値は出す。
                self._add("凍結", "%s の sha256 が宣言されている" % s["id"],
                          False, "いまの値: " + got)
            else:
                self._add("凍結", "%s が差し替わっていない" % s["id"],
                          got == want,
                          "宣言 %s… / 実際 %s…" % (want[:16], got[:16]))

    # ------------------------------------------------------------ 引用
    def check_quotes(self):
        quotes = self.spec.get("quote", [])
        doc = self.document_text()
        doc_flat = normalize(doc) if doc is not None else None
        tally = {}
        for q in quotes:
            sid = q["source"]
            if q.get("present", True):
                key = (sid, q.get("group"))
                tally[key] = tally.get(key, 0) + 1
            text = self._source_text(sid)
            where = q.get("where", "")
            head = normalize(q["text"])
            present = q.get("present", True)
            label = "%s%s の記述が一次資料に%s" % (
                sid, ("（%s）" % where) if where else "",
                "ある" if present else "無い")
            if text is None:
                self._add("引用", label, False, "一次資料 %s が宣言に無い" % sid)
                continue
            self._add("引用", label, (head in text) == present, head[:56] + "…")
            if not present:
                # 「印字されていないこと」は正誤表の側にはあってよい。数えない。
                continue
            if q.get("in_document", True) and doc_flat is not None:
                self._add("引用", "同じ引用が正誤表にもある", head in doc_flat,
                          head[:56] + "…")
        # 数え落としを落とす。「三箇所だと思っていたら六箇所だった」を止めるため。
        for c in self.spec.get("count", []):
            sid, group, want = c["source"], c.get("group"), c["expect"]
            got = (tally.get((sid, group), 0) if group is not None
                   else sum(v for (s_, _g), v in tally.items() if s_ == sid))
            name = "%s%s" % (sid, ("・%s" % group) if group else "")
            self._add("引用", "%s の記述が %d 箇所宣言されている" % (name, want),
                      got == want, "宣言 %d / 実際 %d" % (want, got))

    # ------------------------------------------------------------ 不在
    def check_absent(self):
        for a in self.spec.get("absent", []):
            pattern = os.path.join(self.root, a["glob"])
            hits = [os.path.relpath(p, self.root)
                    for p in glob.glob(pattern, recursive=True)]
            self._add("不在", "%s が存在しない" % a["glob"], not hits,
                      (a.get("reason", "") + ("  見つかった: " + ", ".join(hits[:3])
                                              if hits else "")).strip())

    # ------------------------------------------------------------ 数値
    def check_numbers(self):
        doc = self.document_text()
        for nspec in self.spec.get("number", []):
            label = nspec.get("label", nspec.get("pattern", "数値"))
            out = subprocess.run(nspec["command"], shell=True, cwd=self.root,
                                 capture_output=True, text=True)
            m = re.search(nspec["extract"], out.stdout)
            if not m:
                self._add("数値", "%s をコマンドの出力から取れる" % label, False,
                          "出力の末尾: " + out.stdout.strip()[-80:])
                continue
            actual = m.group(1)
            self._add("数値", "%s をコマンドの出力から取れる" % label, True,
                      actual)
            targets = nspec.get("in", [])
            if isinstance(targets, str):
                targets = [targets]
            if not targets and doc is not None:
                targets = [self.spec["document"]["path"]]
            for rel in targets:
                with io.open(self._path(rel), encoding="utf-8") as fh:
                    body = fh.read()
                found = re.findall(nspec["pattern"], body)
                self._add("数値", "%s に書かれた %s が実際と一致する" % (rel, label),
                          bool(found) and all(v == actual for v in found),
                          "文書 %s / 実際 %s" % (", ".join(sorted(set(found))) or "なし",
                                                actual))

    # ------------------------------------------------------------ 検定統計量
    def _in_source(self, group, spec, label):
        """spec の text が一次資料にあることを見る。text が無ければ何もしない。"""
        if "text" not in spec:
            return True
        text = self._source_text(spec.get("source"))
        if text is None:
            return self._add(group, label + "（一次資料が宣言に無い）", False)
        head = normalize(spec["text"])
        return self._add(group, label, head in text, head[:52] + "…")

    def check_statistics(self):
        """印字された検定統計量から p を計算し直し、印字された p と突き合わせる。

        statcheck（Nuijten ら 2016）と同じ考え方。実装は独立で、分布は
        公表されている数値表と突き合わせて確かめてある。

        consistent = false と宣言すれば、**合わないことのほうを検査する。**
        「この論文のここは p が誤って印字されている」と正誤表に書いたとき、
        その指摘自体が正しいかどうかを機械で押さえるための欄である。
        """
        for st in self.spec.get("statistic", []):
            where = st.get("where", "")
            name = "%s%s" % (st["test"], ("（%s）" % where) if where else "")
            self._in_source("検定", st, "%s の記述が一次資料にある" % name)
            m = re.search(r"p\s*([<>=]+)\s*(\d*\.\d+|\d+)", st["reported"])
            if not m:
                self._add("検定", "%s の印字された p を読める" % name, False, st["reported"])
                continue
            op, printed = m.group(1), m.group(2)
            decimals = len(printed.split(".")[1]) if "." in printed else 0
            target = float(printed if printed[0] != "." else "0" + printed)
            got = p_value(st["test"], st["value"], st["df"], st.get("tail", "two"))
            if op == "=":
                ok = abs(round(got, decimals) - target) < 10 ** (-decimals - 3)
            elif op == "<":
                ok = got < target
            else:
                ok = got > target
            want = st.get("consistent", True)
            self._add("検定",
                      "%s の p が計算し直した値と%s" % (
                          name, "合う" if want else "、宣言どおり合わない"),
                      ok == want,
                      "印字 %s / 計算 %.6f" % (st["reported"], got))

    # ------------------------------------------------------------ GRIM
    def check_grim(self):
        """整数を平均した値が、その標本数で到達できる値かどうか。

        Brown–Heathers の GRIM テストと同じ考え方。到達できない平均が
        印字されていれば、標本数か平均のどちらかが誤っている。
        """
        for g in self.spec.get("grim", []):
            where = g.get("where", "")
            name = "平均 %s（n = %d%s）" % (g["mean"], g["n"],
                                            "、%s" % where if where else "")
            self._in_source("GRIM", g, "%s の記述が一次資料にある" % name)
            printed = str(g["mean"])
            decimals = g.get("decimals",
                             len(printed.split(".")[1]) if "." in printed else 0)
            ok = grim_ok(float(g["mean"]), int(g["n"]), decimals, int(g.get("items", 1)))
            want = g.get("attainable", True)
            self._add("GRIM", "%s が%s到達できる値である"
                      % (name, "" if want else "、宣言どおり"), ok == want,
                      "到達できる: %s / 宣言: %s" % (ok, want))

    # ---------------------------------------------------------- 識別子
    def check_identifiers(self):
        """ORCID・ISBN・ISSN の検査数字を確かめる。

        書き写しの誤りは、ここでほぼ捕まる。一桁変えれば検査数字が合わなくなる。
        """
        doc = self.document_text()
        for idf in self.spec.get("identifier", []):
            kind, value = idf["kind"], str(idf["value"])
            self._add("識別子", "%s %s の検査数字が合っている" % (kind, value),
                      checksum_ok(kind, value))
            if idf.get("source"):
                text = self._source_text(idf["source"])
                self._add("識別子", "%s が %s に印字されている" % (value, idf["source"]),
                          text is not None and normalize(value) in text)
            elif doc is not None and idf.get("in_document", True):
                self._add("識別子", "%s が文書にある" % value, value in doc)

    # ------------------------------------------------------------ 算術
    def check_arithmetic(self):
        """印字されている数どうしの関係。内訳の和が総数に一致する、など。

        臨床試験の流れ図（無作為化 = 解析 + 脱落）や、表の合計に効く。
        """
        for a in self.spec.get("arithmetic", []):
            label = a.get("label", "算術")
            text = self._source_text(a["source"]) if a.get("source") else None
            for t in a.get("texts", []):
                self._add("算術", "「%s」が一次資料にある" % t[:32],
                          text is not None and normalize(t) in text)
            values = [float(v) for v in a["values"]]
            got = math.fsum(values) if a.get("op", "sum") == "sum" else \
                math.prod(values)
            tol = float(a.get("tolerance", 0.0))
            self._add("算術", label, abs(got - float(a["equals"])) <= tol,
                      "計算 %g / 宣言 %g" % (got, a["equals"]))

    # ------------------------------------------------------------ 元号
    def check_eras(self):
        """和暦と西暦が対応しているか。史料を扱うときに効く。"""
        for e in self.spec.get("era", []):
            self._in_source("元号", e, "「%s」が一次資料にある" % e["text"])
            got = era_to_gregorian(e["text"])
            self._add("元号", "%s = %s 年" % (e["text"], e["gregorian"]),
                      got == int(e["gregorian"]),
                      "換算 %s" % got)

    # -------------------------------------------------------- 未解決の項目
    def check_open_items(self):
        doc = self.document_text()
        if doc is None:
            return
        for item in self.spec.get("open_item", []):
            iid = item.get("id", "項目")
            hp = item.get("heading_pattern")
            if hp:
                self._add("未解決", "%s の見出しがある" % iid,
                          re.search(hp, doc, re.M) is not None, hp)
            for phrase in item.get("must_say", []):
                self._add("未解決", "%s が「%s」を保っている" % (iid, phrase[:24]),
                          phrase in doc)
            for phrase in item.get("must_not_say", []):
                self._add("未解決", "%s が「%s」と言っていない" % (iid, phrase[:24]),
                          phrase not in doc)

    # ------------------------------------------------------------ 日付
    def check_dates(self):
        doc = self.document_text()
        spec = self.spec.get("dates")
        if doc is None or not spec:
            return
        stamp_pat = spec["stamp_pattern"]
        any_pat = spec.get("any_pattern", stamp_pat)
        m = re.search(stamp_pat, doc)
        if not self._add("日付", "最終更新の日付が書いてある", m is not None,
                         stamp_pat):
            return
        def key(match):
            return tuple(int(g) for g in match)
        stamp = key(m.groups())
        inner = [key(g) for g in re.findall(any_pat, doc)]
        newest = max(inner) if inner else stamp
        self._add("日付", "最終更新が本文のどの日付よりも古くない", stamp >= newest,
                  "最終更新 %s / 本文の最新 %s" % (stamp, newest))

    # ------------------------------------------------------------ 実行
    def run(self):
        self.check_sources()
        self.check_quotes()
        self.check_absent()
        self.check_numbers()
        self.check_statistics()
        self.check_grim()
        self.check_identifiers()
        self.check_arithmetic()
        self.check_eras()
        self.check_open_items()
        self.check_dates()
        return self.results


def run(spec_path, quiet=False, as_json=False):
    """宣言を読んで走らせ、(通った件数, 落ちた結果) を返す。"""
    spec = load(spec_path)
    root = spec.get("root") or os.path.dirname(os.path.abspath(spec_path)) or "."
    if not os.path.isabs(root):
        root = os.path.join(os.path.dirname(os.path.abspath(spec_path)), root)
    audit = Audit(spec, root=os.path.normpath(root))
    results = audit.run()
    if as_json:
        print(json.dumps({"version": __version__,
                          "passed": sum(r.ok for r in results),
                          "failed": sum(not r.ok for r in results),
                          "results": [r.as_dict() for r in results]},
                         ensure_ascii=False, indent=1))
    elif not quiet:
        group = None
        for r in results:
            if r.group != group:
                group = r.group
                print("\n" + group)
            print(r.line())
    return sum(r.ok for r in results), [r for r in results if not r.ok]


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="errata-check",
        description="凍結された公開物に対して、正誤表のほうを機械で監査する。")
    ap.add_argument("spec", help="監査の宣言（.toml または .json）")
    ap.add_argument("--json", action="store_true", dest="as_json",
                    help="結果を JSON で出す")
    ap.add_argument("--quiet", action="store_true", help="要約だけ出す")
    ap.add_argument("--version", action="version", version=__version__)
    args = ap.parse_args(argv)

    passed, failed = run(args.spec, quiet=args.quiet, as_json=args.as_json)
    if not args.as_json:
        print("\n" + "-" * 58)
        if failed:
            print("%d 件が通り、%d 件が通りませんでした。" % (passed, len(failed)))
            for r in failed:
                print("  - " + r.label + (("  " + r.detail) if r.detail else ""))
        else:
            print("%d 件すべて通りました。" % passed)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
