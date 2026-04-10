## Overview

I am going to give you some English words that I want assigned the correct
POS.  Most of the fields in the table should be self-explanatory.  Please use
the `uid` in any output when referencing that lemma.

The input POS will be one of:

```
  n: likely noun (including proper-nouns)
  v: likely verb
  m: likely verb, possible noun
  a: adjective or adverb
  ?: unknown
```

The words given are the likely lemmas and POSes from processing a strict list
of isolated words.  The POS is a best guess based on whether related inflected
forms were also found elsewhere in that same wordlist.

The `m` POS is used when all verb forms are found, but a noun form can not be
ruled out due to lack of POS information on the lemma.

The `?` is used for leftover words.  As such, words with the `?` POS are
likely lemmas, but could be an inflected form the script failed to pick up on.

If a `-ed` or `-ing` form of a word is given with a `?` POS lean strongly
towards evaluating the word as an adjective or noun rather than assuming it an
inflected form of a verb.

If the POS is not `?` then assume the word is a lemma.  A plural of a noun
labeled with a `n` POS is possible, any other inflected forms labeled with the
base form's POS is unlikely.

Do not strip derivational affixes when identifying the lemma; only resolve
inflectional morphology.  For example, reduce 'misallocating' to
'misallocate', but do not strip the prefix to make it 'allocate', and do not
reduce 'happiness' to 'happy'.

The words given will have the correct letter case.  If a common word starts
with a capital letter, assume it is a name of some sort.

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
it to a POS of `?` instead of skipping the UID.

### `lemma` field instructions

If, after applying the guidelines in the overview section, the lemma evaluated
is the base form of the inflected word, provide the lemma in the `lemma`
field and use the new lemma when assigning the POS.

Once the lemma is determined, try to evaluate the word exactly as written, do
not change the letter case or spelling.  If that exact word is still not
recognized and case corrections are needed, provide the case-corrected lemma.
Do not fix the spelling of the word in any other way.

Do not leave the `lemma` field blank, and do not evaluate any other forms of
the word beyond the allowed transformations in this section.  If the `lemma`
field is not yet populated then repeat the word and evaluate the word exactly
as written.

If you do not recognize the word, use `?` as the POS.

### `pos` field instructions

Replace the guessed (i.e. input) POS with the correct one.  If the lemma has
multiple POSes that are compatible with the input POS, output one row for each
POS; do not just choose the most probable one.  Do not include more than one
POS in the `pos` column.  Use the same UID for each row.

When determining if a POS is compatible consider all possible forms of the
word that might get flagged under the input POS tag:

- If the input POS is `n` or `v` then the lemma is a noun or verb
  respectively, and not the other one.  Other POSes of the lemma are also
  possible and should be considered.

- If the input POS is `m` then it at least a verb.  All other POSes, including
  a noun, are also possible and should be carefully considered.

- If the input POS is `a` it is an adjective or adverb and any other POS is
  unlikely.

- If the input POS is `?` it could be any POS.  However, it is unlikely a POS
  that regularly takes on inflected forms.

Obscure or highly uncommon senses of the lemma not considered compatible
unless the input POS forces the word to be interpreted that way.  When this is
the case, include the string `Obscure!` somewhere in the `notes` column and
choose a POS compatible with the input POS based on the other rules.

The POS tag is still a guess.  If the POS tag violates the above rules (for
example, a `m` POS that is not at least a verb), then include the string
`Wrong!` somewhere in the `notes` column and provide the correct POS in the
`pos` column.  An unrecognized word is not considered wrong in this sense and
should simply get a POS of `?` as per previous rules.

Do not use `Obscure!` or `Wrong!` if the input POS is `?`.

In addition to assigning the POS, if the word is normally only used as part of
a larger expression, name, or bound form, for example "Los", "Angeles", or
"habeas" assign it its normal POS but include the string `Fragment.` somewhere
in the `notes` column.

Use `Fragment.` only for items that are not normally used as standalone lemmas
in the English language.  Do not use `Fragment.` for ordinary standalone
names, places, abbreviations, or dictionary words, even if they often appear
as part of larger names or compounds.

### `pos_class` field instructions

The `pos_class` field is a string used to qualify the POS when the word is a
proper noun/adjective or an abbreviation.  It should be one of:

    person: first name of person
    surname: last name of person
    place: geographical place: United States, Maryland, Boston, etc.
    name: a proper noun/adjective when no other label is a good fit

    demonym: related to a place; both nouns and adjectives

    acronym: an abbreviation that functions syntactically as a standalone word

    none: normal dictionary word, no qualification needed

Proper nouns such as Monday, September, and Easter are considered dictionary
entries and get a class tag of `none`.

If a word is an acronym (or initialism) that functions syntactically as a
standalone word then assign the `pos` field the normal POS of the word and use
`acronym` for the class tag.

If the word is not a proper noun/adjective, and does not qualify for the
`acronym` tag, then it should get a class tag of `none`.

If the corrected word is all lowercase and has a class tag other than `none`,
provide a brief explanation justifying why an all lowercase word is considered
a proper noun/adjective or acronym.

If multiple class tags apply, choose the most prominent one.  If a name is
also an abbreviation then the appropriate proper noun tag gets precedence.  If
different class tags apply depending on the sense of the word, use one output
row for each sense.  Do not include multiple `pos_class` tags in a single row.
