import io
import unittest
from datetime import date, datetime

import pandas as pd
from fastapi.testclient import TestClient

from date_normalization import date_columns, normalize_date
from main import (AutoApproval, AutoCleanupRequest, analyses, app, apply_auto_cleanup,
                  auto_cleanup_config, create_state, export_corrected, get_analysis,
                  normalize_for_match, preview_auto_cleanup)


class DateNormalizationTests(unittest.TestCase):
    def test_supported_date_formats(self):
        for source in ['2026/11/18', '2026.11.18', '18/11/2026', '11/18/2026', '2026-11-18', '18-11-2026', '18.11.2026']:
            with self.subTest(source=source):
                self.assertEqual(normalize_date(source), ('2026-11-18', None))
        self.assertEqual(normalize_date('2026-1-2'), ('2026-01-02', None))

    def test_ambiguous_date_is_not_guessed(self):
        self.assertEqual(normalize_date('03/04/2026')[0], '03/04/2026')
        self.assertIn('ambigua', normalize_date('03/04/2026')[1])
        self.assertEqual(normalize_date('03/04/2026', 'dmy'), ('2026-04-03', None))
        self.assertEqual(normalize_date('03/04/2026', 'mdy'), ('2026-03-04', None))
        self.assertEqual(normalize_date('03/03/2026'), ('2026-03-03', None))

    def test_invalid_and_unsupported_values_are_preserved(self):
        for source in ['31/02/2026', '2026-13-01', '02/29/2025', '18/11/26', 'sin fecha', '2026-11-18 25:00', 45200, 20261118]:
            with self.subTest(source=source):
                self.assertEqual(normalize_date(source)[0], source)
                self.assertIsNotNone(normalize_date(source)[1])
        self.assertEqual(normalize_date('29/02/2024'), ('2024-02-29', None))

    def test_times_fractions_and_timezone_are_retained(self):
        self.assertEqual(normalize_date('18/11/2026 14:30:15'), ('2026-11-18T14:30:15', None))
        self.assertEqual(normalize_date('2026-11-18T14:30:15.123456-05:00'), ('2026-11-18T14:30:15.123456-05:00', None))
        self.assertEqual(normalize_date('2026-11-18T14:30Z'), ('2026-11-18T14:30:00+00:00', None))
        self.assertEqual(normalize_date('03/04/2026 10:15')[0], '03/04/2026 10:15')

    def test_python_dates_and_nulls(self):
        self.assertEqual(normalize_date(date(2026, 11, 18)), ('2026-11-18', None))
        self.assertEqual(normalize_date(datetime(2026, 11, 18, 14, 30)), ('2026-11-18T14:30:00', None))
        self.assertEqual(normalize_date(None), (None, None))
        self.assertEqual(normalize_date(''), ('', None))
        self.assertTrue(pd.isna(normalize_date(pd.NaT)[0]))

    def test_columns_detected_without_interpreting_ids_or_notes(self):
        frame = pd.DataFrame({'fecha_ingreso': ['sin dato', '18/11/2026'], 'dato': ['2026-11-18', '2026/11/19'],
                              'codigo': ['2026-11-18', '2026-11-19'], 'id': [20261118, 20261119],
                              'nota': ['llamar el 18/11/2026', 'sin fecha']})
        self.assertEqual(date_columns(frame, normalize_for_match), ['fecha_ingreso', 'dato'])


