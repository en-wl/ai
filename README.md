As discussed in https://github.com/en-wl/wordlist/discussions/429, I am now
using LLMs to help decide whether or not to add a word.  For full transparency,
here are the instructions and files that I use for a ChatGPT project.  

I am constantly tweaking the instructions so these instructions may not
represent the exact ones I used for any single GitHub issue, but they should
provide similar results.  

To use with ChatGPT, use the file contents in instructions.txt as the project
instructions and upload the following 4 files as part of the project.  

* `word_evaluation_guidelines.md`
* `word_formatting_guidelines.md`
* `file_format.md`
* `scowl_sample.txt`

You can then just give a list of words or a GitHub issue link and it will
create a report for you.  

For best results, use the "thinking" model.  

I have also used Google Gemini and got similar results.  However, since Google
Gemini does not support projects, you need to adjust the instructions slightly
and give them as the initial prompt.  With that prompt, also upload the four
files above.  After that you should be able to give words in follow-up prompts.
Again, you likely will need to use the "Thinking" model.  

The instant or fast models can be usable, but the results may not always be
formatted right, and if you give it too many words at once it may refuse to do
anything at all without additional instructions.  They can, instead, be used
to get quick answers if you tell it to follow the normal instructions but
instead just report on the SCOWL size chosen.  Keep in mind though that the
results may be the same as using the "thinking" model, especially if a
web-search is required to get up-to-date info.
