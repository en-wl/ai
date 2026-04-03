## Overview

I am going to give you some English words that I want assigned a correct POS.
Most of the fields in the table should be self-explanatory.  Please use the
`uid` in any output when referencing that lemma.

The input POS will be one of:

```
  n: likely noun (including proper-nouns)
  v: likely verb
  m: likely verb, possible noun
  a: adjective or adverb
  ?: unknown
```

The words given are the likely lemmas and POSes from processing a raw list of
words.  The POS is a best guess based on derived forms found in the wordlist.
Words with the `?` POS are likely lemmas, but could be an inflected form the
script failed to pick on.

The words given will have the correct letter case.  If a common word starts
with a capital letter, assume it is a name of some sort.

If a `-ed` or `-ing` form of a word is given with a `?` POS lean strongly
towards evaluating the word as an adj. or noun rather than assuming it an
inflected form of a verb.

## Formatting Rules

- Use Markdown for lists, tables, and styling.
- When formatting Markdown tables:
   - Always include the mandatory separator row (e.g., `|---|---|`) between
     the header and the data. Ensure every row starts and ends with a pipe `|`
     character.
   - Do not attempt to line up columns.  Keep the table compact by minimizing
     the use of unnecessary whitespace.  Do not put spaces between pipe
     characters and cell values. Use `|word|lemma|` not `| word | lemma |`.

## Output

Return the results as a Markdown table with the following columns.

  - `uid`
  - `word`  -- the original word as given
  - `lemma` -- the lemma of the word
  - `pos` -- the corrected POS, one of: `noun` (including proper-nouns), 
               `pronoun`, `verb`, `adj`, `adv`, `conj`, `prep`, `det`, 
               `interj`, `abbr`, `?`
  - `pos_class` -- see below
  - `notes` -- optional notes

A header row for the table is required, but a legend is unnecessary.

After the table make a brief note of any thing else of importance.

## Instructions

Do not use any additional formatting for entries in the table.  Ensure each
row has exactly 6 columns.

Output at least one row for each UID.  If you do not recognize the word assign
it to a pos of `?` instead of skipping the UID.

### `lemma` field instructions

If the input POS is `?` and the most common form of the word an inflected form
of some other lemma, provide the lemma in the `lemma` field, and assign it the
POS of the lemma.

In all other cases simply repeat the word in the `lemma` field.

Do not correct the spelling, compound form (open vs closed vs hyphenated), or
the letter case of the word.  Except in the specific case of `?` being an
inflected form, always evaluate the word as is.  If you do not recognize the
word as is use `?` as the POS.

### `pos` field instructions

Replace the guessed (i.e. input) POS with the correct one.  If the lemma has
multiple POSes that are compatible with the input POS, output one row for each
POS; do not just chose the most probable one.  Do not include more than one
POS in the `pos` column.  Use the same UID for each column.

If the word is normally only used as part of a larger expression, name, or
bound form, for example "Los", "Angeles", or "habeas" assign it its normal POS
but include the string `Fragment.` somewhere in the `notes` column.

Use `Fragment.` only for items that are not normally used as standalone
lemmas.  Do not use `Fragment.` for ordinary standalone names, places,
abbreviations, or dictionary words, even if they often appear inside larger
names or compounds.

If the input POS is `n` or `v` than the POS is a noun or verb respectively and
not the other one.  If the input POS is `m` then it is at least a verb, but it
might also be a noun so carefully consider both.  For any of `n`, `v`, or `m`,
the lemma might also be some other POS (that is not a noun or verb), including
an adj. or adv.

If the input POS is `a` it is an adj. or adv. and any other POS is unlikely.

If the input POS is `?` it could be be any POS.

Obscure POSes for the lemma are not considered compatible unless the input
POS is also obscure.

If the input POS is obscure, include the string `Obscure!` somewhere in the
`notes` column.

If the input POS is clearly wrong (including the case when the input POS is
`m` and the word is not a verb) include the string `Wrong!` somewhere in
`notes` column.

Do not use `Obscure!` or `Wrong!` if the input POS is `?`.

### `pos_class` field instructions

The `pos_class` field is a string used to qualify the POS.  It should be one of:

    person: first name of person
    surname: last name of person
    place: geographical place: United States, Maryland, Boston, etc.
    name: a proper noun/adj when no other label is a good fit

    demonym: person or people related to a place

    abbr: an abbreviation that takes on inflected forms such as FAQs

    none: normal dictionary word, no qualification needed

Proper nouns such as Monday, September, and Easter are considered dictionary
entries and get a class tag of `none`.

If multiple class tags apply chose the most promote one.  If a name is also an
abbr then the `name` tag gets precedence.  If different class tags apply
depending on the sense of a word, use one output row for each sense.  Do not
include multiple `pos_class` tags in a single row.
