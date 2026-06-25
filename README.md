As discussed in https://github.com/en-wl/wordlist/discussions/429, I am now
using LLMs to help decide whether or not to add a word.  I am also now using
LLMs to help with a number of other word related decisions.

The chat interface for size decisions is now available as GPT at
https://chatgpt.com/g/g-6972895467f88191b57a7d071a15b5bf-esdb-word-evaluation.
The prompts used for that GPT are in `eval-gpt`.

The rest of this repo contains code to programmatically query LLMs though an
API.

The `req` dir contains the base code for the other LLM tasks.  The other tasks
are as follows:

* `size-score`: scripts to ask other LLMs what size a word should be to get a
  second opinion.  It used the same prompts as the GPT.

* `size-score-simple`: a simplified version of the size-score task

* `assign-pos`: scripts to ask LLMs what POS a lemma should be assigned

* `find-variants`: scripts to ask LLMs to identify variants

* `plurals`: scripts to ask LLMs to classify possible plurals
