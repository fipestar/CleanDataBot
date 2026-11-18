import unittest
import io

import pandas as pd
from fastapi import HTTPException
from fastapi.testclient import TestClient

from country_normalization import catalog, country_columns, normalize_country
from main import (AutoApproval, AutoCleanupRequest, analyses, app, apply_auto_cleanup,
                  auto_cleanup_config, create_state, export_corrected, get_analysis, preview_auto_cleanup)


class CountryCatalogTests(unittest.TestCase):
    def test_variants_in_user_example(self):
        cases = {
            'Estados Unidos': ['u.s.', 'US', 'usa', 'United States', 'U.S.A.', 'EE.UU.', 'Estados Unidos de América'],
            'Reino Unido': ['GB', 'uk', 'United Kingdom', 'GBR'],
            'Brasil': ['Brazil', 'BR', 'Brasil'], 'Francia': ['FR', 'france', 'Francia'],
            'Alemania': ['Germany', 'germany', 'DE', 'Alemania'],
        }
        for canonical, variants in cases.items():
            for value in variants:
                with self.subTest(value=value):
                    result, reason, code = normalize_country(value)
                    self.assertEqual(result, canonical)
                    self.assertIsNone(reason)
                    self.assertIsNotNone(code)

    def test_output_formats_and_accents(self):
        self.assertEqual(normalize_country('Estados Unidos', 'iso2'), ('US', None, 'US'))
        self.assertEqual(normalize_country('uk', 'iso3'), ('GBR', None, 'GB'))
        self.assertEqual(normalize_country('Alemania', 'en'), ('Germany', None, 'DE'))
        self.assertEqual(normalize_country('méxico', 'iso2'), ('MX', None, 'MX'))
        self.assertEqual(normalize_country('ESPAÑA', 'iso2'), ('ES', None, 'ES'))
        self.assertEqual(normalize_country('840', 'iso2'), ('US', None, 'US'))

    def test_unknown_ambiguous_and_subdivisions_are_not_guessed(self):
        for value in ['Congo', 'Corea', 'Korea', 'Islas Vírgenes', 'Columbia', 'Germnay', 'England', 'Latam', 840]:
            with self.subTest(value=value):
                result, reason, code = normalize_country(value)
                self.assertEqual(result, value)
                self.assertIsNotNone(reason)
                self.assertIsNone(code)
        self.assertEqual(normalize_country('República del Congo', 'iso2'), ('CG', None, 'CG'))
        self.assertEqual(normalize_country('República Democrática del Congo', 'iso2'), ('CD', None, 'CD'))
        self.assertEqual(normalize_country('Corea del Sur', 'iso2'), ('KR', None, 'KR'))

    def test_empty_values_are_not_failures(self):
        for value in [None, '', '   ']:
            self.assertEqual(normalize_country(value), (value, None, None))
        self.assertTrue(pd.isna(normalize_country(float('nan'))[0]))

    def test_all_canonical_outputs_are_valid_idempotent_inputs(self):
        _, output = catalog()
        self.assertGreater(len(output), 200)
        for code, formats in output.items():
            for format, value in formats.items():
                with self.subTest(code=code, format=format):
                    self.assertEqual(normalize_country(value, format), (value, None, code))

    def test_headers_only_do_not_infer_countries_from_arbitrary_text(self):
        self.assertEqual(country_columns(['nombre', 'Country', 'país', 'billing_country', 'email', 'city']), ['Country', 'país', 'billing_country'])


