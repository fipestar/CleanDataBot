import io
import random
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from fastapi import HTTPException
from fastapi.testclient import TestClient

from main import (GroupApproval, MatchApproval, MatchRequest, TextCleanupApproval, TextCleanupRequest,
    DuplicateApplyRequest, DuplicateDecisionRequest, DuplicateSearchRequest,
    analyses, app, apply_group, apply_matches, apply_text_cleanup, apply_duplicate_decisions,
    confirm_duplicate_decision, create_state, export_corrected, find_groups, find_matches,
    get_analysis, get_empty_rows, normalize_for_match, preview_text_cleanup, search_duplicates, similarity)

EXAMPLES = Path(__file__).resolve().parents[1] / 'frontend' / 'public'

class WorkingDatasetTests(unittest.TestCase):
    def setUp(self):
        self.original = pd.read_csv(EXAMPLES / 'grupos_demo.csv')
        analyses['test'] = create_state(self.original, 'demo.csv')
    def tearDown(self):
        analyses.clear()
    def groups(self):
        proposal = find_groups('test', MatchRequest(column='ciudad'))
        return proposal, next(group for group in proposal['groups'] if 'Bogotá' in [variant['value'] for variant in group['variants']] and group['kind'] == 'normalized')
    def group_request(self, proposal, group, **kwargs):
        return GroupApproval(proposal_id=proposal['proposal_id'], revision=proposal['revision'], group_id=group['id'],
            variants=kwargs.get('variants', [variant['value'] for variant in group['variants']]), canonical=kwargs.get('canonical', 'Bogotá'))
    def cleanup(self):
        preview = preview_text_cleanup('test', TextCleanupRequest(columns=['nombre'], trim=True, collapse_spaces=True))
        request = TextCleanupApproval(preview_id=preview['preview_id'], revision=preview['revision'], approved_change_ids=[change['id'] for change in preview['changes']])
        return apply_text_cleanup('test', request)
    def test_cleanup_groups_duplicates_and_export_accumulate(self):
        self.assertEqual(self.cleanup()['changed_values'], 5)
        proposal, group = self.groups()
        self.assertEqual(apply_group('test', self.group_request(proposal, group))['changed_values'], 4)
        review = search_duplicates('test', DuplicateSearchRequest())
        self.assertEqual(review['pairs'][0]['id'], '1:7')
        confirm_duplicate_decision('test', DuplicateDecisionRequest(review_id=review['review_id'], revision=2, pair_id='1:7', action='keep_left'))
        result = apply_duplicate_decisions('test', DuplicateApplyRequest(review_id=review['review_id'], revision=2))
        current = result['analysis']
        self.assertEqual((current['original_rows'], current['rows'], current['deleted_rows'], current['modified_values']), (8, 7, 1, 8))
        self.assertEqual(current['preview_row_numbers'], [1, 2, 3, 4, 5, 6, 8])
        self.assertEqual(current['completeness'], round(34/35*100, 2))
        self.assertLess(current['completeness'], 97.5)  # Deleting a complete row reduces completeness here.
        before = get_analysis('test')
        first, second = export_corrected('test'), export_corrected('test')
        self.assertEqual(first.body, second.body)
        self.assertEqual(before, get_analysis('test'))
        exported = pd.read_csv(io.BytesIO(first.body))
        self.assertEqual(list(exported.columns), list(self.original.columns))
        self.assertEqual(exported['id'].tolist(), [1, 2, 3, 4, 5, 6, 8])
        self.assertEqual(exported.iloc[0]['nombre'], 'Ana María')
        self.assertEqual(exported['ciudad'].tolist().count('Bogotá'), 6)
        pd.testing.assert_frame_equal(analyses['test']['original_frame'], self.original)
        self.assertEqual(get_empty_rows('test', 'correo')['row_numbers'], [4])
    def test_group_counts_all_occurrences_and_excluded_variants_are_untouched(self):
        frame = pd.DataFrame({'ciudad': ['Bogotá'] * 20 + ['BOGOTA'] * 12 + ['bogota'] * 8, 'nombre': ['BOGOTA'] * 40})
        analyses['test'] = create_state(frame, 'test.csv')
        proposal, group = self.groups()
        self.assertEqual(group['changed_values'], 20)
        result = apply_group('test', self.group_request(proposal, group, variants=['Bogotá', 'BOGOTA']))
        self.assertEqual(result['changed_values'], 12)
        work = analyses['test']['frame']
        self.assertEqual(work.ciudad.value_counts().to_dict(), {'Bogotá': 32, 'bogota': 8})
        self.assertEqual(work.nombre.tolist(), ['BOGOTA'] * 40)
        self.assertEqual(len(work), 40)
        self.assertEqual(len(result['analysis']['equivalences']), 1)
    def test_manual_canonical_and_no_transitive_fuzzy_group(self):
        analyses['test'] = create_state(pd.DataFrame({'ciudad': ['AAAA', 'AAAB', 'AABB']}), 'test.csv')
        proposal = find_groups('test', MatchRequest(column='ciudad', threshold=70))
        self.assertTrue(all(len(group['variants']) == 2 for group in proposal['groups']))
        group = proposal['groups'][0]
        result = apply_group('test', self.group_request(proposal, group, canonical='Valor manual'))
        self.assertEqual(result['changed_values'], 2)
        self.assertEqual(analyses['test']['frame'].ciudad.tolist(), ['Valor manual', 'Valor manual', 'AABB'])
    def test_stale_proposals_in_every_module_are_rejected(self):
        groups, group = self.groups()
        matches = find_matches('test', MatchRequest(column='ciudad'))
        duplicates = search_duplicates('test', DuplicateSearchRequest())
        self.cleanup()
        requests = [
            lambda: apply_group('test', self.group_request(groups, group)),
            lambda: apply_matches('test', MatchApproval(proposal_id=matches['proposal_id'], revision=0, approved_match_ids=[matches['matches'][0]['id']])),
            lambda: apply_duplicate_decisions('test', DuplicateApplyRequest(review_id=duplicates['review_id'], revision=0)),
            lambda: confirm_duplicate_decision('test', DuplicateDecisionRequest(review_id=duplicates['review_id'], revision=0, pair_id='1:7', action='keep_left')),
        ]
        for operation in requests:
            with self.assertRaises(HTTPException) as stale: operation()
            self.assertEqual(stale.exception.status_code, 409)
        self.assertEqual(get_analysis('test')['revision'], 1)
    def test_deletion_does_not_shift_later_cell_corrections(self):
        # Delete row 1, leaving a hole at the start of the stable index.
        review = search_duplicates('test', DuplicateSearchRequest())
        confirm_duplicate_decision('test', DuplicateDecisionRequest(review_id=review['review_id'], revision=0, pair_id='1:7', action='keep_right'))
        apply_duplicate_decisions('test', DuplicateApplyRequest(review_id=review['review_id'], revision=0))
        self.cleanup()
        proposal, group = self.groups()
        apply_group('test', self.group_request(proposal, group, variants=['BOGOTA']))
        work = analyses['test']['frame']
        self.assertEqual(work.index.tolist(), [1, 2, 3, 4, 5, 6, 7])
        self.assertEqual(work.loc[1, 'ciudad'], 'Bogotá')
        self.assertEqual(work.loc[2, 'ciudad'], 'bogota')
        self.assertEqual(work.loc[3, 'ciudad'], 'Medellín')
        self.assertEqual(work.loc[6, 'nombre'], 'Ana María')
    def test_invalid_operation_does_not_partially_apply(self):
        proposal, group = self.groups()
        before = get_analysis('test')
        with self.assertRaises(HTTPException):
            apply_group('test', self.group_request(proposal, group, variants=['BOGOTA', 'not approved']))
        self.assertEqual(before, get_analysis('test'))
        preview = preview_text_cleanup('test', TextCleanupRequest(columns=['nombre'], trim=True))
        with self.assertRaises(HTTPException):
            apply_text_cleanup('test', TextCleanupApproval(preview_id=preview['preview_id'], revision=0, approved_change_ids=[preview['changes'][0]['id'], 'unknown']))
        self.assertEqual(before, get_analysis('test'))
    def test_summary_failure_does_not_publish_partial_state_or_equivalence(self):
        proposal, group = self.groups()
        before = get_analysis('test')
        with patch('main.summary', side_effect=RuntimeError('derived metric failed')):
            with self.assertRaises(RuntimeError):
                apply_group('test', self.group_request(proposal, group))
        self.assertEqual(before, get_analysis('test'))
    def test_fuzzy_response_is_bounded_and_every_variant_matches_its_anchor(self):
        values = [f'Ciudad {index:04d}' for index in range(500)]
        analyses['test'] = create_state(pd.DataFrame({'ciudad': values}), 'test.csv')
        proposal = find_groups('test', MatchRequest(column='ciudad', threshold=85))
        self.assertLessEqual(sum(len(group['variants']) for group in proposal['groups']), 2 * len(values))
        for group in proposal['groups']:
            for variant in group['variants']:
                self.assertGreaterEqual(similarity(normalize_for_match(group['canonical']), normalize_for_match(variant['value'])), 85)
    def test_individual_correction_uses_stable_ids_after_deletion(self):
        review = search_duplicates('test', DuplicateSearchRequest())
        confirm_duplicate_decision('test', DuplicateDecisionRequest(review_id=review['review_id'], revision=0, pair_id='1:7', action='keep_right'))
        apply_duplicate_decisions('test', DuplicateApplyRequest(review_id=review['review_id'], revision=0))
        proposal = find_matches('test', MatchRequest(column='ciudad', threshold=100))
        change = next(match for match in proposal['matches'] if match['target_row'] == 3)
        apply_matches('test', MatchApproval(proposal_id=proposal['proposal_id'], revision=1, approved_match_ids=[change['id']]))
        work = analyses['test']['frame']
        self.assertEqual(work.loc[2, 'ciudad'], 'BOGOTA')
        self.assertEqual(work.loc[3, 'ciudad'], 'Medellín')
        self.assertEqual(work.loc[5, 'ciudad'], 'bogota')
    def test_replayed_apply_is_rejected_and_duplicate_ids_count_once(self):
        preview = preview_text_cleanup('test', TextCleanupRequest(columns=['nombre'], trim=True))
        identifier = preview['changes'][0]['id']
        request = TextCleanupApproval(preview_id=preview['preview_id'], revision=0, approved_change_ids=[identifier, identifier])
        self.assertEqual(apply_text_cleanup('test', request)['changed_values'], 1)
        before = get_analysis('test')
        with self.assertRaises(HTTPException): apply_text_cleanup('test', request)
        self.assertEqual(before, get_analysis('test'))
    def test_concurrent_approvals_commit_only_once(self):
        proposal, group = self.groups()
        request = self.group_request(proposal, group)
        def apply():
            try: return apply_group('test', request)['changed_values']
            except HTTPException as exc: return exc.status_code
        with ThreadPoolExecutor(max_workers=2) as executor:
            self.assertEqual(sorted(executor.map(lambda _: apply(), range(2))), [4, 409])
        self.assertEqual(get_analysis('test')['revision'], 1)
    def test_net_cell_metric_is_not_an_operation_counter(self):
        proposal, group = self.groups()
        apply_group('test', self.group_request(proposal, group, variants=['BOGOTA']))
        self.assertEqual(get_analysis('test')['modified_values'], 2)
        self.assertEqual(apply_group('test', self.group_request(*self.groups(), variants=['Bogotá'], canonical='Bogotá'))['changed_values'], 0)
        self.assertEqual(get_analysis('test')['modified_values'], 2)
    def test_cached_matches_preserve_best_earlier_reference(self):
        random.seed(17)
        values = ['AAAA', 'AAAB', 'AABB', 'AABC', 'BBBC', 'aaaa', ' AAAB ']
        frame = pd.DataFrame({'nombre': [random.choice(values) for _ in range(80)], 'id': range(80)})
        analyses['test'] = create_state(frame, 'test.csv')
        expected = []
        for target in range(len(frame)):
            best = None
            for reference in range(target):
                a, b = frame.loc[reference, 'nombre'], frame.loc[target, 'nombre']
                if a == b: continue
                score = similarity(normalize_for_match(a), normalize_for_match(b))
                if score >= 60 and (best is None or score > best[1]): best = (reference, score)
            if best: expected.append((target + 1, best[0] + 1, round(best[1], 1)))
        actual = find_matches('test', MatchRequest(column='nombre', threshold=60))
        self.assertEqual([(match['target_row'], match['reference_row'], match['similarity']) for match in actual['matches']], expected)

class HttpContractTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.__enter__()
    def tearDown(self):
        self.client.__exit__(None, None, None)
        analyses.clear()
    def upload(self, filename='grupos_demo.csv'):
        content = (EXAMPLES / filename).read_bytes()
        response = self.client.post('/api/analyze', files={'file': (filename, content, 'text/csv')})
        self.assertEqual(response.status_code, 200)
        return response.json(), content
    def post(self, id, path, body):
        response = self.client.post(f'/api/analyses/{id}/{path}', json=body)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()
    def test_complete_http_contract_matches_frontend_and_readonly_download(self):
        initial, content = self.upload()
        id = initial['analysis_id']
        preview = self.post(id, 'text-cleanup/preview', {'columns': ['nombre'], 'trim': True, 'collapse_spaces': True})
        result = self.post(id, 'text-cleanup/apply', {'preview_id': preview['preview_id'], 'revision': preview['revision'], 'approved_change_ids': [change['id'] for change in preview['changes']]})
        self.assertEqual(result['changed_values'], 5)
        groups = self.post(id, 'groups/search', {'column': 'ciudad', 'threshold': 85})
        group = groups['groups'][0]
        result = self.post(id, 'groups/apply', {'proposal_id': groups['proposal_id'], 'revision': groups['revision'], 'group_id': group['id'], 'variants': [v['value'] for v in group['variants']], 'canonical': 'Bogotá'})
        self.assertEqual(result['changed_values'], 4)
        review = self.post(id, 'duplicates/search', {'column': None, 'threshold': 85})
        self.post(id, 'duplicates/decision', {'review_id': review['review_id'], 'revision': review['revision'], 'pair_id': '1:7', 'action': 'keep_left'})
        self.assertEqual(len(pd.read_csv(io.BytesIO(self.client.get(f'/api/analyses/{id}/export').content))), 8)
        final = self.post(id, 'duplicates/apply', {'review_id': review['review_id'], 'revision': review['revision']})
        self.assertEqual(final['analysis']['rows'], 7)
        self.assertEqual(self.client.get(f'/api/analyses/{id}').json(), final['analysis'])
        first = self.client.get(f'/api/analyses/{id}/export')
        second = self.client.get(f'/api/analyses/{id}/export')
        self.assertEqual(first.content, second.content)
        self.assertIn('text/csv', first.headers['content-type'])
        self.assertEqual(first.headers['x-dataset-revision'], '3')
        self.assertEqual(list(pd.read_csv(io.BytesIO(first.content)).columns), initial['columns'])
        self.assertEqual((EXAMPLES / 'grupos_demo.csv').read_bytes(), content)
        self.assertEqual(self.client.get(f'/api/analyses/{id}/empty-rows', params={'column': 'correo'}).json()['row_numbers'], [4])
    def test_individual_approvals_and_http_stale_rejection(self):
        initial, _ = self.upload()
        id = initial['analysis_id']
        matches = self.post(id, 'matches', {'column': 'ciudad', 'threshold': 85})
        request = {'proposal_id': matches['proposal_id'], 'revision': matches['revision'], 'approved_match_ids': [matches['matches'][0]['id']]}
        result = self.post(id, 'matches/apply', request)
        self.assertEqual(result['changed_values'], 1)
        stale = self.client.post(f'/api/analyses/{id}/matches/apply', json=request)
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.json()['detail']['code'], 'stale_proposal')
        self.assertEqual(self.client.post(f'/api/analyses/{id}/groups/apply', json={}).status_code, 422)
    def test_fifty_record_example_and_upload_errors(self):
        result, _ = self.upload('clientes_demo.csv')
        self.assertEqual(result['rows'], 50)
        self.assertEqual(len(result['preview']), 50)
        self.assertEqual(self.client.post('/api/analyze', files={'file': ('empty.csv', b'', 'text/csv')}).status_code, 400)
        self.assertEqual(self.client.get('/api/analyses/missing').status_code, 404)
        self.assertEqual(self.client.post('/api/analyze', files={'file': ('large.csv', ('id\n' + '\n'.join(map(str, range(2001)))).encode(), 'text/csv')}).status_code, 413)
    def test_full_pipeline_with_existing_fifty_record_example(self):
        initial, source = self.upload('clientes_demo.csv')
        id = initial['analysis_id']
        original = analyses[id]['original_frame'].copy(deep=True)
        preview = self.post(id, 'text-cleanup/preview', {'columns': ['nombre', 'ciudad', 'correo'], 'trim': True, 'collapse_spaces': True})
        cleaned = self.post(id, 'text-cleanup/apply', {'preview_id': preview['preview_id'], 'revision': preview['revision'], 'approved_change_ids': [change['id'] for change in preview['changes']]})
        self.assertGreater(cleaned['changed_values'], 0)
        groups = self.post(id, 'groups/search', {'column': 'ciudad', 'threshold': 85})
        group = next(group for group in groups['groups'] if group['kind'] == 'normalized' and 'Bogotá' in [variant['value'] for variant in group['variants']])
        grouped = self.post(id, 'groups/apply', {'proposal_id': groups['proposal_id'], 'revision': groups['revision'], 'group_id': group['id'], 'variants': [variant['value'] for variant in group['variants']], 'canonical': 'Bogotá'})
        self.assertGreater(grouped['changed_values'], 0)
        self.assertEqual(grouped['analysis']['rows'], 50)
        review = self.post(id, 'duplicates/search', {'column': None})
        self.assertEqual(len(review['pairs']), 5)
        for pair in review['pairs']:
            self.post(id, 'duplicates/decision', {'review_id': review['review_id'], 'revision': review['revision'], 'pair_id': pair['id'], 'action': 'keep_left'})
        final = self.post(id, 'duplicates/apply', {'review_id': review['review_id'], 'revision': review['revision']})
        self.assertEqual(final['analysis']['rows'], 45)
        self.assertEqual(final['analysis']['deleted_rows'], 5)
        self.assertEqual(final['analysis']['exact_duplicate_count'], 0)
        content = self.client.get(f'/api/analyses/{id}/export').content
        exported = pd.read_csv(io.BytesIO(content))
        self.assertEqual(len(exported), 45)
        self.assertTrue(all(value == value.strip() for value in exported.nombre.dropna()))
        self.assertEqual(set(value for value in exported.ciudad.dropna() if normalize_for_match(value) == 'bogota'), {'Bogotá'})
        pd.testing.assert_frame_equal(analyses[id]['original_frame'], original)
        self.assertEqual((EXAMPLES / 'clientes_demo.csv').read_bytes(), source)
        self.assertEqual(self.client.get(f'/api/analyses/{id}/export').content, content)
    def test_cors_preflight_preserves_default_origin(self):
        response = self.client.options('/api/analyze', headers={'Origin': 'http://localhost:5173', 'Access-Control-Request-Method': 'POST'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['access-control-allow-origin'], 'http://localhost:5173')

if __name__ == '__main__':
    unittest.main()
