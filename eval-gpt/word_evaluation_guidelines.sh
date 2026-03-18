#!/bin/sh

set -e

cat <<'EOF'
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

EOF

echo
cat ../prompts/eval/inc.md

echo
echo
cat ../prompts/eval/infl.md

echo
echo
cat ../prompts/eval/size.md

echo
echo
cat ../prompts/eval/variants.md
