#!/usr/bin/env python3

import os
import sys
import sqlite3
from typing import NamedTuple
from collections import defaultdict

DB = 'data.db'

LABEL_CODES = {
    'American': 'A',
    'American variant': 'Av',
    'British': 'B',
    'British variant': 'Bv',
    'Oxford': 'Z',
    'Oxford variant': 'Zv',
    'non-variant': '_',
    'variant': '_v',
}

# preferred order of codes when a word carries several (for sorting/printing)
CODE_ORDER = list(LABEL_CODES.values())
CODE_RANK = {c: i for i, c in enumerate(CODE_ORDER)}

# with --easy, only output groups whose codes are all in this set
EASY_CODES = {'A', 'B', 'Z'}

# with --regional, a group must carry an American-side and a British-side code
AMERICAN_CODES = {'A', 'Av'}
BRITISH_CODES = {'B', 'Bv'}


class Row(NamedTuple):
    row_id: int
    req_id: int
    run_id: int
    qualifier: str
    notes: str


class Word(NamedTuple):
    labels: list  # list of (row_id, code)
    word: str


class Entry(NamedTuple):
    labels: list  # codes, deduped and sorted
    word: str


def split_cells(s):
    """Split a comma-separated cell into individual stripped values."""
    if s is None:
        return []
    return [p.strip() for p in s.split(',') if p.strip()]


def code_for(label):
    code = LABEL_CODES.get(label)
    if code is None:
        print(f'warning: unknown label {label!r}', file=sys.stderr)
        return label
    return code


class UnionFind:
    def __init__(self):
        self.parent = {}

    def find(self, x):
        self.parent.setdefault(x, x)
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:
            self.parent[x], x = root, self.parent[x]
        return root

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def main():
    args = sys.argv[1:]
    easy_only = False
    for flag in ('--easy', '-e'):
        if flag in args:
            easy_only = True
            args.remove(flag)
    regional_only = '--regional' in args
    while '--regional' in args:
        args.remove('--regional')
    run_ids = [int(a) for a in args]
    if not run_ids:
        print('usage: extract.py [--easy] [--regional] run_id [run_id ...]',
              file=sys.stderr)
        sys.exit(1)

    con = sqlite3.connect(DB)
    placeholders = ','.join('?' * len(run_ids))
    cur = con.execute(
        f'''select row_id, req_id, run_id, label, word,
                   variant_label, variant, qualifier, notes
            from results
            where run_id in ({placeholders}) and label is not null''',
        run_ids,
    )

    rows = {}                          # row_id => Row
    word_labels = defaultdict(list)    # word => list of (row_id, code)
    uf = UnionFind()                   # connects word strings into variants

    for (row_id, req_id, run_id, label, word,
         variant_label, variant, qualifier, notes) in cur:
        rows[row_id] = Row(row_id, req_id, run_id, qualifier, notes)

        members = []  # word strings appearing in this row

        # main side: label(s) apply to word(s)
        codes = [code_for(p) for p in split_cells(label)]
        for w in split_cells(word):
            for c in codes:
                word_labels[w].append((row_id, c))
            members.append(w)

        # variant side: variant_label(s) apply to variant(s)
        vcodes = [code_for(p) for p in split_cells(variant_label)]
        for w in split_cells(variant):
            for c in vcodes:
                word_labels[w].append((row_id, c))
            members.append(w)

        # everything in the same row is one variant group (edges from row_id);
        # identical word strings across rows fuse groups (edges from word)
        for w in members[1:]:
            uf.union(members[0], w)

    con.close()

    # gather connected components: variant_id (root) => list of word strings
    raw_variants = defaultdict(list)
    for w in word_labels:
        raw_variants[uf.find(w)].append(w)

    def code_key(codes):
        return [CODE_RANK.get(c, len(CODE_ORDER)) for c in codes]

    # build the printable groups
    blocks = []
    for words in raw_variants.values():
        entries = []
        for w in words:
            codes = sorted({c for _rid, c in word_labels[w]},
                           key=lambda c: CODE_RANK.get(c, len(CODE_ORDER)))
            entries.append(Entry(codes, w))
        entries.sort(key=lambda e: (code_key(e.labels), e.word))

        group_codes = {c for e in entries for c in e.labels}

        # output-only filter: keep only groups whose codes are all easy, and
        # drop the whole group if any spelling is both American and British
        if easy_only:
            if not group_codes <= EASY_CODES:
                continue
            if any({'A', 'B'} <= set(e.labels) for e in entries):
                continue

        # output-only filter: keep only groups with a US- and a UK-side spelling
        if regional_only:
            if not (group_codes & AMERICAN_CODES and group_codes & BRITISH_CODES):
                continue

        # collect distinct qualifiers / notes from every row in the group
        rids = sorted({rid for w in words for rid, _c in word_labels[w]})
        quals, notes = [], []
        for rid in rids:
            q = (rows[rid].qualifier or '').strip()
            n = (rows[rid].notes or '').strip()
            if q and q not in quals:
                quals.append(q)
            if n and n not in notes:
                notes.append(n)

        lines = [f'{" ".join(e.labels)}: {e.word}' for e in entries]
        lines += [f'#= {q}' for q in quals]
        lines += [f'## {n}' for n in notes]

        blocks.append((entries[0].word, '\n'.join(lines)))

    # order groups by the first word of each (already sorted) group
    blocks.sort(key=lambda b: b[0])
    print('\n\n'.join(block for _first, block in blocks))


if __name__ == '__main__':
    main()
