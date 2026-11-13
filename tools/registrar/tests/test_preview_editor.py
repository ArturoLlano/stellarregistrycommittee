import base64
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as registrar_app
from registrar.preview_editor import apply_edits, editor_fields
from registrar.repo import RepoContext
from registrar.schema import build_entry_payload


class PreviewEditorTests(unittest.TestCase):
    def setUp(self):
        self.payload = build_entry_payload(
            sao=86406, inscription_name='Estrella de prueba', inscription_motto='Una dedicatoria',
            inscription_date='2026-11-13', recorded_by='Clerk', sponsor='Sponsor',
            recorded_at_utc='2026-11-13T00:00:00Z', coordinates=None,
            sao_meta={'coordinates': {'ra_hms': '18 45 39.732', 'dec_dms': '+20 32 46.75',
                                     'ra_deg': 281.41555, 'dec_deg': 20.54631944},
                      'photometry': {'v_mag': 4.3, 'source': 'I/131A'},
                      'spectral': {'type': 'F5', 'is_composite': False, 'source': 'I/131A'}})
        self.form = {f['name']: str(f['value']) for f in editor_fields(self.payload)}
        self.form['editor_version'] = '1'
        self.form['payload_b64'] = base64.b64encode(json.dumps(self.payload).encode()).decode()

    def test_untouched_payload_is_identical(self):
        self.assertEqual(apply_edits(self.payload, self.form), self.payload)

    def test_catalogue_edits_regenerate_legend_and_preserve_originals(self):
        self.form.update(v_mag='0', spectral_type='A2', inscription_name='Nombre corregido')
        result = apply_edits(self.payload, self.form)
        self.assertEqual(result['id'], self.payload['id'])
        self.assertEqual(result['object']['inscription']['name'], 'Nombre corregido')
        self.assertIn('visual magnitude: 0.0', result['certificate']['legend_en'])
        self.assertIn('spectral type: A2', result['certificate']['legend_en'])
        self.assertEqual(result['provenance']['manual_overrides']['object.photometry.v_mag']['original'], 4.3)
        self.assertEqual(self.payload['object']['photometry']['v_mag'], 4.3)

    def test_coordinate_changes_update_degrees_and_constellation(self):
        self.form.update(ra_hms='12:00:00', dec_dms='-00 30 00')
        result = apply_edits(self.payload, self.form)
        self.assertEqual(result['object']['coordinates']['ra_deg'], 180)
        self.assertEqual(result['object']['coordinates']['dec_deg'], -0.5)
        self.assertIn('12h 00m 0.00s', result['certificate']['legend_en'])

    def test_new_entries_have_independent_visual_coordinates(self):
        obj = self.payload['object']
        self.assertEqual(obj['coordinatesV'], obj['coordinates'])
        self.assertIsNot(obj['coordinatesV'], obj['coordinates'])

    def test_visual_edits_never_change_certificate_or_catalogue_coordinates(self):
        self.form.update(visual_ra_hms='12:00:00', visual_dec_dms='-00 30 00')
        result = apply_edits(self.payload, self.form)
        visual = result['object']['coordinatesV']
        self.assertEqual(visual['ra_deg'], 180)
        self.assertEqual(visual['dec_deg'], -0.5)
        self.assertEqual(visual['epoch'], 'J2000')
        self.assertEqual(result['object']['coordinates'], self.payload['object']['coordinates'])
        self.assertEqual(result['object']['constellation'], self.payload['object']['constellation'])
        self.assertEqual(result['certificate'], self.payload['certificate'])
        self.assertEqual(result['provenance'], self.payload['provenance'])

    def test_old_entry_without_visual_coordinates_and_clearing_pair(self):
        old = json.loads(json.dumps(self.payload))
        old['object'].pop('coordinatesV')
        form = {f['name']: str(f['value']) for f in editor_fields(old)}
        form['editor_version'] = '1'
        self.assertEqual(apply_edits(old, form), old)
        result = apply_edits(self.payload, {**self.form, 'visual_ra_hms': '', 'visual_dec_dms': ''})
        self.assertNotIn('coordinatesV', result['object'])
        self.assertEqual(result['certificate'], self.payload['certificate'])

    def test_visual_pair_is_validated(self):
        for ra, dec in [('24 00 00', '+00 00 00'), ('12 00 00', '+90 01 00'), ('', '+00 00 00')]:
            with self.subTest(ra=ra, dec=dec), self.assertRaises(ValueError):
                apply_edits(self.payload, {**self.form, 'visual_ra_hms': ra, 'visual_dec_dms': dec})

    def test_invalid_fields_are_rejected(self):
        for field, value in [('v_mag', 'nan'), ('v_mag', '1e999'), ('ra_hms', '24 00 00'),
                             ('dec_dms', '+90 01 00'), ('dec_dms', ''),
                             ('inscription_name', ''), ('inscription_date', '2026-02-30')]:
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                apply_edits(self.payload, {**self.form, field: value})

    def test_review_and_commit_use_same_edited_payload_without_publishing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ctx = RepoContext(ok=True, repo_root=root, entries_dir=root/'public'/'data'/'entries')
            client = registrar_app.app.test_client()
            with patch.object(registrar_app, 'detect_repo_context', return_value=ctx), \
                 patch.object(registrar_app, 'find_duplicates', return_value=[]), \
                 patch.object(registrar_app.subprocess, 'run', side_effect=AssertionError('No Git in this test')):
                self.form.update(v_mag='2.7', spectral_type='A0', visual_ra_hms='12 00 00', visual_dec_dms='-00 30 00')
                review = client.post('/review', data=self.form)
                self.assertEqual(review.status_code, 200)
                self.assertIn(b'visual magnitude: 2.7', review.data)
                self.assertIn(b'spectral type: A0', review.data)
                self.assertFalse(ctx.entries_dir.exists())
                bad = client.post('/commit', data={**self.form, 'ra_hms': 'bad'})
                self.assertEqual(bad.status_code, 400)
                self.assertIn(b'value="bad"', bad.data)
                self.assertFalse(ctx.entries_dir.exists())
                captured = []
                module = types.ModuleType('tools.tsrc.certificates.generate')
                def capture(**kwargs):
                    captured.append(json.loads((ctx.entries_dir/(kwargs['entry_id']+'.json')).read_text(encoding='utf-8')))
                    raise RuntimeError('Intentional stop before PDF or Git')
                module.generate_certificate_pdf_for_id = capture
                with patch.dict(sys.modules, {'tools.tsrc.certificates.generate': module}):
                    result = client.post('/commit', data=self.form)
                self.assertEqual(result.status_code, 500)  # intentional, isolated generation stub
                self.assertEqual(captured[0]['object']['photometry']['v_mag'], 2.7)
                self.assertEqual(captured[0]['object']['coordinatesV']['ra_deg'], 180)
                self.assertEqual(captured[0]['object']['coordinates'], self.payload['object']['coordinates'])
                self.assertIn('spectral type: A0', captured[0]['certificate']['legend_en'])
                self.assertFalse(list(ctx.entries_dir.glob('*.json')))  # rolled back


if __name__ == '__main__':
    unittest.main()
