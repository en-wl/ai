As discussed in https://github.com/en-wl/wordlist/discussions/429, I am now
using LLMs to help decide whether or not to add a word.

I use the chat interface for a initial assessment and then ask multiple other
LLMs for a second opinion before making my final decision.

The prompts for the chat interface are in `eval-gpt`.  The scripts I use for
asking other LLMs are in `size-score`.
