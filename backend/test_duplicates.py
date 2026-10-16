import io
import unittest

import pandas as pd
from fastapi import HTTPException

from main import (
    DuplicateDecisionRequest, DuplicateExportRequest, DuplicateSearchRequest,
    analyses, confirm_duplicate_decision, export_duplicate_decisions, search_duplicates,
)


class DuplicateReviewTests(unittest.TestCase):
    def setUp(self):
        self.frame = pd.DataFrame({
            "id": [1, 2, 3, 4, 4],
            "nombre": ["Ana Pérez", "ANA PEREZ", "Ana Perez", "Zoe", "Zoe"],
            "correo": ["ana@example.com", None, "otro@example.com", None, None],
        })
        analyses["test"] = {"frame": self.frame.copy(deep=True), "filename": "test.csv"}
        self.review = search_duplicates("test", DuplicateSearchRequest(column="nombre", threshold=100))

    def tearDown(self):
        analyses.clear()

    def decide(self, pair_id, action, review_id=None):
        return confirm_duplicate_decision("test", DuplicateDecisionRequest(
            review_id=review_id or self.review["review_id"], pair_id=pair_id, action=action,
        ))

    def exported(self):
        response = export_duplicate_decisions("test", DuplicateExportRequest(review_id=self.review["review_id"]))
        return pd.read_csv(io.BytesIO(response.body))

    def test_full_comparison_includes_exact_duplicates_and_field_differences(self):
        pairs = {pair["id"]: pair for pair in self.review["pairs"]}
        self.assertEqual(set(pairs), {"1:2", "1:3", "4:5"})
        self.assertEqual(pairs["1:2"]["differences"], ["id", "nombre", "correo"])
        self.assertEqual(pairs["1:2"]["left"]["correo"], "ana@example.com")
        self.assertIsNone(pairs["1:2"]["right"]["correo"])
        self.assertEqual(pairs["4:5"]["kind"], "exact")
        self.assertEqual(pairs["4:5"]["differences"], [])

    def test_without_confirmations_export_preserves_every_record(self):
        pd.testing.assert_frame_equal(self.exported(), self.frame)

    def test_export_only_applies_confirmed_removals_and_preserves_original(self):
        self.decide("1:2", "keep_left")
        self.decide("4:5", "keep_right")
        result = self.exported()
        self.assertEqual(result["id"].tolist(), [1, 3, 4])
        self.assertEqual(result.iloc[0]["nombre"], "Ana Pérez")
        pd.testing.assert_frame_equal(analyses["test"]["frame"], self.frame)
        # Repeat export produces the same copy, without applying changes twice.
        pd.testing.assert_frame_equal(self.exported(), result)

    def test_different_records_are_kept_and_cannot_be_removed_by_another_pair(self):
        self.decide("1:2", "different")
        pd.testing.assert_frame_equal(self.exported(), self.frame)
        with self.assertRaises(HTTPException) as conflict:
            self.decide("1:3", "keep_right")
        self.assertEqual(conflict.exception.status_code, 409)
        self.assertEqual(analyses["test"]["duplicate_review"]["decisions"], {"1:2": "different"})

    def test_conflicting_keep_decisions_are_atomic_and_can_be_undone(self):
        self.decide("1:2", "keep_right")
        with self.assertRaises(HTTPException):
            self.decide("1:3", "keep_left")
        self.assertEqual(self.exported()["id"].tolist(), [2, 3, 4, 4])
        undone = self.decide("1:2", "pending")
        self.assertEqual(undone["removed_rows"], [])
        pd.testing.assert_frame_equal(self.exported(), self.frame)
        self.decide("1:3", "keep_left")
        self.assertEqual(self.exported()["id"].tolist(), [1, 2, 4, 4])

    def test_shared_removals_are_counted_once(self):
        # Both pairs can confirm that record 1 is removed, keeping 2 and 3.
        self.decide("1:2", "keep_right")
        result = self.decide("1:3", "keep_right")
        self.assertEqual(result["removed_rows"], [1])
        self.assertEqual(len(self.exported()), 4)

    def test_new_search_invalidates_old_decisions_and_rejects_unknown_pairs(self):
        self.decide("1:2", "keep_left")
        with self.assertRaises(HTTPException):
            self.decide("wrong", "keep_left")
        old_id = self.review["review_id"]
        self.review = search_duplicates("test", DuplicateSearchRequest())
        self.assertEqual(len(self.review["pairs"]), 1)
        with self.assertRaises(HTTPException):
            self.decide("1:2", "keep_left", review_id=old_id)
        with self.assertRaises(HTTPException):
            export_duplicate_decisions("test", DuplicateExportRequest(review_id=old_id))
        pd.testing.assert_frame_equal(self.exported(), self.frame)

    def test_exact_duplicates_beyond_preview_and_numeric_only_dataset(self):
        analyses["test"]["frame"] = pd.DataFrame({"id": list(range(55)) + [10]})
        self.review = search_duplicates("test", DuplicateSearchRequest())
        self.assertEqual(self.review["pairs"][0]["id"], "11:56")
        self.decide("11:56", "keep_left")
        self.assertEqual(len(self.exported()), 55)

    def test_invalid_analysis_or_column(self):
        with self.assertRaises(HTTPException) as missing:
            search_duplicates("missing", DuplicateSearchRequest())
        self.assertEqual(missing.exception.status_code, 404)
        for column in ["id", "missing"]:
            with self.assertRaises(HTTPException):
                search_duplicates("test", DuplicateSearchRequest(column=column))


if __name__ == "__main__":
    unittest.main()
