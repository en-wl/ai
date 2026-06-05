import sys

sys.path.append("../")

from req._request import *


sample = '''
accelerometer
acidification
adjustability
adobo
adoptee
aesthetician
aikido
alarmism
alopecia
antidiscrimination
antiestablishment
antifeminist
antigravity
antimicrobial
antiterrorism
arabica
arborist
arcana
archrival
armoire
arrestee
arthouse
asana
attaboy
auteur
autofocus
baba
bachelorette
backbeat
backcourt
backflip
backflow
backlight
backsplash
backstab
backstabbing
backswing
badass
bagger
baller
bandmate
bartend
basketful
deglaze
delegitimize
demonisation
descriptor
designee
dialler
diffuser
digitisation
dirtbag
disempower
disinvite
disruptor
yogurt
'''.splitlines()

#resp = send_prompt('gemma-4-31b', sample)
#resp = send_prompt('gpt-5.3-chat', sample)

run = Run('gemma-4-31b', len(sample))
#run = Run('gpt-5.5', len(sample))

resp = Request(run, 0, sample).send()

if resp.error_msg:
    print(f"ERROR: {resp.error_msg}")

reasoning = resp.data["choices"][0]["message"].get("reasoning", None)
if reasoning is None:
    reasoning = resp.data["choices"][0]["message"].get("reasoning_content", None)

if reasoning:
    print(reasoning)
    print("===")

print(resp.content)


