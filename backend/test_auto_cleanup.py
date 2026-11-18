import io
import unittest
from unittest.mock import patch

import pandas as pd
from fastapi import HTTPException
from fastapi.testclient import TestClient

from main import (AutoApproval, AutoCleanupRequest, ExceptionDecision, analyses, app, apply_auto_cleanup,
                  auto_cleanup_config, create_state, export_corrected, get_analysis, preview_auto_cleanup,
                  review_auto_exception, apply_text_cleanup, preview_text_cleanup, TextCleanupRequest, TextCleanupApproval)


class AutomaticCleanupTests(unittest.TestCase):
    def tearDown(self):
        analyses.clear()

    def state(self, rows):
        frame = pd.DataFrame(rows)
        analyses['test'] = create_state(frame, 'clientes.csv')
        return frame

    def config(self, **overrides):
        return AutoCleanupRequest(**{'revision': analyses['test']['revision'],
            'fields': {'name': 'full_name', 'email': 'email', 'phone': 'phone', 'identifiers': ['document']},
            **overrides})

    def run_cleanup(self, config=None):
        preview = preview_auto_cleanup('test', config or self.config())
        result = apply_auto_cleanup('test', AutoApproval(plan_id=preview['plan_id'], revision=preview['revision']))
        return result, result['analysis']['automatic_report']

    def base(self, **updates):
        return {'full_name': 'Ana María Pérez', 'email': 'ana@example.com', 'phone': None, 'document': 'A-1', 'city': 'Bogotá', **updates}

    def test_real_duplicate_fills_only_empty_fields_and_keeps_first(self):
        original = self.state([self.base(city=None), self.base(full_name='Ana Maria Pérez', phone='3001234567')])
        result, report = self.run_cleanup()
        work = analyses['test']['frame']
        self.assertEqual(len(work), 1)
        self.assertEqual(work.index.tolist(), [0])
        self.assertEqual(work.loc[0, 'city'], 'Bogotá')
        self.assertEqual(work.loc[0, 'phone'], '3001234567')
        self.assertEqual(work.loc[0, 'full_name'], 'Ana María Pérez')
        self.assertEqual(report['counts']['clients_merged'], 1)
        self.assertEqual(report['counts']['filled_cells'], 2)
        self.assertEqual(result['changed_values'], 2)
        self.assertEqual(report['counts']['pending_groups'], 0)
        self.assertTrue(all(event['rule'] for event in result['analysis']['automatic_audit']))
        pd.testing.assert_frame_equal(analyses['test']['original_frame'], original)

    def test_similar_names_alone_and_two_empty_contacts_never_merge(self):
        self.state([self.base(email=None), self.base(full_name='Ana Maria Pérez', email='', document='A-2')])
        _, report = self.run_cleanup()
        self.assertEqual(len(analyses['test']['frame']), 2)
        self.assertEqual(report['counts']['clients_merged'], 0)
        self.assertEqual(report['counts']['pending_groups'], 1)
        self.assertIn('sin correo', ' '.join(report['pending_groups'][0]['reasons']))

    def test_contradictory_identifiers_contacts_and_other_fields_block_merge(self):
        for changes in [{'document': 'B-2'}, {'phone': '999'}, {'city': 'Cali'}, {'email': 'other@example.com'}]:
            with self.subTest(changes=changes):
                self.state([self.base(phone='300'), self.base(**changes)])
                _, report = self.run_cleanup()
                self.assertEqual(report['counts']['clients_merged'], 0)
                self.assertEqual(report['counts']['pending_groups'], 1)
                self.assertTrue(report['pending_groups'][0]['conflicting_columns'])
                self.assertEqual(len(analyses['test']['frame']), 2)

    def test_shared_contact_different_or_missing_name_is_reviewed(self):
        for value in ['Carlos Rojas', None, '', 1234]:
            with self.subTest(name=value):
                self.state([self.base(), self.base(full_name=value)])
                _, report = self.run_cleanup()
                self.assertEqual(report['counts']['clients_merged'], 0)
                self.assertEqual(report['counts']['pending_groups'], 1)

    def test_exact_duplicates_removed_before_and_after_standardization(self):
        original = self.state([self.base(city='BOGOTA'), self.base(city='BOGOTA'), self.base(city='  Bogotá  ')])
        config = self.config(column_rules=[{'column': 'city', 'replacements': [{'variant': 'BOGOTA', 'canonical': 'Bogotá'}]}])
        result, report = self.run_cleanup(config)
        self.assertEqual(report['counts']['exact_duplicates_removed'], 2)
        self.assertEqual(report['counts']['normalized_cells'], 1)
        self.assertEqual(report['counts']['standardized_cells'], 1)
        self.assertEqual(len(analyses['test']['frame']), 1)
        self.assertEqual(analyses['test']['frame'].loc[0, 'city'], 'Bogotá')
        self.assertEqual({event['rule'] for event in report['events']}, {'exact_duplicate_before', 'normalize_text', 'canonical_variant', 'exact_duplicate_after_standardization'})
        pd.testing.assert_frame_equal(original, analyses['test']['original_frame'])
        self.assertEqual(result['deleted_rows'], 2)

    def test_column_scope_canonical_chains_and_second_run_are_idempotent(self):
        self.state([self.base(full_name='BOGOTA', city='  BOGOTA '), self.base(full_name='Other', email=None, city='bogota', document='A-2')])
        rules = [{'column': 'city', 'replacements': [{'variant': 'BOGOTA', 'canonical': 'bogota'}, {'variant': 'bogota', 'canonical': '  Bogotá  '}]}]
        _, first = self.run_cleanup(self.config(column_rules=rules, title_case_names=False))
        before = analyses['test']['frame'].copy(deep=True)
        revision = analyses['test']['revision']
        second, report = self.run_cleanup(self.config(column_rules=rules, title_case_names=False))
        self.assertEqual(analyses['test']['frame'].loc[0, 'full_name'], 'BOGOTA')
        self.assertEqual(first['counts']['standardized_cells'], 2)
        self.assertEqual(report['counts']['duplicates_removed'], 0)
        self.assertEqual(report['counts']['normalized_cells'], 0)
        self.assertEqual(report['counts']['standardized_cells'], 0)
        self.assertEqual(second['changed_values'], 0)
        self.assertEqual(analyses['test']['revision'], revision)
        pd.testing.assert_frame_equal(before, analyses['test']['frame'])
        snapshot = get_analysis('test')
        self.assertEqual(export_corrected('test').body, export_corrected('test').body)
        self.assertEqual(snapshot, get_analysis('test'))

    def test_transitive_contact_chain_is_not_automatically_merged(self):
        self.state([self.base(email='a@example.com', phone=None), self.base(email='a@example.com', phone='300'), self.base(email=None, phone='300')])
        _, report = self.run_cleanup()
        self.assertEqual(report['counts']['clients_merged'], 0)
        self.assertEqual(report['counts']['pending_groups'], 1)
        self.assertEqual(len(report['pending_groups'][0]['records']), 3)
        self.assertEqual(len(analyses['test']['frame']), 3)
        _, repeat = self.run_cleanup()
        self.assertEqual(repeat['counts']['clients_merged'], 0)

    def test_transitive_name_links_only_group_for_presentation(self):
        self.state([self.base(full_name='AAAA', email=None, document='1'), self.base(full_name='AAAB', email=None, document='2'), self.base(full_name='AABB', email=None, document='3')])
        _, report = self.run_cleanup(self.config(review_threshold=70))
        self.assertEqual(report['counts']['clients_merged'], 0)
        self.assertEqual(report['counts']['pending_groups'], 1)
        self.assertEqual(len(report['pending_groups'][0]['records']), 3)

    def test_conflicting_donors_cannot_partially_fill_the_survivor(self):
        self.state([self.base(city=None), self.base(city='Bogotá'), self.base(city='Cali')])
        _, report = self.run_cleanup()
        self.assertEqual(report['counts']['clients_merged'], 0)
        self.assertIsNone(analyses['test']['frame'].loc[0, 'city'])
        self.assertEqual(report['counts']['filled_cells'], 0)

    def test_missing_roles_are_explained_and_aliases_are_suggested(self):
        self.state([{'full_name': 'Ana', 'email': 'a@example.com'}, {'full_name': 'Ana', 'email': 'b@example.com'}])
        suggested = auto_cleanup_config('test')['config']['fields']
        self.assertEqual(suggested['name'], 'full_name')
        self.assertEqual(suggested['email'], 'email')
        _, report = self.run_cleanup(AutoCleanupRequest(revision=0, fields={'name': 'full_name'}))
        self.assertIn('falta asociar correo', ' '.join(report['warnings']))
        self.assertEqual(len(analyses['test']['frame']), 2)
        self.state([{'email': 'a@example.com', 'city': 'Cali'}, {'email': 'a@example.com', 'city': None}])
        _, report = self.run_cleanup(AutoCleanupRequest(revision=0, fields={'email': 'email'}))
        self.assertIn('columna de nombre', ' '.join(report['warnings']))
        self.assertEqual(report['counts']['clients_merged'], 0)

    def test_ambiguous_headers_are_not_silently_selected(self):
        self.state([{'full_name': 'Ana', 'nombre': 'Ana', 'email': 'a@example.com'}])
        config = auto_cleanup_config('test')
        self.assertIsNone(config['config']['fields']['name'])
        self.assertTrue(config['warnings'])

    def test_invalid_rules_and_cycles_do_not_modify_state(self):
        self.state([self.base(city='BOGOTA')])
        before = get_analysis('test')
        rules = [
            {'column_rules': [{'column': 'missing'}]},
            {'column_rules': [{'column': 'city', 'replacements': [{'variant': 'BOGOTA', 'canonical': 'Bogotá'}, {'variant': 'Bogotá', 'canonical': 'BOGOTA'}]}]},
            {'column_rules': [{'column': 'city', 'replacements': [{'variant': 'BOGOTA', 'canonical': 'Bogotá'}, {'variant': ' BOGOTA ', 'canonical': 'Cali'}]}]},
            {'ignored_columns': ['document']},
            {'fields': {'name': 'full_name', 'email': 'email', 'phone': 'email'}},
        ]
        for override in rules:
            with self.subTest(rule=override), self.assertRaises(HTTPException):
                preview_auto_cleanup('test', self.config(**override))
            self.assertEqual(before, get_analysis('test'))

    def test_stale_and_replayed_plan_rejected_and_summary_failure_is_atomic(self):
        self.state([self.base(city='  Bogotá ')])
        preview = preview_auto_cleanup('test', self.config(column_rules=[{'column': 'city'}]))
        approval = AutoApproval(plan_id=preview['plan_id'], revision=0)
        with patch('main.summary', side_effect=RuntimeError('metric failure')):
            with self.assertRaises(RuntimeError): apply_auto_cleanup('test', approval)
        self.assertEqual(analyses['test']['revision'], 0)
        self.assertEqual(analyses['test']['automatic_audit'], [])
        apply_auto_cleanup('test', approval)
        with self.assertRaises(HTTPException) as stale: apply_auto_cleanup('test', approval)
        self.assertEqual(stale.exception.status_code, 409)
        with self.assertRaises(HTTPException): preview_auto_cleanup('test', self.config(revision=0))

    def test_keep_all_is_recorded_and_respected_on_repeat(self):
        self.state([self.base(document='1'), self.base(document='2')])
        _, report = self.run_cleanup()
        group = report['pending_groups'][0]
        result = review_auto_exception('test', ExceptionDecision(revision=report['revision'], run_id=report['run_id'], group_id=group['id'], action='keep_all'))
        self.assertEqual(result['analysis']['automatic_report']['counts']['pending_groups'], 0)
        _, repeat = self.run_cleanup()
        self.assertEqual(repeat['counts']['pending_groups'], 0)
        self.assertEqual(repeat['counts']['previously_separated_groups'], 1)
        self.assertEqual(len(analyses['test']['frame']), 2)
        _, changed_config = self.run_cleanup(self.config(fields={'name': 'full_name', 'email': 'email', 'phone': 'phone'}, ignored_columns=['document']))
        self.assertEqual(changed_config['counts']['clients_merged'], 0)
        self.assertEqual(len(analyses['test']['frame']), 2)

    def test_previous_manual_transformations_accumulate_and_old_proposals_expire(self):
        self.state([self.base(full_name=' Ana  María Pérez ', city='BOGOTA'), self.base(full_name=' Ana  María Pérez ', city='Bogotá')])
        manual = preview_text_cleanup('test', TextCleanupRequest(columns=['full_name'], trim=True, collapse_spaces=True))
        apply_text_cleanup('test', TextCleanupApproval(preview_id=manual['preview_id'], revision=0, approved_change_ids=[change['id'] for change in manual['changes']]))
        stale = preview_text_cleanup('test', TextCleanupRequest(columns=['city'], letter_case='upper'))
        self.run_cleanup(self.config(column_rules=[{'column': 'city', 'replacements': [{'variant': 'BOGOTA', 'canonical': 'Bogotá'}]}]))
        exported = pd.read_csv(io.BytesIO(export_corrected('test').body))
        self.assertEqual(exported['full_name'].tolist(), ['Ana María Pérez'])
        self.assertEqual(exported['city'].tolist(), ['Bogotá'])
        with self.assertRaises(HTTPException):
            apply_text_cleanup('test', TextCleanupApproval(preview_id=stale['preview_id'], revision=1, approved_change_ids=[change['id'] for change in stale['changes']]))

    def test_exact_only_without_customer_fields_and_no_blank_evidence(self):
        self.state([{'note': 'same', 'email': None}, {'note': 'same', 'email': None}, {'note': 'different', 'email': None}])
        _, report = self.run_cleanup(AutoCleanupRequest(revision=0))
        self.assertEqual(report['counts']['exact_duplicates_removed'], 1)
        self.assertEqual(report['counts']['clients_merged'], 0)
        self.assertEqual(len(report['warnings']), 2)
        self.assertEqual(analyses['test']['frame'].index.tolist(), [0, 2])

    def test_manual_exception_decision_removes_only_selected_stable_rows(self):
        self.state([self.base(document='1'), self.base(document='2'), self.base(document='3')])
        _, report = self.run_cleanup()
        group = report['pending_groups'][0]
        invalid = ExceptionDecision(revision=0, run_id=report['run_id'], group_id=group['id'], action='remove_selected', keep_row=1, remove_rows=[1])
        with self.assertRaises(HTTPException): review_auto_exception('test', invalid)
        result = review_auto_exception('test', ExceptionDecision(revision=0, run_id=report['run_id'], group_id=group['id'], action='remove_selected', keep_row=1, remove_rows=[2]))
        self.assertEqual(result['deleted_rows'], 1)
        self.assertEqual(result['analysis']['preview_row_numbers'], [1, 3])
        self.assertEqual(analyses['test']['frame'].loc[2, 'document'], '3')
        self.assertEqual(result['analysis']['automatic_report']['counts']['pending_groups'], 1)
        with self.assertRaises(HTTPException): review_auto_exception('test', invalid)

    def test_review_recomputes_groups_when_a_transitive_bridge_is_removed(self):
        self.state([self.base(full_name='AAAA', email=None, document='1'), self.base(full_name='AAAB', email=None, document='2'), self.base(full_name='AABB', email=None, document='3')])
        _, report = self.run_cleanup(self.config(review_threshold=70))
        group = report['pending_groups'][0]
        result = review_auto_exception('test', ExceptionDecision(revision=report['revision'], run_id=report['run_id'], group_id=group['id'], action='remove_selected', keep_row=1, remove_rows=[2]))
        self.assertEqual(result['analysis']['automatic_report']['pending_groups'], [])
        self.assertEqual(result['analysis']['automatic_report']['counts']['pending_groups'], 0)
        self.assertEqual(result['analysis']['preview_row_numbers'], [1, 3])

    def test_technical_ids_require_explicit_ignoring(self):
        self.state([self.base(id=1), self.base(id=2, phone='300')])
        _, report = self.run_cleanup()
        self.assertEqual(report['counts']['clients_merged'], 0)
        _, report = self.run_cleanup(self.config(ignored_columns=['id']))
        self.assertEqual(report['counts']['clients_merged'], 1)
        self.assertEqual(analyses['test']['frame'].loc[0, 'id'], 1)

    def test_nonempty_contact_does_not_match_an_empty_contact(self):
        self.state([self.base(email='a@example.com'), self.base(email=None)])
        _, report = self.run_cleanup()
        self.assertEqual(report['counts']['clients_merged'], 0)

    def test_complete_contact_clique_merges_once_and_then_is_unchanged(self):
        self.state([self.base(city=None), self.base(phone='300'), self.base(city='Bogotá')])
        _, report = self.run_cleanup()
        self.assertEqual(report['counts']['duplicates_removed'], 2)
        self.assertEqual(len(analyses['test']['frame']), 1)
        before = get_analysis('test')['revision']
        _, report = self.run_cleanup()
        self.assertEqual(report['counts']['duplicates_removed'], 0)
        self.assertEqual(report['counts']['filled_cells'], 0)
        self.assertEqual(get_analysis('test')['revision'], before)


