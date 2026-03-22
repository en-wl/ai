#!/bin/sh

set -e

cat <<'EOF'
## Formatting Rules

- Use Markdown for lists, tables, and styling.
- When formatting Markdown tables:
   - Always include the mandatory separator row (e.g., `|---|---|`) between
     the header and the data. Ensure every row starts and ends with a pipe `|`
     character.
   - Do not attempt to line up columns; keep the table compact by minimizing
     the use of unnecessary whitespace.


## Overview and Instructions

I am going to give you some English words to evaluate, Most of the fields in
the table should be self-explanatory.  Please use the `uid` in any output when
referencing that lemma.

If a POS is a single letter the exact POS is not known.  These POSes are:

```
  n: likely noun
  m: likely verb, possible noun
  a: adjective or adverb
  ?: unknown
```

If the POS is one of `n`, `m`, or `a` the POS was a best guess based on
derived forms found in the wordlist, evaluate the lemma with this is mind.

Words with the `?` POS are likely lemmas.  If the word is clearly not a lemma,
evaluate it anyway, but make a note of the actual lemma.

If the POS is not a single letter, the exact POS is known.  When an exact POS
is given, evaluate the word for the given POS only.  The exact POSes are one of
one of: noun (including proper-nouns), pronoun, verb, adj, or adv, conj, prep,
det, interj.


## Output

Return the results as a Markdown formatted table, with the following columns.

  - `uid`
  - `words`
  - `pos`
  - `size` -- one of `60`, `70`, `80`, or `excluded`
  - `borderline` -- `No` if there were no borderline decisions;
                    `60/70` or `70/80` if there was a size borderline decision;
                    `incl/excl` if there was an include/exclude decision;
                    if both borderlines cases apply, separate with a comma
  - `size_notes` -- one or two sentences justifying the size or exclude decision

Do not use any additional formatting for entries in the table.

Output at least one row for each input row.  Do not treat excluded words as
special cases; use the word "excluded" only in the size column and fill out
the other columns as you would if the word was included.

Always include original lemma given without modifications.  If the word was
clearly not a lemma than also include the lemma and seperate the two words
with a comma.

If an exact POS is given, do not correct it.  Mark the lemma as excluded if
the POS is invalid for the lemma.

If an exact POS was not given, replace the POS with the correct one.  If the
lemma has multiple POSes, use one row for each POS and evaluate each new POS
separately.

A header row for the table is required, but a legend is unnecessary.

After the table make a brief of any thing else of importance.
EOF

echo
echo
cat ../prompts/eval/inc.md

echo
echo
cat ../prompts/eval/size.md
