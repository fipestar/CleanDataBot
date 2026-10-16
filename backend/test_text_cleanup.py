import io
import unittest

import pandas as pd
from fastapi import HTTPException
from pydantic import ValidationError

from main import (
    TextCleanupApproval, TextCleanupRequest, ExportRequest, analyses, clean_text,
    export_corrected, export_text_cleanup, preview_text_cleanup,
)


class TextCleanupTests(unittest.TestCase):
    def setUp(self):
        self.frame = pd.DataFrame({
            "nombre": ["  Ana   María  ", "LUIS", None, "   ", "sin cambios"],
            "ciudad": [" bogotá  ", " Cali ", "Lima", None, "Lima"],
            "edad": [20, 30, 40, 50, 60],
        })
        analyses["test"] = {"frame": self.frame.copy(deep=True), "filename": "clientes.csv", "matches": {}}

    def tearDown(self):
        analyses.clear()

    def test_options_work_independently_and_in_order(self):
        self.assertEqual(clean_text("  Ána   María  ", TextCleanupRequest(columns=["nombre"], trim=True)), "Ána   María")
        self.assertEqual(clean_text("  Ána   María  ", TextCleanupRequest(columns=["nombre"], collapse_spaces=True)), " Ána María ")
        self.assertEqual(clean_text(" Ána ", TextCleanupRequest(columns=["nombre"], letter_case="upper")), " ÁNA ")
        self.assertEqual(clean_text(" ÁNA ", TextCleanupRequest(columns=["nombre"], letter_case="lower")), " ána ")
        self.assertEqual(clean_text("  Ána   María  ", TextCleanupRequest(columns=["nombre"], trim=True, collapse_spaces=True, letter_case="upper")), "ÁNA MARÍA")

    def test_preview_then_approval_exports_exact_changes_without_mutating_original(self):
        preview = preview_text_cleanup("test", TextCleanupRequest(columns=["nombre", "ciudad"], trim=True, collapse_spaces=True, letter_case="lower"))
        self.assertEqual(preview["total"], 7)
        self.assertEqual(preview["changes"][0], {"row": 1, "column": "nombre", "original": "  Ana   María  ", "proposed": "ana maría"})
        pd.testing.assert_frame_equal(analyses["test"]["frame"], self.frame)
        response = export_text_cleanup("test", TextCleanupApproval(preview_id=preview["preview_id"]))
        result = pd.read_csv(io.BytesIO(response.body), keep_default_na=False)
        self.assertEqual(result["nombre"].tolist(), ["ana maría", "luis", "", "", "sin cambios"])
        self.assertEqual(result["ciudad"].tolist(), ["bogotá", "cali", "lima", "", "lima"])
        self.assertEqual(result["edad"].tolist(), [20, 30, 40, 50, 60])
        self.assertEqual(response.headers["X-Applied-Corrections"], "7")
        pd.testing.assert_frame_equal(analyses["test"]["frame"], self.frame)
        # Existing exports continue to operate on the original dataset.
        original_export = export_corrected("test", ExportRequest())
        self.assertEqual(pd.read_csv(io.BytesIO(original_export.body)).iloc[0]["nombre"], "  Ana   María  ")

    def test_preview_covers_rows_beyond_fifty_and_deduplicates_columns(self):
        analyses["test"]["frame"] = pd.DataFrame({"nombre": ["Ana"] * 55 + [" Ana "]})
        preview = preview_text_cleanup("test", TextCleanupRequest(columns=["nombre", "nombre"], trim=True))
        self.assertEqual(preview["total"], 1)
        self.assertEqual(preview["changes"][0]["row"], 56)

    def test_stale_or_unreviewed_approval_is_rejected(self):
        with self.assertRaises(HTTPException):
            export_text_cleanup("test", TextCleanupApproval(preview_id="unknown"))
        first = preview_text_cleanup("test", TextCleanupRequest(columns=["nombre"], trim=True))
        second = preview_text_cleanup("test", TextCleanupRequest(columns=["nombre"], letter_case="upper"))
        self.assertNotEqual(first["preview_id"], second["preview_id"])
        with self.assertRaises(HTTPException):
            export_text_cleanup("test", TextCleanupApproval(preview_id=first["preview_id"]))

    def test_invalid_requests_and_no_changes(self):
        for column in ["unknown", "edad"]:
            with self.assertRaises(HTTPException):
                preview_text_cleanup("test", TextCleanupRequest(columns=[column], trim=True))
        with self.assertRaises(HTTPException):
            preview_text_cleanup("test", TextCleanupRequest(columns=["nombre"]))
        with self.assertRaises(HTTPException):
            preview_text_cleanup("missing", TextCleanupRequest(columns=["nombre"], trim=True))
        with self.assertRaises(ValidationError):
            TextCleanupRequest(columns=[])
        with self.assertRaises(ValidationError):
            TextCleanupRequest(columns=["nombre"], letter_case="invalid")
        analyses["test"]["frame"] = pd.DataFrame({"nombre": ["Ana", None]})
        self.assertEqual(preview_text_cleanup("test", TextCleanupRequest(columns=["nombre"], trim=True))["total"], 0)


if __name__ == "__main__":
    unittest.main()