class AutomaticHttpTests(unittest.TestCase):
    def tearDown(self):
        analyses.clear()

    def test_title_case_applies_only_to_the_mapped_name_column(self):
        with TestClient(app) as client:
            source = "full_name,nota\nMARÍA-JOSÉ pérez,MARÍA-JOSÉ pérez\n,Sin nombre\n"
            upload = client.post('/api/analyze', files={'file': ('names.csv', source.encode(), 'text/csv')})
            path = f"/api/analyses/{upload.json()['analysis_id']}"
            config = client.get(f'{path}/auto-cleanup/config').json()['config']
            self.assertEqual(config['fields']['name'], 'full_name')
            self.assertTrue(config['title_case_names'])
            plan = client.post(f'{path}/auto-cleanup/preview', json=config).json()
            self.assertEqual(plan['counts']['names_title_cased'], 1)
            result = client.post(f'{path}/auto-cleanup/apply', json={
                'plan_id': plan['plan_id'], 'revision': plan['revision'],
            })
            self.assertEqual(result.status_code, 200)
            current = pd.read_csv(io.BytesIO(client.get(f'{path}/export').content))
            self.assertEqual(current.loc[0, 'full_name'], 'María-José Pérez')
            self.assertEqual(current.loc[0, 'nota'], 'MARÍA-JOSÉ pérez')
            self.assertTrue(pd.isna(current.loc[1, 'full_name']))
            config['revision'] = result.json()['analysis']['revision']
            repeated = client.post(f'{path}/auto-cleanup/preview', json=config).json()
            self.assertEqual(repeated['counts']['names_title_cased'], 0)

    def test_http_upload_config_preview_apply_and_combined_export(self):
        with TestClient(app) as client:
            csv = 'full_name,email,phone,city\n" Ana  Pérez ",a@example.com,,BOGOTA\nAna Pérez,a@example.com,300,Bogotá\nAna Pérez,a@example.com,300,Bogotá\nAna Peres,b@example.com,400,Cali\n'
            initial = client.post('/api/analyze', files={'file': ('test.csv', csv.encode(), 'text/csv')}).json()
            id = initial['analysis_id']
            config = client.get(f'/api/analyses/{id}/auto-cleanup/config').json()['config']
            self.assertEqual(config['fields']['name'], 'full_name')
            next(rule for rule in config['column_rules'] if rule['column'] == 'city')['replacements'] = [{'variant': 'BOGOTA', 'canonical': 'Bogotá'}]
            preview = client.post(f'/api/analyses/{id}/auto-cleanup/preview', json=config)
            self.assertEqual(preview.status_code, 200, preview.text)
            approval = {'plan_id': preview.json()['plan_id'], 'revision': 0}
            result = client.post(f'/api/analyses/{id}/auto-cleanup/apply', json=approval)
            self.assertEqual(result.status_code, 200, result.text)
            analysis = result.json()['analysis']
            self.assertEqual(analysis['rows'], 2)
            self.assertEqual(analysis['automatic_report']['counts']['duplicates_removed'], 2)
            exported = pd.read_csv(io.BytesIO(client.get(f'/api/analyses/{id}/export').content))
            self.assertEqual(exported.iloc[0]['full_name'], 'Ana Pérez')
            self.assertEqual(exported.iloc[0]['phone'], 300)
            self.assertEqual(exported.iloc[0]['city'], 'Bogotá')
            self.assertEqual(client.post(f'/api/analyses/{id}/auto-cleanup/apply', json=approval).status_code, 409)
            self.assertEqual(client.post(f'/api/analyses/{id}/auto-cleanup/preview', json={}).status_code, 422)
            pd.testing.assert_frame_equal(analyses[id]['original_frame'], pd.read_csv(io.StringIO(csv)))

    def test_http_review_groups_and_manual_selection_contract(self):
        with TestClient(app) as client:
            csv = 'full_name,email,document\nAna,a@example.com,1\nANA,a@example.com,2\n'
            id = client.post('/api/analyze', files={'file': ('test.csv', csv.encode(), 'text/csv')}).json()['analysis_id']
            config = client.get(f'/api/analyses/{id}/auto-cleanup/config').json()['config']
            self.assertEqual(config['fields']['identifiers'], ['document'])
            plan = client.post(f'/api/analyses/{id}/auto-cleanup/preview', json=config).json()
            report = client.post(f'/api/analyses/{id}/auto-cleanup/apply', json={'plan_id': plan['plan_id'], 'revision': 0}).json()['analysis']['automatic_report']
            request = {'revision': report['revision'], 'run_id': report['run_id'], 'group_id': report['pending_groups'][0]['id'], 'action': 'remove_selected', 'keep_row': 2, 'remove_rows': [1]}
            response = client.post(f'/api/analyses/{id}/auto-cleanup/review', json=request)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()['analysis']['preview_row_numbers'], [2])
            self.assertEqual(response.json()['analysis']['automatic_report']['counts']['pending_groups'], 0)
            self.assertEqual(client.post(f'/api/analyses/{id}/auto-cleanup/review', json=request).status_code, 409)

if __name__ == '__main__':
    unittest.main()
