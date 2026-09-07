#!/usr/bin/env python3
"""ERRATA.md が史料ノートからずれていないかを、機械で当たる。

    pip install pypdf
    python3 verification/check_errata.py

この PDF は公開済みで、もう直せない。**直せるのは正誤表のほうである。**
だから正誤表は、時間とともに紙面からずれていく。引用が一字変わる。「印字されて
いない」と書いたものが、実は印字されていた。未解決の項目が「解決済み」に
書き換わる。最終更新の日付が古いまま残る。

条件は verification/audit.toml に宣言してあり、当たるのは errata_check.py が
やる。**判定に推論を使わない。**あるか、無いか、一致するか、しないか。

道具は errata-check（MIT、v0.2.0、DOI: 10.5281/zenodo.22649899）。単一ファイルなので
ここに写して使っている。
https://github.com/cpsbvbng26-dotcom/errata-check
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from errata_check import Audit, load  # noqa: E402

spec = load(os.path.join(HERE, "audit.toml"))
audit = Audit(spec, root=ROOT)
results = audit.run()

group = None
for r in results:
    if r.group != group:
        group = r.group
        print("\n" + group)
    print(r.line())

print("\n配布物")
extra = []


def check(label, cond, detail=""):
    extra.append((label, bool(cond), detail))
    print("  %s  %s%s" % ("PASS" if cond else "FAIL", label,
                          ("  " + detail) if detail else ""))


declared = sorted(os.path.basename(s["path"]) for s in spec["source"])
actual = sorted(f for f in os.listdir(os.path.join(ROOT, "pdf")) if f.endswith(".pdf"))
check("配布している PDF は宣言したものだけ", declared == actual, ", ".join(actual))
check("原資料の画像を同梱していない",
      not [f for f in os.listdir(ROOT) if f.lower().endswith((".jpg", ".jpeg", ".tif", ".tiff"))],
      "転載には防衛省防衛研究所への確認が要る")

passed = sum(r.ok for r in results) + sum(1 for _, ok, _ in extra if ok)
failed = [r.label for r in results if not r.ok] + [l for l, ok, _ in extra if not ok]

print("\n" + "-" * 58)
if failed:
    print("%d 件が通り、%d 件が通りませんでした。" % (passed, len(failed)))
    for f in failed:
        print("  - " + f)
    sys.exit(1)
print("%d 件すべて通りました。" % passed)
