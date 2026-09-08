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

# 自分の散文では使わないと決めた自称。
#
# **紙面には印字されている。**そこは直せないし、直さない。だが、いま自分が書く
# 文章では使わない。忘れると自然に戻ってくるので、機械で止める。
FORBIDDEN = [
    ('独立研究者', '自分の散文では使わない'),
    ('Independent Researcher', '同上（英訳）'),
]


# ですます調から である調へ書き換えたとき、五段活用の連用形に「た」「ない」を
# そのまま繋ぐ壊れ方が起きた。「載りました」→「載りた」、「使いません」→「使いない」。
# 日本語として成立しないが、漢字は正しいので目視では通り抜ける。
#
# 推測で活用を作らない。実際に混入した形だけを表に持つ。
CONJUGATION = [
    (r'ありなかった', 'なかった', '「ありません」からの書き換え'),
    (r'ありた(?![いくかけ])', 'あった', '同上'),
    (r'なりた(?![いくかけ])', 'なった', '「なりました」からの書き換え'),
    (r'残りた(?![いくかけ])', '残った', '「残りました」からの書き換え'),
    (r'載りた(?![いくかけ])', '載った', '「載りました」からの書き換え'),
    (r'分かりた(?![いくかけ])', '分かった', '「分かりました」からの書き換え'),
    (r'書きた(?![いくかけ])', '書いた', '「書きました」からの書き換え'),
    (r'置きた(?![いくかけ])', '置いた', '「置きました」からの書き換え'),
    (r'拾いた(?![いくかけ])', '拾った', '「拾いました」からの書き換え'),
    (r'行いた(?![いくかけ])', '行った', '「行いました」からの書き換え'),
    (r'使いた(?![いくかけ])', '使った', '「使いました」からの書き換え'),
    (r'使いない', '使わない', '「使いません」からの書き換え'),
    (r'言いない', '言わない', '「言いません」からの書き換え'),
    (r'狂いる', '狂う', '「狂います」からの書き換え'),
    (r'落とする', '落とす', '「落とします」からの書き換え'),
]
CONJUGATION = [(re.compile(p), r, n) for p, r, n in CONJUGATION]

# Markdown のバッジ記法の壊れ。![...] の ! が落ちる。
BADGE_BROKEN = re.compile(r'\[!(?!\[)[^\]]*\]\(https?://[^)]*badge')

# 第三者のロゴは載せない方針。バッジは文字と色だけにする。
# 商標は各社のもので、使用許諾を得ているわけではないため。
BADGE_LOGO = re.compile(r'img\.shields\.io/badge/[^)\s"]*[?&]logo=')

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
                for term, note in FORBIDDEN:
                    if term in line:
                        hits.append(('使わないと決めた語', rel, n,
                                     '「%s」  %s' % (term, note), line.strip()[:90]))
                for wrong, right, note in INCONSISTENT:
                    if wrong in line:
                        hits.append(('表記の揺れ', rel, n,
                                     '「%s」→「%s」  %s' % (wrong, right, note), line.strip()[:90]))
                for pat, right, note in CONJUGATION:
                    m = pat.search(line)
                    if m:
                        hits.append(('活用の壊れ', rel, n,
                                     '「%s」→「%s」  %s' % (m.group(0), right, note),
                                     line.strip()[:90]))
                if BADGE_BROKEN.search(line):
                    hits.append(('バッジ記法', rel, n,
                                 '! または [ が欠けています（[![…](…)](…) の形）', line.strip()[:90]))
                if BADGE_LOGO.search(line):
                    hits.append(('第三者のロゴ', rel, n,
                                 'バッジに logo= が入っています。文字と色だけにしてください',
                                 line.strip()[:90]))

print('%d ファイルを走査しました。' % scanned)
if hits:
    print('\n%d 件見つかりました。\n' % len(hits))
    for kind, rel, n, msg, text in hits:
        print('  [%s] %s:%d' % (kind, rel, n))
        print('    %s' % msg)
        print('    > %s\n' % text)
    sys.exit(1)
print('既知の誤変換・活用の壊れ・表記の揺れ・使わないと決めた語・バッジの壊れ・'
      '第三者のロゴは見つかりませんでした。')