class CountryPipelineTests(unittest.TestCase):
    def tearDown(self):
        analyses.clear()

    def state(self, frame):
        analyses['test'] = create_state(frame, 'countries.csv')

    def run_cleanup(self, **options):
        plan = preview_auto_cleanup('test', AutoCleanupRequest(revision=analyses['test']['revision'], **options))
        result = apply_auto_cleanup('test', AutoApproval(plan_id=plan['plan_id'], revision=plan['revision']))
        return result

    def test_country_column_only_original_audit_and_repeat(self):
        original = pd.DataFrame({'country': ['US', 'u.s.', 'usa', 'UK', 'france'], 'name': ['US', 'US', 'US', 'UK', 'france'], 'id': range(5)})
        self.state(original)
        result = self.run_cleanup()
        self.assertEqual(analyses['test']['frame'].country.tolist(), ['Estados Unidos', 'Estados Unidos', 'Estados Unidos', 'Reino Unido', 'Francia'])
        self.assertEqual(analyses['test']['frame']['name'].tolist(), original['name'].tolist())
        self.assertEqual(result['analysis']['automatic_report']['counts']['countries_normalized'], 5)
        self.assertEqual(result['analysis']['automatic_report']['counts']['countries_skipped'], 0)
        country_events = [event for event in result['analysis']['automatic_audit'] if event['rule'] == 'normalize_country']
        self.assertEqual(len(country_events), 5)
        self.assertEqual(country_events[0]['country_code'], 'US')
        pd.testing.assert_frame_equal(original, analyses['test']['original_frame'])
        revision = result['analysis']['revision']
        second = self.run_cleanup()
        self.assertEqual(second['changed_values'], 0)
        self.assertEqual(second['analysis']['revision'], revision)
        snapshot = get_analysis('test')
        self.assertEqual(export_corrected('test').body, export_corrected('test').body)
        self.assertEqual(snapshot, get_analysis('test'))

    def test_unknown_and_ambiguous_are_preserved_without_review_group_ui(self):
        self.state(pd.DataFrame({'country': ['Congo', 'Columbia', 'US', None], 'id': [1, 2, 3, 4]}))
        result = self.run_cleanup()
        self.assertEqual(analyses['test']['frame'].country.tolist(), ['Congo', 'Columbia', 'Estados Unidos', None])
        report = result['analysis']['automatic_report']
        self.assertEqual(report['counts']['countries_skipped'], 2)
        self.assertEqual(len(report['country_issues']), 2)
        self.assertEqual(report['country_issues'][0]['row'], 1)

    def test_can_disable_or_explicitly_associate_columns(self):
        self.state(pd.DataFrame({'country': ['US'], 'origen_cliente': ['UK']}))
        self.run_cleanup(normalize_countries=False)
        self.assertEqual(analyses['test']['frame'].country.iloc[0], 'US')
        self.run_cleanup(country_columns=['origen_cliente'], country_format='iso2')
        self.assertEqual(analyses['test']['frame'].country.iloc[0], 'US')
        self.assertEqual(analyses['test']['frame'].origen_cliente.iloc[0], 'GB')

    def test_invalid_columns_and_identity_mapping_are_rejected_atomically(self):
        original = pd.DataFrame({'country': ['US'], 'name': ['Ana']})
        self.state(original)
        before = get_analysis('test')
        for options in [{'country_columns': ['missing']}, {'country_columns': ['name'], 'fields': {'name': 'name'}}]:
            with self.assertRaises(HTTPException):
                preview_auto_cleanup('test', AutoCleanupRequest(revision=0, **options))
            self.assertEqual(before, get_analysis('test'))

    def test_countries_can_create_exact_duplicates_and_accumulate_with_dates(self):
        self.state(pd.DataFrame({'name': [' Ana ', ' Ana '], 'country': ['US', 'usa'], 'fecha': ['18/11/2026', '2026-11-18']}))
        result = self.run_cleanup()
        self.assertEqual(result['analysis']['rows'], 1)
        self.assertEqual(result['analysis']['preview_row_numbers'], [1])
        self.assertEqual(result['deleted_rows'], 1)
        exported = pd.read_csv(io.BytesIO(export_corrected('test').body))
        self.assertEqual(exported.iloc[0].to_dict(), {'name': 'Ana', 'country': 'Estados Unidos', 'fecha': '2026-11-18'})

    def test_selected_country_column_is_not_interpreted_as_a_date(self):
        self.state(pd.DataFrame({'origen_cliente': ['2026/11/18']}))
        result = self.run_cleanup(country_columns=['origen_cliente'])
        self.assertEqual(analyses['test']['frame'].iloc[0, 0], '2026/11/18')
        self.assertEqual(result['analysis']['automatic_report']['counts']['countries_skipped'], 1)
        self.assertEqual(result['analysis']['automatic_report']['counts']['dates_normalized'], 0)

    def test_http_country_settings_preview_apply_and_csv(self):
        with TestClient(app) as client:
            csv = 'id,country,nombre\n1,u.s.,Ana\n2,uk,Luis\n3,Brazil,Sara\n4,FR,Pedro\n5,Germany,Nora\n'
            id = client.post('/api/analyze', files={'file': ('countries.csv', csv.encode(), 'text/csv')}).json()['analysis_id']
            config = client.get(f'/api/analyses/{id}/auto-cleanup/config').json()['config']
            self.assertEqual(config['country_columns'], ['country'])
            self.assertTrue(config['normalize_countries'])
            self.assertEqual(config['country_format'], 'es')
            plan = client.post(f'/api/analyses/{id}/auto-cleanup/preview', json=config).json()
            result = client.post(f'/api/analyses/{id}/auto-cleanup/apply', json={'plan_id': plan['plan_id'], 'revision': plan['revision']})
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(result.json()['analysis']['automatic_report']['counts']['countries_normalized'], 5)
            exported = pd.read_csv(io.BytesIO(client.get(f'/api/analyses/{id}/export').content))
            self.assertEqual(exported.country.tolist(), ['Estados Unidos', 'Reino Unido', 'Brasil', 'Francia', 'Alemania'])
            bad = client.post(f'/api/analyses/{id}/auto-cleanup/preview', json={**config, 'country_format': 'unknown'})
            self.assertEqual(bad.status_code, 422)

if __name__ == '__main__':
    unittest.main()
