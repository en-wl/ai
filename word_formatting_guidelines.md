# Encoding & Output Guidelines (Step 2)

## 1. Scope and dependencies

* Step 2 starts **after** Step 1.
  Step 1 has already decided what each lemma is, which POS it has, how it is
  used, which forms exist, and which SIZE band (60/70/80) it belongs to.

* This guide tells you how to:

  * Turn those results into SCOWL entries for this project.
  * Structure the response (summary + SCOWL groups).

* For all syntax and low-level format details, follow:

  * `file_format.md`
  * `scowl_sample.txt`

* Output must be a clean report suitable for pasting directly into a GitHub
  issue comment, with no restatement of these guidelines or commentary on the
  process.


## 2. Inputs and main task

For each lemma–POS from Step 1 (lemmas, POS, senses, inflectional/derived
forms, spelling and dialect usage) create a GROUP for that lemma–POS as
defined in `file_format.md`.  Use `scowl_sample.txt` as guide to understanding
the specifications.

Project-specific constraints:

* Do not use the special `m`, `a`, `n_v`, or `aj_av` POS tags; keep noun,
  verb, adjective, and adverb in separate GROUPs.

* When building the `SCOWL_INFO` grammar element, use only `SIZE`. The other
  optional parts are out of scope for this task.

* The optional `USAGE-NOTE` grammar element is out of scope for this task.

* Do not add group specific comment lines (lines starting with `##`)


## 3. Which inflected and derived forms to encode

Step 1 has already identified which inflected and regularly derived forms
exist and are used.

Step 2 decides which of those to encode in the SCOWL derived segments.

Follow the per-POS rules below.

### 3.1 Nouns

* **Base form**

  * The lemma’s base form is the **singular**.

* **Plural**

  * Include the plural form if the plural is genuinely used in real text.
  * For **proper names**, default to **not** including the plural unless there
    is a good reason to include it.  (This does not apply to broader
    categories like demonyms, where plurals are normal.)
  * Omit the plural for mass/abstract nouns whose plural is extremely rare or
    unnatural.

* **Possessives**

  * Include the **singular possessive** if the noun frequently functions as a
    possessor in ordinary text.
  * Include the **plural possessive** only if:

    * The plural itself is included, **and**
    * The plural is **irregular** in a way that changes the possessive formation
      so that `'s` must be added instead of just a final apostrophe.

### 3.2 Verbs

* Include the usual set of forms when they are standard and used.
* Do not add non-standard or artificial inflections just because they are
  mechanically derivable.

### 3.3 Adjectives and adverbs

* Include comparative and superlative forms when they are actually used.
* Omit comparative/superlative forms if they are unnatural or essentially
  unattested in ordinary text.


## 4. Spelling variants (project-specific rules)

Everything not mentioned here should follow `file_format.md` and Step 1’s
dialect profile.

### 4.1 General Rules

* Consider all applicable SPELLING codes; ignore the implies (`B` implies `Z`,
  etc.) rules as they are strictly for output compression.  Also, note that
  the `B` and `Z` codes are two distinct British sub-dialects.

* Encode all alternative spellings, except for the limited omission in Section
  4.2.  Assign the variant level for each spelling separately within each
  SPELLING (i.e. dialect).  Do not mix `_` with other SPELLING codes within
  the same group.  Use `_` only when none of the spellings in the group are
  dialect-associated.

* When two different compound word forms are considered equal variants give
  preference to the closed form; otherwise, treat differences in compound
  forms as ordinary spelling variants.

* When creating new entries, only use the `=`, `?`, `v`, `V`, `-`, or `@`
  VARIANT-LEVEL codes.


### 4.2 Uncommon cross-dialect variants

To keep groups from becoming cluttered, you may omit certain cross-dialect
spelling variants when **all** of the following are true:

1. The spelling would be assigned an uncommon variant level in the
   dialects it covers (for example, it would clearly fall into a
   rare/archaic/non-standard category for that dialect).

2. The same lemma–POS already has a more standard spelling for another dialect
   within the same group.

3. The omitted spelling does not have clear independent value (e.g., no strong
   historical, cultural, or domain-specific importance beyond being a rare
   variant).


## 5. Signature vs Extra classification

For each lemma-POS that Step 1 includes, Step 2 also labels it as Signature or
Extra.  Do not spend much time on this distinction—if you are unsure, make a
reasonable quick choice and move on.

* **Signature**:

  * A small subset of additions that are noteworthy beyond mere validity, for example:

    * Clear neologisms or relatively new coinages with visible impact.
    * High-impact internet or online-culture terms.
    * Terms marking important conceptual or social shifts where users would
      particularly expect spell-checker support.

  * Being technical or domain-specific by itself is **not** enough to be
    Signature.

* **Extra**:

  * All other valid additions:

    * Normal domain terms.
    * Routine derivatives and compounds.
    * Most lemmas will be Extra.

When in doubt, treat a lemma as **Extra** and reserve **Signature** for
clearly special cases.

This classification is used only to structure the output for this project.


## 6. Output structure and formatting

Step 2 produces both a **summary** and **SCOWL groups** as text blocks.

### 6.1 Grouping by GitHub issue (when applicable)

When words come from one or more GitHub issues:

  * Group both the summary and output by issue.

  * After the section header for each issue also include:

    * A link back to the GitHub issue.

    * The following explanatory paragraph (exact text, but include all on a
      single line): **ChatGPT analyzes; see
      https://github.com/en-wl/wordlist/discussions/429. Note that size 60 is
      the normal spellchecker dictionary, 70 is the larger, and 80 is the "if
      it's a valid word" size.**

### 6.2 Summary section

Before the SCOWL entries, provide a summary of decisions.

* Group entries by SIZE (60, then 70, then 80). Within each SIZE, list
  Signature entries first, then Extra. Within each of those, sort by lemma.
  You may group multiple POS under one lemma when the POS differences are not
  notable.

* For each included lemma in the summary:

  * After the word, and on a single line state: (1) the SIZE, (2) "Borderline:
    A/B → X" or "not borderline" (lowercase), and (3)
    Signature or Extra.
  
  * Optionally provide a short primary-sense gloss (1–2 words) if useful.

  * What motivated the SIZE decision.  Be sure to call out any borderline
    decisions and the rationale.

  * If the word has variants within a SPELLING dialect explain (1) how the
    primary spelling was chosen and (2) the motivation for choosing the
    variant-level for alternative spellings.

* If there are any excluded lemmas (if present in the prompt), list them
  separately with a brief reason (e.g., “misspelling only”, “too obscure”,
  “transient meme form”).

### 6.3 SCOWL entries

Output the **Signature** and **Extra** words in fenced `text` blocks.  Give
each block its own subsection.  If a subsection would be empty, omit that
subsection entirely (no heading, no empty block).

Within each `text` block:

* Order groups by SIZE: 60, then 70, then 80; then within each SIZE, sort
  groups alphabetically by lemma, then by POS (human-expected order).

* Follow all syntactic rules from `file_format.md`

* Do not repeat the lemma in the derived segment; only derived forms (if any)
  go after the POS tag.

* If a GROUP contains only a single `LINE`, omit the `_` SPELLING code as it
  optional in those cases.

* Separate groups by a single blank line.  Do not insert blank lines inside a
  group; that would incorrectly signal a new group.

* Use two blank lines only for high-level visual breaks if deemed helpful.
  (For example between SIZE sections.)

* Preserve the layout exactly as emitted (including blank lines), so that
  downstream tooling can parse the groups reliably.
