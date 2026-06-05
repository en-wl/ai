import sys

sys.path.append("../")

from req._request import *

class VariantRequest(Request):
    def process_response(self, response):
        content = response.content
        data_match = re.search(r'#\s*Data', content)
        notes_match = re.search(r'#\s*Notes', content)

        model_notes = None
        if notes_match:
            notes_text = content[notes_match.end():].strip()
            if notes_text:
                model_notes = notes_text

        rows = []
        if data_match:
            data_start = data_match.end()
            data_end = notes_match.start() if notes_match else len(content)
            data_section = content[data_start:data_end]

            for line in data_section.splitlines():
                line = line.strip()
                if not line or not line.startswith('|'):
                    continue
                if re.match(r'\|[-| ]+\|', line):
                    continue
                cells = [c.strip() for c in line.split('|')]
                if cells and cells[0] == '':
                    cells = cells[1:]
                if cells and cells[-1] == '':
                    cells = cells[:-1]
                if len(cells) < 6:
                    continue
                if cells[0].lower() == 'label':
                    continue
                keys = ['label', 'word', 'variant_label', 'variant', 'qualifier', 'notes']
                row = {k: ('' if v == '-' else v) for k, v in zip(keys, cells)}
                rows.append(row)

        return rows, model_notes

    def store_result(self, conn, req_id, response, processed):
        rows = processed
        covered = set()

        for row in rows:
            if row['word']:
                covered.add(row['word'])
            if row['variant']:
                for token in row['variant'].split(','):
                    token = token.strip()
                    if token:
                        covered.add(token)
            conn.execute(
                "INSERT INTO results (req_id, run_id, label, word, variant_label, variant, qualifier, notes)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (req_id, self.run.run_id,
                 row['label'], row['word'], row['variant_label'],
                 row['variant'], row['qualifier'], row['notes'])
            )

        for w in self.data:
            if w and w not in covered:
                conn.execute(
                    "INSERT INTO results (req_id, run_id, word) VALUES (?, ?, ?)",
                    (req_id, self.run.run_id, w)
                )

        return response, None

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

resp = VariantRequest(run, 0, sample).send()

if resp.error_msg:
    print(f"ERROR: {resp.error_msg}")

reasoning = resp.data["choices"][0]["message"].get("reasoning", None)
if reasoning is None:
    reasoning = resp.data["choices"][0]["message"].get("reasoning_content", None)

if reasoning:
    print(reasoning)
    print("===")

print(resp.content)


