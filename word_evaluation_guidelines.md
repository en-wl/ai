# Word Evaluation Guidelines

This guide is for lexical evaluation only: decide what the word or expression
is, how it is used, and which forms exist, and ignore any specific wordlist
format or coding scheme while doing so.

Other documents may describe how to turn these evaluations into concrete
entries; that step is outside the scope of this guide.


## Casing and abbreviations

### Casing

* Always recase to the canonical casing for each lemma.
* Do not trust the casing in the prompt.
* Avoid redundant casing variants that add no value beyond what tools can
  generate.

### Abbreviations

When the prompt supplies an abbreviation in a non-canonical way
(e.g., wrong casing or missing final period):

1. Normalize the form (case and punctuation) and evaluate that canonical form.
2. Include the canonical form if it meets the general inclusion criteria; do not
   omit it solely because the prompt showed an unpunctuated or lowercased
   variant.


## [inc] Lemma inclusion decisions

### Include when

Include a candidate lemma when the following are true for the English language:

- It is a real word or stable multi-word expression in current use.

- It appears in mainstream or domain-appropriate references (standard
  dictionaries and/or consistent attested usage).

- It is reasonably expected that users in its domain would prefer not to see it
  flagged by a spell checker.

- If it is a derivative (e.g., affixed form), it is a natural and useful
  extension of an already-accepted lemma.

- It is a real, stable personal name (given name or surname) or place name
  that is attested beyond a single idiosyncratic use.

- It is an abbreviation/initialism that a typical user might reasonably write in
  casual prose (emails, issue trackers, comments, blog posts, internal docs).

### Exclude when

Exclude a candidate when any of the following is true for the English language:

- It is just a misspelling or ad-hoc joke form, not a real lexical item.

- It is so obscure and technical that even domain users are unlikely to expect
  spell-check support.

- It is a short-lived meme spelling or fad where usage appears transient.

- It is a redundant form whose behavior can be generated mechanically (e.g.,
  casing variants), unless there is a specific reason to encode it.

- It is an extremely obscure personal or place name (e.g., a one-off or
  family-only name, a very small locality, or a purely promotional development
  name) with no clear evidence of stable, wider recognition.

- It is an abbreviation whose use is overwhelmingly in real-time conversation
  (texting, Discord, Twitch/in-game chat) and is uncommon in emails, issue
  trackers, blog posts, or other slightly more formal writing.

### Borderline include/exclude

- If the item is clearly a genuine lexical item and at least modestly used,
  prefer inclusion unless there is a strong reason not to.

- When genuine inclusion and omission both remain plausibly defensible after
  applying the include/exclude rules, treat the case as borderline and record
  that uncertainty explicitly.


## [lemmas] Lemma structure, parts of speech, and senses

- Determine whether the spelling corresponds to one or more distinct lemmas:

     - Identify cases where the same spelling represents different words
       (e.g., noun vs. verb, different etymologies, or clearly distinct senses).

     - Distinguish only when the meanings differ enough for separate dictionary
       headwords.

- For each lemma, identify all parts of speech for which the lemma is
  productively used:

     - For nouns: confirm that the word is used as a count noun, mass noun, or both.

     - For verbs: confirm that the lemma behaves as a normal verb in modern usage.

     - For adjectives and adverbs: confirm that the word is used in that role in
       contemporary prose.

     - Exclude purely theoretical or archaic POS assignments not used in modern
       writing.

- Note whether any senses are sufficiently divergent that they require
  independent handling when generating inflected or derived forms:

     - Only separate senses when their inflectional behavior or usage domains
       differ materially.

     - If all senses share the same inflectional behavior, treat them together.


## [infl] Inflectional and regularly-derived forms

For each lemma–POS identified in [incl], gather the information below.

- Nouns:
     - Determine whether a plural form is attested and used.
     - If multiple plural forms exist, record all that are in genuine use.
     - Identify whether possessive forms occur in ordinary prose.
     - Note if the noun is normally uninflected (mass noun, invariant plural, etc.).

- Verbs:
     - Record the standard past tense, past participle, and present participle
       forms that are actually used.
     - Identify any accepted alternatives (e.g., “learnt / learned”) and whether
       they differ by dialect.
     - Determine whether the verb is defective (lacks some forms) or behaves
       irregularly.

- Adjectives and Adverbs:

     - Identify whether comparative and superlative forms are used and, if so,
       whether synthetic forms (“-er / -est”) or analytic forms (“more / most”)
       are standard.
     - If multiple comparative/superlative spellings exist in real usage, record
       the attested set.

- Proper Names:

     - Determine whether plural or possessive forms are used at all.
     - Note if derived forms (e.g., demonyms) exist and are part of ordinary usage.

- Common Derived or Morphologically Regular Forms

     - Identify any regularly formed derivatives that are clearly part of ordinary
       vocabulary (e.g., agent nouns, adjectival forms, adverbial forms), but do
       not generate speculative or unattested derivatives.
     - Record only forms that appear in mainstream edited prose.

Once a derived form is confirmed as a standard, attested form in mainstream
edited prose, record it.  Do not exclude such forms at this stage based on
their frequency.


## [size] SIZE selection (60, 70, 80)

### Overall Procedure

Assign each accepted lemma–POS a SIZE of 60, 70, or 80.

1) Evaluate SIZE 60 first.
   If at least one SIZE 60 criterion plausibly applies, assign SIZE 60.
   If SIZE 70 also plausibly applies, mark it as a 60/70 borderline case.

2) Only if no SIZE 60 criterion plausibly applies, evaluate SIZE 70.
   If at least one SIZE 70 criterion plausibly applies, assign SIZE 70.
   If SIZE 80 also plausibly applies, mark it as a 70/80 borderline case.

