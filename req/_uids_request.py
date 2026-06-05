from req._request import *

class RequestResult(NamedTuple):
    failed: set = frozenset()
    redo: set = frozenset()
    completed: set = frozenset()
    error_class: str = None  # '429', 'connection', 'model', or None

@dataclass(slots=True)
class ProcessedResponse:
    rows: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    failed: set = field(default_factory=set)
    redo: set = field(default_factory=set)

class Row(tuple):
    _fields = ()
    _expected = 0
    _idx = {}

    def __new__(cls, cells):
        return super().__new__(cls, cells)

    @classmethod
    def _make(cls, cells):
        return super().__new__(cls, cells)

    def __getattr__(self, name):
        try:
            return self[self._idx[name]]
        except KeyError:
            raise AttributeError(f"Row has no field '{name}'")

    def _asdict(self):
        return {f: self[i] for i, f in enumerate(self._fields) if i < len(self)}

    def _replace(self, **kwargs):
        items = list(self)
        for k, v in kwargs.items():
            items[self._idx[k]] = v
        return type(self)(items)

Row._fields = tuple(result_data_cols)
Row._expected = len(result_data_cols)
Row._idx = result_col_idx

class UidsRequest(Request):
    def create_prompt(self):
        rows = ''.join(f'{self.run.input_strings[uid]}\n' for uid in self.data
                       if uid in self.run.input_strings)
        return f"{self.run.header}\n{rows}"

    def process_response(self, response):
        expected_uids = self.data
        lines = response.content.splitlines()
        table_rows = defaultdict(list)
        model_notes = []
        errors = []

        in_table = False
        headers_found = False

        row_pattern = re.compile(r'^\s*\|.*\|\s*$')
        seen = set()

        for line in lines:
            if row_pattern.match(line):
                if set(line) <= {'|', '-', ' ', ':'}:
                    in_table = True
                    headers_found = True
                    continue

                if not in_table:
                    cells = [c.strip() for c in line.split('|')[1:-1]]
                    if cells:
                        first_cell = cells[0]
                        if first_cell.isdigit():
                            in_table = True
                            headers_found = True
                        else:
                            in_table = True
                            headers_found = True
                            continue

                cells = Row(c.strip() for c in line.split('|')[1:-1])
                if cells in seen:
                    continue
                seen.add(cells)

                try:
                    uid = int(cells[0])
                except ValueError:
                    errors.append({
                        'uid': None,
                        'error_code': "INVALID_UID",
                        'error_msg': f"Invalid UID str: {cells[0]}",
                        'orig_line': line
                    })
                    continue
                if uid not in expected_uids:
                    errors.append({
                        'uid': None,
                        'error_code': "UID_UNKNOWN",
                        'error_msg': f"UID {uid} returned but not requested.",
                        'orig_line': line,
                    })
                    continue

                validation_err = None
                if validate_row is not None:
                    try:
                        cells, validation_err = validate_row(cells, self.run.input_data[uid])
                    except IndexError:
                        pass

                if len(cells) != cells._expected:
                    errors.append({
                        'uid': uid,
                        'error_code': "MALFORMED_ROW",
                        'error_msg': f"Malformed row ({len(cells)} cols, expected {Row._expected})",
                        'orig_line': line
                    })
                    continue

                if validation_err is not None:
                    errors.append({
                        'uid': uid,
                        'error_code': validation_err['error_code'],
                        'error_msg': validation_err['error_msg'],
                        'orig_line': line
                    })
                    continue

                row = cells._asdict()
                row['uid'] = uid

                try:
                    for col in result_data_cols:
                        if col == 'uid':
                            continue
                        col_type = results_types.get(col, '')
                        val = row[col]
                        if col_type == 'INTEGER':
                            row[col] = int(val)
                        elif col_type == 'REAL':
                            row[col] = float(val)
                except (TypeError, ValueError):
                    errors.append({
                        'uid': uid,
                        'error_code': "INVALID_TYPE",
                        'error_msg': f"Column '{col}' expected {col_type} but got: {val}",
                        'orig_line': line
                    })
                    continue

                row['orig_line'] = line
                table_rows[uid].append(row)

            else:
                if in_table:
                    in_table = False
                    model_notes.append(line)
                elif headers_found:
                    model_notes.append(line)

        if not headers_found:
            errors.append({
                'uid': None,
                'error_code': "NO_TABLE",
                'error_msg': "No table structure detected in response.",
                'orig_line': None,
            })

        failed = set(e['uid'] for e in errors if e['uid'] is not None)
        rows = []
        for uid, uid_rows in table_rows.items():
            if uid in failed:
                continue
            rows.extend(uid_rows)

        good_rows = sum(len(r) for r in table_rows.values())
        bad_rows = sum(1 for e in errors if e['orig_line'] is not None)

        if good_rows == 0:
            if not errors:
                errors.append({
                    'uid': None,
                    'error_code': "NO_DATA",
                    'error_msg': "No data.",
                    'orig_line': None,
                })
            redo = set(expected_uids)
        elif good_rows < 2 * bad_rows:
            rows = []
            errors.append({
                'uid': None,
                'error_code': "BAD_ROWS",
                'error_msg': f"Too many bad rows ({bad_rows} bad vs {good_rows} good).",
                'orig_line': None,
            })
            redo = set(expected_uids)
        else:
            completed = set(table_rows.keys()) - failed
            redo = set(expected_uids) - completed
            missing = redo - failed
            if missing:
                errors.append({
                    'uid': None,
                    'error_code': "MISSING_UIDS",
                    'error_msg': f"Missing {len(missing)}/{len(expected_uids)} UIDs.",
                    'orig_line': None,
                })

        processed = ProcessedResponse(rows=rows, errors=errors, failed=failed, redo=redo)

        if not processed.rows and response.error_msg is None:
            code = processed.errors[-1]['error_code'] if processed.errors else 'UNKNOWN'
            response.error_msg = f"No Results: {code}"
            response.error_class = 'model'

        return processed, "\n".join(model_notes).strip()

    def store_result(self, conn, req_id, response, processed):
        insert_errors = []
        for row in processed.rows:
            values = tuple(
                row.get(c, self.run.run_id if c == 'run_id' else req_id if c == 'req_id' else '')
                for c in results_all_cols
            )
            try:
                conn.execute(results_insert_sql, values)
            except sqlite3.IntegrityError as e:
                insert_errors.append({
                    'uid': row['uid'],
                    'error_code': 'CONSTRAINT_VIOLATION',
                    'error_msg': str(e),
                    'orig_line': row.get('orig_line'),
                })
        violations = set(e['uid'] for e in insert_errors)
        conn.executemany("delete from results where req_id = ? and uid = ?",
                         ((req_id, uid) for uid in violations))
        conn.executemany(
            """INSERT INTO errors (req_id, uid, error_code, error_msg, orig_line)
                VALUES (?, ?, ?, ?, ?)""",
            ((req_id, err['uid'], err['error_code'], err['error_msg'], err['orig_line'])
             for err in [*processed.errors, *insert_errors])
        )

        if DYNAMIC_MODE:
            conn.execute(
                'DELETE FROM outstanding_reqs WHERE run_id = ? AND seq_id = ?',
                (self.run.run_id, self.seq_id))
            done = {row['uid'] for row in processed.rows} - violations
            conn.executemany(
                'INSERT OR IGNORE INTO completed_reqs (uid, model, run_id) VALUES (?, ?, ?)',
                [(uid, self.model_alias, self.run.run_id) for uid in done])

        failed = processed.failed | violations
        redo = processed.redo | violations
        completed = {row['uid'] for row in processed.rows} - violations

        error_msg = response.error_msg
        if error_msg and len(error_msg) > 50:
            error_msg = error_msg[0:49] + '…'
        prefix = f"FAILED: {error_msg}" if error_msg else "FINISHED"
        msg = (f"{prefix}: {self.run.run_id}/{self.model_alias} #{self.seq_id}; id: {req_id}; "
               f"ok/err/…: {len(completed)}/{len(failed)}/{len(redo - failed)}")

        return RequestResult(failed=failed, redo=redo, completed=completed,
                             error_class=response.error_class), msg
