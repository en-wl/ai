## Overview

I am going to give you some English nouns along with the proposed plural, I
want you to identify if the plural has a natural, conventional count use.

I want you to classify each plural as one of:
  - natural
  - specialized
  - contrived
  - ungrammatical
  - gerund
  - invalid

In addition if the plural given is a rare or archaic form add the string 
`, rare form`:

Be conservative. Mark a plural as `natural` only if an ordinary educated
speaker that is familiar with the singular form, might reasonably use it.  Do
not mark a plural `natural` merely because it is morphologically possible or
because it could be used creatively.  If the plural only sounds natural when
used in technical or academic discourse, use `specialized`.  Do not use
`specialized` if the word itself is specialized, but the plural is natural for
that word.  If the plural is morphologically possible, and neither `natural`
or `specialized` apply use `contrived`.

Reserve `gerund` for pure verb gerunds.  If the word has an independent noun
usage use one of `natural`, `specialized` or `contrived` instead.

Use `invalid` if the input is invalid for some reason.

Calibrate your judgments using these examples:

  - wool, wools: natural
  - military, militaries: natural
  - hyperplane, hyperplanes: natural
  - weakness, weaknesses: natural
  - toothpaste, toothpastes: specialized
  - music, musics: specialized
  - knowledge, knowledges: specialized
  - deceleration, decelerations: specialized
  - abnegation, abnegations: contrived
  - strangeness, strangenesses: contrived
  - yellowness, yellownesses: contrived
  - pants, pantses: ungrammatical
  - building, buildings: natural
  - running, runnings: contrived
  - refusing, refusings: gerund
  - tuba, tubas: natural
  - tuba, tubae: natural, rare form
  - formula, formulae: natural
  - color, colours: invalid (plural is for colour not color)
  - colorize, colorizes: invalid (colorize is not a noun)
  - zgxptk, zgxptks: invalid (not a valid word)

## Formatting Rules

- Use Markdown for lists, tables, and styling.
- When formatting Markdown tables:
   - Always include the mandatory separator row (e.g., `|---|---|`) between
     the header and the data. Ensure every row starts and ends with a pipe `|`
     character.
   - Do not attempt to line up columns.  Keep the table compact by minimizing
     the use of unnecessary whitespace.  Do not put spaces between pipe
     characters and cell values.

## Input

Each word/plural pair will be given as a markdown table along with a unique
`uid` that must be preserved in the output.

Example input:

|uid|noun|plural|
|---|---|---|
|17|wool|wools|
|3|pants|pantses|
|52|tuba|tubae|
|22|color|colours|

## Output

Return the results as a Markdown table with the following columns.

  - `uid`
  - `plural`
  - `category`
  - `notes` -- optional notes, use sparingly

The first two columns should be verbatim copies from the input table.  Leave the
singular form out and only repeat the plural.  `category` is the string as
previously described in the overview section.

Example output:

|uid|plural|category|notes|
|---|---|---|---|
|17|wools|natural|-|
|3|pantses|ungrammatical|-|
|52|tubae|natural, rare form|-|
|22|colours|invalid|plural is for colour not color|

A header row for the table is required, but a legend is unnecessary.

Do not use any additional formatting for entries in the table.  Ensure each
row has exactly 4 columns.  Do not skip entries, if unsure use `invalid` as
the category.

Start the output with the markdown table; do not include any text before the table.

Any notes of importance can be provided after the markdown table.  Keep it
short.  The additional notes should be between 0-100 words.
