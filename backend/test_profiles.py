import asyncio
import tempfile
import unittest

import pandas as pd
from fastapi import HTTPException, UploadFile

from main import analyses, analyze, data_type, get_empty_rows


class ColumnProfileTests(unittest.TestCase):
    def tearDown(self):
        analyses.clear()

    def upload(self, content):
        with tempfile.SpooledTemporaryFile() as source:
            source.write(content.encode())
            source.seek(0)
            return asyncio.run(analyze(UploadFile(filename="test.csv", file=source)))

    def test_filter_includes_empty_rows_beyond_preview_and_excludes_healthy_rows(self):
        content = "id,nombre\n" + "".join(
            f'{index},{"" if index == 55 else "   " if index == 60 else "Ana"}\n'
            for index in range(1, 66)
        )
        result = self.upload(content)
        profile = result["column_profiles"][1]
        self.assertEqual(profile["data_type"], "Texto")
        self.assertEqual(profile["empty_count"], 2)
        self.assertEqual(profile["unique_count"], 1)
        self.assertEqual(profile["completeness"], round(63 / 65 * 100, 2))
        self.assertEqual(result["null_count"], 2)
        self.assertEqual(len(result["preview"]), 50)
        filtered = get_empty_rows(result["analysis_id"], "nombre")
        self.assertEqual(filtered["row_numbers"], [55, 60])
        self.assertEqual([row["id"] for row in filtered["rows"]], [55, 60])
        self.assertEqual(filtered["total"], 2)
        self.assertEqual(get_empty_rows(result["analysis_id"], "id")["rows"], [])

    def test_all_empty_and_complete_columns(self):
        result = self.upload('id,vacio,activo\n1,,True\n2,"  ",False\n')
        profiles = {profile["name"]: profile for profile in result["column_profiles"]}
        self.assertEqual(profiles["vacio"]["completeness"], 0)
        self.assertEqual(profiles["vacio"]["unique_count"], 0)
        self.assertEqual(profiles["vacio"]["data_type"], "Sin datos")
        self.assertEqual(profiles["id"]["completeness"], 100)
        self.assertEqual(profiles["id"]["data_type"], "Entero")
        self.assertEqual(profiles["activo"]["data_type"], "Booleano")
        self.assertEqual(data_type(pd.Series([1.5, 2.7])), "Decimal")
        self.assertEqual(data_type(pd.Series(pd.to_datetime(["2026-01-01"]))), "Fecha y hora")

    def test_unknown_analysis_and_column(self):
        with self.assertRaises(HTTPException) as missing:
            get_empty_rows("missing", "id")
        self.assertEqual(missing.exception.status_code, 404)
        result = self.upload("id\n1\n")
        with self.assertRaises(HTTPException) as invalid:
            get_empty_rows(result["analysis_id"], "missing")
        self.assertEqual(invalid.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
