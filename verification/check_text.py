#!/usr/bin/env python3
"""文字化けと既知の誤変換を止める。

    python3 verification/check_text.py

標準ライブラリのみ。

このリポジトリ群では、公開文の編集にあたって同じ種類の壊れ方が繰り返し起きている。
見た目の似た別の漢字に置き換わり、意味が通らなくなる。日本語を読まない目視では
気づきにくく、しかも壊れる場所が重い一文であることが多い。

実際に起きたものを表に持ち、push のたびに落とす。
（Node のあるリポジトリには同じ内容の check_text.js を置いている。）
"""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP = {'.git', 'node_modules', 'site', 'pdf', 'venv', '__pycache__'}
EXT = ('.md', '.html', '.cff', '.json', '.js', '.py', '.yml')

# 実際に混入したもの。wrong は日本語として成立しない、または文脈で明らかに誤り。
CORRUPTIONS = [
    ('捨造', '捏造', '「引用・出典の捏造は行われていません」— 開示文で最も重い一文'),
    ('取り縹う', '取り繕う', '「あとから表示だけを取り繕うことはできません」'),
    ('取り縁う', '取り繕う', '同上'),
    ('精締', '精緻', '「精緻な議論」'),
    ('チェックデジット', 'チェックディジット', 'check digit の表記'),
]

# 文字化けではなく、実在する字だが、この一連のリポジトリで表記を一つに決めたもの。
# 誤変換と混ぜると、壊れているのか選んだのかが区別できなくなる。
INCONSISTENT = [
    ('叙勳', '叙勲', '散文は常用字体。史料そのものの引用（敍勲四等授瑞寶章 など）はこの限りではない'),
]

# Markdown のバッジ記法の壊れ。![...] の ! が落ちる。
BADGE_BROKEN = re.compile(r'\[!(?!\[)[^\]]*\]\(https?://[^)]*badge')

SELF = os.path.join('verification', 'check_text.py')

hits = []
scanned = 0

for dirpath, dirnames, filenames in os.walk(ROOT):
    dirnames[:] = [d for d in dirnames if d not in SKIP]
    for name in sorted(filenames):
        if not name.endswith(EXT):
            continue
        full = os.path.join(dirpath, name)
        rel = os.path.relpath(full, ROOT)
        if rel == SELF:
            continue
        scanned += 1
        with open(full, encoding='utf-8', errors='replace') as fh:
            for n, line in enumerate(fh, 1):
                for wrong, right, note in CORRUPTIONS:
                    if wrong in line:
                        hits.append(('誤変換', rel, n,
                                     '「%s」→「%s」  %s' % (wrong, right, note), line.strip()[:90]))
                for wrong, right, note in INCONSISTENT:
                    if wrong in line:
                        hits.append(('表記の揺れ', rel, n,
                                     '「%s」→「%s」  %s' % (wrong, right, note), line.strip()[:90]))
                if BADGE_BROKEN.search(line):
                    hits.append(('バッジ記法', rel, n,
                                 '! または [ が欠けています（[![…](…)](…) の形）', line.strip()[:90]))

print('%d ファイルを走査しました。' % scanned)
if hits:
    print('\n%d 件見つかりました。\n' % len(hits))
    for kind, rel, n, msg, text in hits:
        print('  [%s] %s:%d' % (kind, rel, n))
        print('    %s' % msg)
        print('    > %s\n' % text)
    sys.exit(1)
print('既知の誤変換・表記の揺れ・バッジ記法の壊れは見つかりませんでした。')
