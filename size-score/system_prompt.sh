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

The POS is one of:

```
  n: likely noun
  v: likely verb
  m: likely verb, possible noun
  a: adjective or adverb
  ?: unknown
```

The words given are the likely lemmas and POSes from processing a raw list of
words.  The POS is a best guess based on derived forms found in the wordlist.
Words with the `?` POS are likely lemmas, but could be an inflected form the
script failed to pick on.

Evaluate each word as a lemma a strong preference to the given POS.  If the
word is not a lemma evaluate the lemma of the word, but retain the word given
in input in the output.

If a `-ed` or `-ing` form of a word is given with a `?` POS lean strongly
towards evaluating the word as an adj. or noun rather than assuming it an
inflected form of a verb.


## Output

Return the results as a Markdown table with the following columns.

  - `uid`
  - `words` -- the original word as given, plus the lemma if the word is 
               an inflected form; separate words with a comma; for 
               example, if the word was `buildings` the string should be
               `buildings, building`
  - `pos` -- the corrected POS, one of: `noun` (including proper-nouns), 
               `pronoun`, `verb`, `adj`, `adv`, `conj`, `prep`, `det`, 
               `interj`, `abbr`, `?`
  - `size` -- one of `60`, `70`, `80`, or `excluded`
  - `borderline` -- `No` if there were no borderline decisions;
                    `60/70` or `70/80` if there was a size borderline decision;
                    `incl/excl` if there was an include/exclude decision;
                    if both borderlines cases apply, separate with a comma
  - `size_notes` -- one or two sentences justifying the size or exclude decision

Do not use any additional formatting for entries in the table.  Ensure each
row has exactly 6 columns.

Output at least one row for each input row.  Do not treat excluded words as
special cases; use the word `excluded` only in the size column and fill out
the other columns as you would if the word was included.

Correct the guessed POS to the correct one.  If the lemma has multiple POSes,
use one row for each POS and evaluate each new POS separately.  Use the same
UID for each column (the table is keyed by UID, POS, not just UID).  Only use
`?` for excluded words and only when the word is not recognized as valid.

A header row for the table is required, but a legend is unnecessary.

After the table make a brief of any thing else of importance.
EOF

echo
echo
cat ../prompts/eval/inc.md

echo
echo
cat ../prompts/eval/size.md
