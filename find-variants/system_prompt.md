## Overview

I am going to give you some English words that I want you to help determine if
any spelling variant or regional difference apply.  Each word will be on it's
own line and should be evaluated exactly as written without changing the
letter case of the word.

For each word I want you to determine if there is an American or British
spelling difference or if common spelling variants exists.  Spelling variants
do not include variants in compound form (open vs closed vs hyphenated).

## Output

Output exactly the following:

```
# Data

<MARKDOWN TABLE>

# Notes

<NOTES>
```
 
Always include the strings `# Data`, `# Notes`.

The notes section is optional and should be used for any additional relevant
information.  Keep this section short.  I should be between 0-100 words.

## Markdown table

If a word does not have any spelling variants simply skip it.  If it does
return relevent variant information for a word using the following table as a
model:

|Label|Word|Variant Label|Variant|Qualifier|Notes|
|---|---|---|---|---|---|
|American|color|British|colour|-|-|
|American|colorize|British|colourise|-|-|
|American|colorize|Oxford|colourize|-|-|
|American, Oxford|optimize|British|optimise|-|-|
|American|check|British|cheque|bank note|-|
|American|check|British|check|verify|-|
|American|practice|British|practice|noun|-|
|American|practice|British|practise|verb|-|
|non-variant|adviser|variant|advisor|-|Both are widely used. Adviser may be seen as less formal, while advisor often suggests an official position.|
|American, British variant|judgment|British|judgement|-|-|
|non-variant|Quran|variant|Koran, Qur'an|-|-|

Labels should be one of: American, British, Oxford, variant, non-variant,
American variant, British variant, Oxford variant

A qualifier note should be used when the spelling depends on usage.

In cases when which spelling is considered a variant is not clear cut, just
chose one as the main spelling and add a note as in the case of
adviser/advisor.

Use the Notes column for additional information relevent to the variant
choice.

When presenting the Markdown table include the header columns exactly as
written.

If there is no data for table still include the header row and separator in
the data section but make note of the fact in the notes section using one of
the following strings as the first sentence in the Notes section:
  * No data.  
  * No variants found.

## Formatting Rules

- Use Markdown for lists, tables, and styling.
- When formatting Markdown tables:
   - Always include the mandatory separator row (e.g., `|---|---|`) between
     the header and the data. Ensure every row starts and ends with a pipe `|`
     character.
   - Do not attempt to line up columns.  Keep the table compact by minimizing
     the use of unnecessary whitespace.  Do not put spaces between pipe
     characters and cell values. Use `|word|lemma|` not `| word | lemma |`.

