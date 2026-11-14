# 手を入れるときに

Issue も pull request も歓迎する。登録は要らない。

## ここに何があるか

海軍公報から一件ずつ史料を翻刻し、確定できることとできないことを分けて記録する。
いまのところ一件である。`data/` に機械可読にしたもの、`pdf/` に史料ノートがある。

## いちばん知らせてほしいもの

翻刻の誤りである。原文と突き合わせて違っている箇所を見つけたら、
<https://github.com/cpsbvbng26-dotcom/naval-gazette-notes/issues> に立ててほしい。

1. どの行か（假記番号で指定できる）
2. 何が違うか
3. 典拠（JACAR のレファレンスコードと、該当する画像の位置）

読みの情報もありがたい。人名の読みは確定していないものが多い。
確定できるなら、その根拠を添えてほしい。確定できないものは、確定できないまま置く。

## 原資料の画像を足さない

防衛省防衛研究所 戦史研究センターへの連絡が先である。
JACAR の画像をこのリポジトリに置く pull request は受けられない。

参照はレファレンスコードで行う。出典表記の形は README にある。

## 変更を出す

```
python3 verification/check_text.py    # 誤変換とバッジ記法
python3 data/check.py                 # データの形と出典表記
pip install pypdf
python3 verification/check_errata.py  # 正誤表の監査
```

通ってから出す。

## 確定と推測を混ぜない

この記録の核である。原文に書いてあることと、そこから推した事だけを分ける。

データの `rank_source` の列が、その実例である。原文にその行の階級が書いてあったのか、
「同」による繰り返しから引き継いだのかを、行ごとに区別している。
推測を確定の欄に入れる変更は受けられない。

## 通らない変更

- **原資料の画像の追加**
- **推測を確定として書くこと**
- **PDF の改変・再生成**
- **検査の期待値を、通すために変えること**

## 支えの範囲と、これからの見込み

- **維持しているのは著者一人である**（根本卓哉）。組織の後ろ盾は無い
- issue への返答は**数日から一週間**を目安とする。約束ではない
- 範囲。海軍公報の翻刻と、そこから確定できる事実に限る。人物の伝記、
  系譜の再構成、軍事史の解釈は範囲の外である
- 件数は増える見込みがある。増えても、一件ずつ同じ形で扱う

## ライセンス

散文とノートは [CC BY 4.0](LICENSE)、実装は [MIT](LICENSE-CODE)。

## 突き合わせの受付 / Checked intake

2026-12-01 から、誤りの知らせ（`error-report.yml`）は「突き合わせの受付」で確かめる。
人が嘘をつくこと一般は、仕組みでは止められない。受けるのは、申し立てた人がその場で書けない出どころと突き合わせられる申し立てだけで、通らないものと確かめられないものは自動で退ける。
確かめるのは一つだけである。「書いてあること」の語が、「どこか」の欄に書いた所（このリポジトリのファイル、配っている頁、このリポジトリが写しを持つ DOI の PDF か翻刻）に、そのとおりにあること。空白の違いと文字の幅は見ない。頁や節は確かめず、文書の全体を探す。
あればラベル「quote verified」を付ける。それが誤りかどうかは、人が読んで決める。なければ、決まった文のコメントを付けて閉じる。新しい issue で出し直せる。
削除・権利・個人の情報・氏名・人についての記述・同意の撤回を求めると読める issue は、自動では閉じない。ラベル「needs a person」を付け、人が読む。
コメントと実行の記録は、決まった語と issue の番号だけを書き、issue に書かれたことを写さない。
道具は `.github/checked-intake/verify.js`、確かめる先は `.github/checked-intake/config.json` にある。

From 2026-12-01, error reports (`error-report.yml`) are checked by the checked intake.
No system can stop a person from lying in general. Only claims that can be checked against a source that the claimant does not write at the moment of claiming are accepted; a claim that fails, or cannot be checked, is turned away automatically.
One thing is checked: that the words under "What it says" occur, as written, at the location under "Where" (a file of this repository, a page that it serves, or the PDF or transcription of a DOI of which it holds a copy). Differences of white space and character width are ignored. The page or section is not checked; the whole document is searched.
If they occur, the label "quote verified" is added, and whether it is an error is decided by a person. If they do not, the issue is closed with a fixed comment, and a new issue can be opened.
An issue that reads as asking for removal, or concerning rights, personal data, a name, a statement about a person or the withdrawal of a consent, is never closed automatically; it gets the label "needs a person", and a person reads it.
Comments and logs carry only fixed words and the issue number, never what the issue says.
The script is `.github/checked-intake/verify.js`; what it checks against is in `.github/checked-intake/config.json`.