3) If neither SIZE 60 nor SIZE 70 is justified, assign SIZE 80.

When a case is borderline:

* Prefer the smaller size unless there is a clear, criteria-based reason to
  choose the larger size.

* Consider typo-masking as outlined in [typo] as one such reason.

* Consider nonstandard/objectionable status (to the extent that someone might
  take issue with inclusion) as one such reason.

Make a note of the SIZE chosen, whether it was borderline, and how it was
resolved.

Evaluate each lemma-POS independently; do not let other lemmas in the same
batch, their relative commonness, or their size outcomes influence the
current lemma's SIZE assignment.

### Size 60

A lemma can qualify for size 60 by satisfying any one of the criteria below
(or a strong combination of them):

-  A typical educated user would reasonably expect the word not to be flagged
   in general-purpose writing tools.

-  The lemma occurs in mainstream, general-audience writing -- including major
   news and magazine sites, general-interest blogs, and other widely read
   online contexts -- and is not confined to specialist technical or
   professional communities.  Dictionary subject/domain labels alone
   do not establish “confined”; use them only as supporting context alongside
   actual usage evidence.

-  It has clear cultural, social, or community significance (for example, as a
   term of art for a commonly discussed identity, movement, practice, or large
   online community) within an identifiable group, such that affected users
   would likely expect it not to be flagged, even if the term is not yet
   mainstream or widely recognized by the general public.

-  It is a well-established archaic or literary form that appears in widely
   read texts and is reasonably recognizable to many educated users.

-  It is a transparent derivative of an obvious 60-level base lemma and appears
   in general writing, or the reverse is true.

-  It is a well-established personal name (forename or surname) or a
   globally or nationally prominent place name (countries, major cities,
   well-known regions).

### Size 70

A lemma can qualify for Size 70 when it does not qualify for size 60, but by
satisfying any one of the criteria below (or a strong combination of them):

-  The lemma is clearly valid and dictionary-attested.

-  Used primarily within professional, academic, or technical domains and has
   not achieved broad, general-interest usage in writing aimed at
   non-specialist readers, nor become routine in everyday consumer-facing or
   mainstream online contexts.

-  It is recognizable to many educated users, but it is not routine in
   mainstream, general-audience writing.

-  It is a personal name with broad, stable attestation (not limited to a
   single family or small community) but not sufficiently well-established to
   meet size 60.

-  It is a place name that is primarily regional or local but has stable,
   wider recognition beyond the immediate locality (e.g., counties and
   equivalent administrative subdivisions, county seats, and larger
   cities/towns commonly referenced in state or regional contexts).

### Size 80

- Everything else that passes the inclusion test but cannot be
  clearly justified at 60 or 70.


## [typo] Typo-masking in borderline SIZE decisions

Typo-masking concerns the risk that including a rare or unusual word might make
it harder to spot typos in a much more common word. Treat typo-masking strictly
as a **secondary** consideration when deciding between adjacent SIZE values.

- Do **not** use typo-masking to decide whether a lemma is included or
  excluded. Inclusion decisions are based on lexical status and usage.

- Use typo-masking only when choosing between plausible SIZE values (typically
  60 vs 70 or 70 vs 80).

In particular:

1. When choosing between 60 and 70:

   - If a lemma otherwise satisfies the criteria for 60 but sits very close to a
     much more common word (especially in short forms or in contexts where
     typos are frequent), it may be safer to assign 70.

2. When choosing between 70 and 80:

   - If a lemma otherwise fits 70 but presents a strong typo-masking risk for a
     very common word, it may be safer to assign 80.

Very short items that are close in form to extremely common words may justify
a more cautious SIZE choice at the boundary.  Casing is important; for
example, proper all-caps acronyms are less likely to be confused with a
similar word than an unmarked or more casual all-lowercase acronym. Outside of
these boundary decisions, treat typo-masking as a minor consideration compared
to lexical reality and user expectations.


## [variants] Spelling and dialect usage profile

Check for all possible spellings of both the lemma and all derived forms.  If
a word is a compound word check for all possible forms: closed, open,
hyphenated.

When multiple spellings are found, build a structured picture of how each
spelling is used across dialects. In this stage, focus on usage facts
(dictionaries, corpora, major publications).

1. **For each lemma and spelling, by dialect (US, GB, Oxford, CA, AU):**

   - Whether the spelling is actually used in that dialect.

   - Whether the spelling appears in major dictionaries for that dialect
     (or in major general-purpose references if dialect-specific dictionaries
     are unavailable).

   Treat GB and Oxford as separate, distinct categories; do not merge them.

   Evaluate Canadian usage independently of both US and GB. Do not assume
   Canadian preference follows either side; note Canadian evidence on its own.

2. **Within each dialect, compare the spellings to each other.**

   For each dialect, record:

   - which spelling appears to function as the normal or default choice in
     practice (in government, education, mainstream media, large reference
     sites, and similar sources);

   - how dictionaries present each spelling (main form, “also” form, variant,
     regional, archaic, or non-standard labels);

   - qualitative prevalence of each spelling compared to the others
     (clearly more common, clearly less common, mainly technical or
     historical, and similar judgments);

   - the typical contexts where each spelling appears (general everyday
     writing, formal/published sources, professional or technical domains,
     historical materials, branding or proper-name contexts);

   - when different spellings dominate in different domains or contexts so
     that there is no single spelling clearly preferred across general usage
     in that region, which spelling an ordinary writer in that region would
     most naturally choose without following a specific style guide.
