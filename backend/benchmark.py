"""Deterministic, local measurements; timings exclude HTTP/network and startup."""
import argparse
import asyncio
import importlib.metadata
import json
import platform
import statistics
import tempfile
import time
from pathlib import Path

import pandas as pd
from fastapi import UploadFile

from main import DuplicateSearchRequest, MatchRequest, analyses, analyze, find_groups, find_matches, search_duplicates


def dataset(size):
    cities = ["Bogotá", "BOGOTA", "bogota", "  Bogotá  ", "Bogota", "Medellín", "MEDELLIN", "Cali"]
    rows = []
    for index in range(size):
        row = {"id": index + 1, "nombre": f" Cliente  {index % 100:03d} ",
               "ciudad": cities[index % len(cities)], "correo": f"c{index}@example.com",
               "telefono": None if index % 7 == 0 else f"310{index:07d}", "nota": "  Pendiente  "}
        rows.append(dict(rows[-1]) if index > 0 and index % 17 == 0 else row)
    return pd.DataFrame(rows)


async def measure(repeats):
    results = []
    for size in [50, 500, 2000]:
        frame = dataset(size)
        content = frame.to_csv(index=False).encode()
        analysis_times, match_times, group_times, duplicate_times = [], [], [], []
        for _ in range(repeats):
            with tempfile.SpooledTemporaryFile() as source:
                source.write(content)
                source.seek(0)
                start = time.perf_counter()
                result = await analyze(UploadFile(filename="benchmark.csv", file=source))
                analysis_times.append((time.perf_counter() - start) * 1000)
            start = time.perf_counter()
            matches = find_matches(result["analysis_id"], MatchRequest(column="ciudad", threshold=85))
            match_times.append((time.perf_counter() - start) * 1000)
            start = time.perf_counter()
            groups = find_groups(result["analysis_id"], MatchRequest(column="ciudad", threshold=85))
            group_times.append((time.perf_counter() - start) * 1000)
            start = time.perf_counter()
            duplicates = search_duplicates(result["analysis_id"], DuplicateSearchRequest(column="ciudad", threshold=85))
            duplicate_times.append((time.perf_counter() - start) * 1000)
            analyses.clear()
        record = {"rows": size, "columns": len(frame.columns),
                  "distinct_cities": int(frame.ciudad.nunique()),
                  "analysis_ms": analysis_times, "matches_ms": match_times,
                  "analysis_median_ms": statistics.median(analysis_times),
                  "matches_median_ms": statistics.median(match_times), "suggestions": len(matches["matches"]),
                  "groups_ms": group_times, "groups_median_ms": statistics.median(group_times),
                  "groups": len(groups["groups"]), "duplicates_ms": duplicate_times,
                  "duplicates_median_ms": statistics.median(duplicate_times), "pairs": len(duplicates["pairs"])}
        results.append(record)
        print(json.dumps(record), flush=True)
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    report = {"platform": platform.platform(), "processor": platform.processor(),
              "python": platform.python_version(),
              "packages": {name: importlib.metadata.version(name) for name in ["pandas", "fastapi", "rapidfuzz"]},
              "repeats": args.repeats, "results": asyncio.run(measure(args.repeats))}
    Path(args.output).write_text(json.dumps(report, indent=2), encoding="utf-8")
