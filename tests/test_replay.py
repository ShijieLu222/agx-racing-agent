"""Export-integrity checks prevent partial or mis-scoped logs being reported valid."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

from test_agent import observation

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from replay_check import complete_rows, replay


def export_bytes(seats=(4,), fault=False):
    metadata = {'type': 'metadata', 'game_id': 'racing',
                'schema': 'agent-tournament.training-export.v2',
                'rules_version': 'rsi-racing-4.4',
                'participants': [{'seat': s, 'agent_id': 'PRIVATE_ACCOUNT_ID'} for s in seats],
                'job_id': 'PRIVATE_JOB_ID', 'seed': 123456789}
    lines = [(json.dumps(metadata) + '\n').encode()]
    decisions = []
    for seat in seats:
        o = observation()
        o['seat'] = seat
        decisions.append((json.dumps({'seat': seat, 'observation': o,
                          'action': None if fault else {'throttle': 0.0, 'brake': 0.0, 'steer': 0.0},
                          'fault': fault}) + '\n').encode())
    lines.extend(decisions)
    lines.append(b'{"type":"outcome","reason":"test"}\n')
    body = b''.join(decisions)
    end = {'type': 'export_complete', 'complete': True, 'rows': len(decisions),
           'raw_bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest(),
           'seat_calls': {str(s): 1 for s in seats}}
    lines.append((json.dumps(end) + '\n').encode())
    return b''.join(lines)


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'training.jsonl'

    def test_original_bytes_and_complete_counts_are_verified(self):
        self.path.write_bytes(export_bytes())
        records = list(complete_rows(self.path))
        self.assertEqual(records[-1]['type'], 'export_complete')
        changed = export_bytes().replace(b'"fault": false', b'"fault":  false')
        self.path.write_bytes(changed)
        with self.assertRaisesRegex(ValueError, 'counts do not match'):
            list(complete_rows(self.path))

    def test_truncation_and_appended_data_are_rejected(self):
        full = export_bytes()
        for bad in (b'\n'.join(full.splitlines()[:-1]) + b'\n',
                    full + b'{"type":"outcome"}\n'):
            self.path.write_bytes(bad)
            with self.assertRaises(ValueError):
                list(complete_rows(self.path))

    def test_wrong_seat_count_or_digest_is_rejected(self):
        for field, value in (('seat_calls', {'4': 2}), ('sha256', '0' * 64),
                             ('rows', 2), ('raw_bytes', 1)):
            lines = export_bytes().splitlines()
            tail = json.loads(lines[-1])
            tail[field] = value
            lines[-1] = json.dumps(tail).encode()
            self.path.write_bytes(b'\n'.join(lines) + b'\n')
            with self.subTest(field=field), self.assertRaises(ValueError):
                list(complete_rows(self.path))

    def test_multiple_seats_require_selection_and_public_report_omits_private_fields(self):
        self.path.write_bytes(export_bytes((4, 7)))
        with self.assertRaisesRegex(ValueError, 'multiple seats'):
            replay(self.path)
        report = replay(self.path, seat=4)
        self.assertEqual(report['candidate']['calls'], 1)
        encoded = json.dumps(report)
        for secret in ('PRIVATE_ACCOUNT_ID', 'PRIVATE_JOB_ID', '123456789', str(self.path)):
            self.assertNotIn(secret, encoded)

    def test_recorded_fault_with_no_action_can_be_audited_without_hiding_fault(self):
        self.path.write_bytes(export_bytes(fault=True))
        report = replay(self.path, seat=4)
        self.assertEqual(report['recorded_faults_for_selected_seat'], 1)
        self.assertEqual(report['candidate']['calls'], 1)
        self.assertEqual(report['candidate']['changed_actions_vs_recorded'], 1)
        self.assertEqual(report['candidate']['exceptions'], 0)

    def test_mismatched_selected_observation_identity_is_rejected(self):
        self.path.write_bytes(export_bytes())
        with self.assertRaisesRegex(ValueError, 'selected seat is absent'):
            replay(self.path, seat=99)


if __name__ == '__main__':
    unittest.main()
