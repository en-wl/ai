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