class GlobalAutomaticTests(unittest.TestCase):
    def tearDown(self):
        analyses.clear()

    def apply(self, **options):
        preview = preview_auto_cleanup('test', AutoCleanupRequest(revision=analyses['test']['revision'], **options))
        return apply_auto_cleanup('test', AutoApproval(plan_id=preview['plan_id'], revision=preview['revision']))

    def test_global_cleanup_dates_counts_original_and_repeat(self):
        frame = pd.DataFrame({'nombre': [' Ana  Pérez ', ' Luis '], 'city': [' Bogotá ', ' Cali '],
                              'fecha': ['18/11/2026', '03/04/2026'], 'documento': [100, 101]})
        analyses['test'] = create_state(frame, 'test.csv')
        result = self.apply()
        work = analyses['test']['frame']
        self.assertEqual(work.nombre.tolist(), ['Ana Pérez', 'Luis'])
        self.assertEqual(work.city.tolist(), ['Bogotá', 'Cali'])
        self.assertEqual(work.fecha.tolist(), ['2026-11-18', '03/04/2026'])
        self.assertEqual(work.documento.tolist(), [100, 101])
        counts = result['analysis']['automatic_report']['counts']
        self.assertEqual(counts['dates_normalized'], 1)
        self.assertEqual(counts['dates_skipped'], 1)
        self.assertEqual(counts['normalized_cells'], 4)
        self.assertIn('normalize_date', [event['rule'] for event in result['analysis']['automatic_audit']])
        pd.testing.assert_frame_equal(analyses['test']['original_frame'], frame)
        before = get_analysis('test')['revision']
        repeated = self.apply()
        self.assertEqual(repeated['changed_values'], 0)
        self.assertEqual(repeated['analysis']['revision'], before)
        self.assertEqual(export_corrected('test').body, export_corrected('test').body)

    def test_explicit_date_order_and_disable_dates(self):
        frame = pd.DataFrame({'fecha': ['03/04/2026']})
        analyses['test'] = create_state(frame, 'test.csv')
        self.apply(normalize_dates=False)
        self.assertEqual(analyses['test']['frame'].loc[0, 'fecha'], '03/04/2026')
        self.apply(date_order='dmy')
        self.assertEqual(analyses['test']['frame'].loc[0, 'fecha'], '2026-04-03')

    def test_date_normalization_can_create_exact_duplicates(self):
        analyses['test'] = create_state(pd.DataFrame({'nombre': ['Ana', 'Ana'], 'fecha': ['18/11/2026', '2026-11-18']}), 'test.csv')
        result = self.apply()
        self.assertEqual(result['analysis']['rows'], 1)
        self.assertEqual(result['deleted_rows'], 1)
        self.assertEqual(result['analysis']['preview_row_numbers'], [1])

    def test_typed_excel_dates_remain_strings_after_normalization(self):
        frame = pd.DataFrame({'fecha': pd.to_datetime(['2026-11-18 14:30:00', None])})
        analyses['test'] = create_state(frame, 'test.xlsx')
        first = self.apply()
        self.assertEqual(analyses['test']['frame'].loc[0, 'fecha'], '2026-11-18T14:30:00')
        self.assertEqual(first['analysis']['automatic_report']['counts']['dates_normalized'], 1)
        self.assertEqual(self.apply()['changed_values'], 0)

    def test_default_config_enables_global_cleanup_and_dates(self):
        analyses['test'] = create_state(pd.DataFrame({'fecha': ['2026/11/18'], 'city': [' Cali ']}), 'test.csv')
        config = auto_cleanup_config('test')['config']
        self.assertTrue(config['all_columns'])
        self.assertTrue(config['normalize_dates'])
        self.assertEqual(config['date_order'], 'auto')

    def test_mapped_custom_identifier_is_never_interpreted_as_a_date(self):
        frame = pd.DataFrame({'nombre': ['Ana'], 'clave': ['2026/11/18'], 'fecha': ['18/11/2026']})
        analyses['test'] = create_state(frame, 'test.csv')
        self.apply(fields={'name': 'nombre', 'identifiers': ['clave']})
        self.assertEqual(analyses['test']['frame'].loc[0, 'clave'], '2026/11/18')
        self.assertEqual(analyses['test']['frame'].loc[0, 'fecha'], '2026-11-18')

    def test_http_global_dates_export_and_ambiguous_order(self):
        with TestClient(app) as client:
            csv = 'nombre,city,fecha\n" Ana  Pérez "," Bogotá ",18/11/2026\nLuis,Cali,03/04/2026\n'
            id = client.post('/api/analyze', files={'file': ('dates.csv', csv.encode(), 'text/csv')}).json()['analysis_id']
            config = client.get(f'/api/analyses/{id}/auto-cleanup/config').json()['config']
            plan = client.post(f'/api/analyses/{id}/auto-cleanup/preview', json=config).json()
            result = client.post(f'/api/analyses/{id}/auto-cleanup/apply', json={'plan_id': plan['plan_id'], 'revision': plan['revision']})
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(result.json()['analysis']['automatic_report']['counts']['dates_skipped'], 1)
            exported = pd.read_csv(io.BytesIO(client.get(f'/api/analyses/{id}/export').content))
            self.assertEqual(exported.fecha.tolist(), ['2026-11-18', '03/04/2026'])
            self.assertEqual(exported.nombre.iloc[0], 'Ana Pérez')
            self.assertEqual(exported.city.iloc[0], 'Bogotá')
            bad = client.post(f'/api/analyses/{id}/auto-cleanup/preview', json={**config, 'date_order': 'guess'})
            self.assertEqual(bad.status_code, 422)

if __name__ == '__main__':
    unittest.main()
