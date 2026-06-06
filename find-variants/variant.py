import re

from req._request import Request
from req._loop import BatchSession, RequestResult


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
                # The model often overflows the note into one or more extra
                # columns (e.g. `...|-|-|<note>|`), leaving '-' in the declared
                # Notes column. Treat anything from the 6th cell onward as the
                # note so that content is never silently dropped.
                head = [('' if v == '-' else v) for v in cells[:5]]
                note = ' '.join(c for c in cells[5:] if c and c != '-')
                row = dict(zip(keys, head + [note]))
                rows.append(row)

        # A well-formed response with both sections but no data rows is a valid
        # empty result (the model found no variants) — not an error. Only flag
        # a malformed response, i.e. one missing a required section.
        if (not data_match or not notes_match) and response.error_msg is None:
            response.error_msg = "No Results: MALFORMED"
            response.error_class = 'model'

        return rows, model_notes

    def store_result(self, conn, req_id, response, processed):
        rows = processed
        words = set(w for w in self.data if w)

        # Whole-request granularity: on any error the entire batch is redone,
        # and nothing is written to results (it would just be retried).
        if response.error_class:
            msg = (f"FAILED: {response.error_msg}: {self.run.run_id}/"
                   f"{self.model_alias} #{self.seq_id}; id: {req_id}")
            return RequestResult(failed=words, redo=words,
                                 error_class=response.error_class), msg

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

        msg = (f"FINISHED: {self.run.run_id}/{self.model_alias} #{self.seq_id}; "
               f"id: {req_id}; words: {len(self.data)}")
        return RequestResult(completed=words), msg


class RedoBatchSession(BatchSession):
    """Single-pass word session that re-queues any request that fails, so the
    run only finishes once every word has been processed."""
    def record_result(self, result):
        self.push(*result.redo)
        return 0
