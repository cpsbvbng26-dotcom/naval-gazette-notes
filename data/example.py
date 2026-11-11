#!/usr/bin/env python3
"""investiture-1943-09-11.csv を読んで数える例。標準ライブラリだけで動く。

    python3 data/example.py
"""

import collections
import csv
import os

path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "investiture-1943-09-11.csv")
with open(path, encoding="utf-8", newline="") as fh:
    rows = list(csv.DictReader(fh))

print("全件", len(rows))
for rank, n in collections.Counter(r["rank_ja"] for r in rows).most_common():
    print(rank, n)
for source, n in collections.Counter(r["rank_source"] for r in rows).most_common():
    print(source, n)
otani = next(r for r in rows if r["entry_no"] == "2603-25")
print(otani["entry_no"], otani["name_as_printed"], otani["rank_ja"], otani["rank_source"])
