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
the table should be self-explanatory.  All entries in a single row of the
table should be evaluated together as a single lemma, please use the `uid` in
any output when referencing that lemma.

The POSes are:

```
  n: noun (including proper-nouns)
  v: verb
  aj: adjective
  av: adverb
```

Evaluate all lemmas given together as a single unit.

## Output

Return the results as a Markdown formatted table, with the following columns.

  - `uid`
  - `lemmas`
  - `pos`
  - `size` -- one of `60`, `70`, `80`, or `excluded`
  - `borderline` -- `No` if there were no borderline decisions;
                    `60/70` or `70/80` if there was a size borderline decision;
                    `incl/excl` if there was an include/exclude decision;
                    if both borderlines cases apply, separate with a comma
  - `size_notes` -- one or two sentences justifying the size or exclude decision

Do not use any additional formatting for entries in the table.

Output one row for each input row.  Do not treat excluded words as special
cases; use the word "excluded" only in the size column and fill out the other
columns as you would if the word was included.

A header row for the table is required, but a legend is unnecessary.

After the table make a brief of any thing else of importance.
EOF

echo
echo
cat ../prompts/eval/inc.md

echo
echo
cat ../prompts/eval/size.md
