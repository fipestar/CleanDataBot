from __future__ import annotations

import io
import json
import os
import re
import unicodedata
import uuid
from typing import Any, Literal

import pandas as pd
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field

try:
    from rapidfuzz import fuzz

    def similarity(a: str, b: str) -> float:
        return float(fuzz.ratio(a, b))
except ImportError:  # Fallback for a first run before optional packages are installed.
    from difflib import SequenceMatcher

    def similarity(a: str, b: str) -> float:
        return SequenceMatcher(None, a, b).ratio() * 100


app = FastAPI(title="CleanDataBot Demo", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in os.getenv(
            "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
        ).split(",")
        if origin.strip()
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory storage is intentional for this classroom prototype. It is cleared
# when the server restarts; the uploaded original is never changed.
analyses: dict[str, dict[str, Any]] = {}


class MatchRequest(BaseModel):
    column: str
    threshold: float = Field(default=85, ge=50, le=100)


class ExportRequest(BaseModel):
    approved_match_ids: list[str] = Field(default_factory=list)


class TextCleanupRequest(BaseModel):
    columns: list[str] = Field(min_length=1)
    trim: bool = False
    collapse_spaces: bool = False
    letter_case: Literal["unchanged", "upper", "lower"] = "unchanged"


class TextCleanupApproval(BaseModel):
    preview_id: str


class DuplicateSearchRequest(BaseModel):
    column: str | None = None
    threshold: float = Field(default=85, ge=60, le=100)


class DuplicateDecisionRequest(BaseModel):
    review_id: str
    pair_id: str
    action: Literal["keep_left", "keep_right", "different", "pending"]


class DuplicateExportRequest(BaseModel):
    review_id: str


def clean_text(value: str, request: TextCleanupRequest) -> str:
    if request.trim:
        value = value.strip()
    if request.collapse_spaces:
        value = re.sub(r" {2,}", " ", value)
    if request.letter_case == "upper":
        value = value.upper()
    elif request.letter_case == "lower":
        value = value.lower()
    return value


def normalize_for_match(value: Any) -> str:
    text = str(value).strip().casefold()
    text = "".join(
        char for char in unicodedata.normalize("NFD", text)
        if unicodedata.category(char) != "Mn"
    )
    return " ".join(text.split())


def json_records(frame: pd.DataFrame, limit: int = 50) -> list[dict[str, Any]]:
    # to_json converts NaN, numpy scalars, and common date values into JSON-safe values.
    return json.loads(frame.head(limit).to_json(orient="records", date_format="iso"))


def empty_values(series: pd.Series) -> pd.Series:
    return series.isna() | series.map(lambda value: isinstance(value, str) and not value.strip())


def data_type(series: pd.Series) -> str:
    populated = series.loc[~empty_values(series)]
    if populated.empty:
        return "Sin datos"
    inferred = pd.api.types.infer_dtype(populated, skipna=True)
    return {
        "boolean": "Booleano", "integer": "Entero", "floating": "Decimal",
        "mixed-integer-float": "Decimal", "datetime": "Fecha y hora",
        "datetime64": "Fecha y hora", "date": "Fecha", "string": "Texto",
        "unicode": "Texto", "bytes": "Texto",
    }.get(inferred, "Mixto")


def load_dataset(filename: str, content: bytes) -> pd.DataFrame:
    extension = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    try:
        if extension == "csv":
            try:
                return pd.read_csv(io.BytesIO(content))
            except UnicodeDecodeError:
                return pd.read_csv(io.BytesIO(content), encoding="latin-1")
        if extension in {"xlsx", "xls"}:
            return pd.read_excel(io.BytesIO(content))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"No se pudo leer el archivo: {exc}") from exc
    raise HTTPException(status_code=415, detail="Formato no compatible. Carga un archivo CSV o Excel.")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "app": "CleanDataBot Demo"}


@app.post("/api/analyze")
async def analyze(file: UploadFile = File(...)) -> dict[str, Any]:
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="El archivo está vacío.")
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Para esta demo, el archivo debe pesar menos de 10 MB.")

    frame = load_dataset(file.filename or "dataset.csv", content)
    if frame.empty or len(frame.columns) == 0:
        raise HTTPException(status_code=400, detail="El archivo no contiene registros o columnas para analizar.")
    if len(frame) > 2000:
        raise HTTPException(status_code=413, detail="Para esta demo, usa un archivo de máximo 2.000 filas.")

    frame.columns = frame.columns.map(str)

    analysis_id = str(uuid.uuid4())
    text_columns = [
        str(column) for column in frame.columns
        if pd.api.types.is_object_dtype(frame[column]) or pd.api.types.is_string_dtype(frame[column])
    ]
    nulls_by_column = {
        str(column): int(empty_values(frame[column]).sum()) for column in frame.columns
    }
    column_profiles = [
        {
            "name": column,
            "data_type": data_type(frame[column]),
            "empty_count": nulls_by_column[column],
            "completeness": round(100 * (len(frame) - nulls_by_column[column]) / len(frame), 2),
            "unique_count": int(frame.loc[~empty_values(frame[column]), column].nunique()),
        }
        for column in frame.columns
    ]
    analyses[analysis_id] = {
        "frame": frame.copy(deep=True),
        "filename": file.filename or "dataset.csv",
        "matches": {},
    }

    return {
        "analysis_id": analysis_id,
        "filename": file.filename or "dataset.csv",
        "columns": [str(column) for column in frame.columns],
        "text_columns": text_columns,
        "rows": int(len(frame)),
        "column_count": int(len(frame.columns)),
        "null_count": sum(nulls_by_column.values()),
        "exact_duplicate_count": int(frame.duplicated().sum()),
        "nulls_by_column": nulls_by_column,
        "column_profiles": column_profiles,
        "preview": json_records(frame),
        "preview_limit": min(50, len(frame)),
    }


@app.get("/api/analyses/{analysis_id}/empty-rows")
def get_empty_rows(analysis_id: str, column: str) -> dict[str, Any]:
    analysis = analyses.get(analysis_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="El análisis ya no está disponible. Vuelve a cargar el archivo.")
    frame = analysis["frame"]
    if column not in frame.columns:
        raise HTTPException(status_code=400, detail="La columna seleccionada no existe en el archivo.")
    affected = frame.loc[empty_values(frame[column])]
    return {
        "rows": json_records(affected, limit=len(affected)),
        "row_numbers": [int(index) + 1 for index in affected.index],
        "total": len(affected),
    }


@app.post("/api/analyses/{analysis_id}/text-cleanup/preview")
def preview_text_cleanup(analysis_id: str, request: TextCleanupRequest) -> dict[str, Any]:
    analysis = analyses.get(analysis_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="El análisis ya no está disponible. Vuelve a cargar el archivo.")
    frame = analysis["frame"]
    for column in request.columns:
        if column not in frame.columns:
            raise HTTPException(status_code=400, detail="La columna seleccionada no existe en el archivo.")
        if not (pd.api.types.is_object_dtype(frame[column]) or pd.api.types.is_string_dtype(frame[column])):
            raise HTTPException(status_code=400, detail="Selecciona únicamente columnas de texto.")
    if not (request.trim or request.collapse_spaces or request.letter_case != "unchanged"):
        raise HTTPException(status_code=400, detail="Selecciona al menos una transformación.")

    changes = []
    for column in dict.fromkeys(request.columns):
        for index, original in frame[column].items():
            if not isinstance(original, str):
                continue
            proposed = clean_text(original, request)
            if proposed != original:
                changes.append({"row": int(index) + 1, "column": column, "original": original, "proposed": proposed})
    preview = {"preview_id": str(uuid.uuid4()), "changes": changes, "total": len(changes)}
    # Keep the exact proposal reviewed by the user; a new preview replaces the old one.
    analysis["text_cleanup_preview"] = preview
    return preview


@app.post("/api/analyses/{analysis_id}/text-cleanup/export")
def export_text_cleanup(analysis_id: str, request: TextCleanupApproval) -> Response:
    analysis = analyses.get(analysis_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="El análisis ya no está disponible. Vuelve a cargar el archivo.")
    preview = analysis.get("text_cleanup_preview")
    if preview is None or preview["preview_id"] != request.preview_id:
        raise HTTPException(status_code=400, detail="La previsualización ya no es válida. Genera una nueva antes de aprobar.")
    corrected = analysis["frame"].copy(deep=True)
    for change in preview["changes"]:
        corrected.at[change["row"] - 1, change["column"]] = change["proposed"]
    return csv_response(corrected, analysis["filename"], preview["total"], suffix="limpio")


def duplicate_review(analysis_id: str, review_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    analysis = analyses.get(analysis_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="El análisis ya no está disponible. Vuelve a cargar el archivo.")
    review = analysis.get("duplicate_review")
    if review is None or review["review_id"] != review_id:
        raise HTTPException(status_code=400, detail="La revisión ya no es válida. Busca los duplicados nuevamente.")
    return analysis, review


def duplicate_removals(pairs: dict[str, Any], decisions: dict[str, str]) -> set[int]:
    removed: set[int] = set()
    protected: set[int] = set()
    for pair_id, action in decisions.items():
        pair = pairs[pair_id]
        left, right = pair["left_row"], pair["right_row"]
        if action == "different":
            protected.update([left, right])
        elif action == "keep_left":
            protected.add(left)
            removed.add(right)
        elif action == "keep_right":
            protected.add(right)
            removed.add(left)
    if removed & protected:
        rows = ", ".join(map(str, sorted(removed & protected)))
        raise HTTPException(status_code=409, detail=f"Decisiones incompatibles para los registros {rows}: se han marcado para conservar y eliminar. Deshaz la decisión anterior antes de confirmar.")
    return removed


@app.post("/api/analyses/{analysis_id}/duplicates/search")
def search_duplicates(analysis_id: str, request: DuplicateSearchRequest) -> dict[str, Any]:
    analysis = analyses.get(analysis_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="El análisis ya no está disponible. Vuelve a cargar el archivo.")
    frame = analysis["frame"]
    if request.column is not None and (request.column not in frame.columns or not (
        pd.api.types.is_object_dtype(frame[request.column]) or pd.api.types.is_string_dtype(frame[request.column])
    )):
        raise HTTPException(status_code=400, detail="Selecciona una columna de texto válida.")
    records = json_records(frame, len(frame))
    normalized = [
        normalize_for_match(row[request.column]) if request.column is not None and row[request.column] is not None else ""
        for row in records
    ]
    first_exact: dict[str, int] = {}
    pairs = []
    for right, record in enumerate(records):
        signature = json.dumps(record, ensure_ascii=False, sort_keys=True)
        exact = signature in first_exact
        left = first_exact.setdefault(signature, right)
        score = 100.0
        if not exact:
            if not normalized[right]:
                continue
            best = None
            for candidate in range(right):
                if not normalized[candidate]:
                    continue
                candidate_score = similarity(normalized[candidate], normalized[right])
                if candidate_score >= request.threshold and (best is None or candidate_score > best[1]):
                    best = (candidate, candidate_score)
            if best is None:
                continue
            left, score = best
        differences = [column for column in frame.columns if records[left][column] != record[column]]
        pairs.append({
            "id": f"{left + 1}:{right + 1}", "left_row": left + 1, "right_row": right + 1,
            "left": records[left], "right": record, "differences": differences,
            "kind": "exact" if exact else "similar", "similarity": round(score, 1),
        })
    review_id = str(uuid.uuid4())
    analysis["duplicate_review"] = {"review_id": review_id, "pairs": {pair["id"]: pair for pair in pairs}, "decisions": {}}
    return {"review_id": review_id, "pairs": pairs, "decisions": {}}


@app.post("/api/analyses/{analysis_id}/duplicates/decision")
def confirm_duplicate_decision(analysis_id: str, request: DuplicateDecisionRequest) -> dict[str, Any]:
    _, review = duplicate_review(analysis_id, request.review_id)
    if request.pair_id not in review["pairs"]:
        raise HTTPException(status_code=400, detail="El par seleccionado no pertenece a esta revisión.")
    decisions = dict(review["decisions"])
    if request.action == "pending":
        decisions.pop(request.pair_id, None)
    else:
        decisions[request.pair_id] = request.action
    removed = duplicate_removals(review["pairs"], decisions)
    review["decisions"] = decisions
    return {"decisions": decisions, "removed_rows": sorted(removed)}


@app.post("/api/analyses/{analysis_id}/duplicates/export")
def export_duplicate_decisions(analysis_id: str, request: DuplicateExportRequest) -> Response:
    analysis, review = duplicate_review(analysis_id, request.review_id)
    removed = duplicate_removals(review["pairs"], review["decisions"])
    corrected = analysis["frame"].drop(index=[row - 1 for row in removed]).copy(deep=True)
    return csv_response(corrected, analysis["filename"], len(removed), suffix="revisado")


@app.post("/api/analyses/{analysis_id}/matches")
def find_matches(analysis_id: str, request: MatchRequest) -> dict[str, Any]:
    analysis = analyses.get(analysis_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="El análisis ya no está disponible. Vuelve a cargar el archivo.")

    frame: pd.DataFrame = analysis["frame"]
    if request.column not in frame.columns:
        raise HTTPException(status_code=400, detail="La columna seleccionada no existe en el archivo.")
    if not (
        pd.api.types.is_object_dtype(frame[request.column])
        or pd.api.types.is_string_dtype(frame[request.column])
    ):
        raise HTTPException(status_code=400, detail="Selecciona una columna de texto para buscar similitudes.")

    values = frame[request.column].tolist()
    matches: list[dict[str, Any]] = []
    exact_duplicate_rows = frame.duplicated(keep="first").tolist()
    # For each later row, recommend at most one earlier value: the highest-scoring
    # candidate. This keeps each proposed correction unambiguous in the demo.
    for target_index in range(1, len(values)):
        if exact_duplicate_rows[target_index]:
            continue  # It is already reported in the exact-duplicate metric.
        target = values[target_index]
        if pd.isna(target) or not str(target).strip():
            continue
        target_text = str(target).strip()
        target_normalized = normalize_for_match(target_text)
        best: tuple[int, str, float] | None = None

        for reference_index in range(target_index):
            reference = values[reference_index]
            if pd.isna(reference) or not str(reference).strip():
                continue
            reference_text = str(reference).strip()
            if reference_text == target_text:
                continue  # Exact same values do not need a fuzzy suggestion.
            reference_normalized = normalize_for_match(reference_text)
            score = similarity(reference_normalized, target_normalized)
            if score >= request.threshold and (best is None or score > best[2]):
                best = (reference_index, reference_text, score)

        if best is not None:
            reference_index, canonical_value, score = best
            match_id = f"{request.column}:{target_index}:{reference_index}"
            matches.append({
                "id": match_id,
                "target_row": target_index + 1,
                "reference_row": reference_index + 1,
                "current_value": target_text,
                "suggested_value": canonical_value,
                "similarity": round(score, 1),
            })

    analysis["matches"] = {match["id"]: match for match in matches}
    analysis["match_column"] = request.column
    return {"column": request.column, "threshold": request.threshold, "matches": matches}


@app.post("/api/analyses/{analysis_id}/export")
def export_corrected(analysis_id: str, request: ExportRequest) -> Response:
    analysis = analyses.get(analysis_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="El análisis ya no está disponible. Vuelve a cargar el archivo.")

    known_matches: dict[str, dict[str, Any]] = analysis.get("matches", {})
    unknown_ids = [match_id for match_id in request.approved_match_ids if match_id not in known_matches]
    if unknown_ids:
        raise HTTPException(status_code=400, detail="Hay sugerencias seleccionadas que no pertenecen a este análisis.")

    # Apply approved changes to a copy. The stored original remains untouched.
    corrected: pd.DataFrame = analysis["frame"].copy(deep=True)
    column = analysis.get("match_column")
    for match_id in request.approved_match_ids:
        match = known_matches[match_id]
        corrected.at[match["target_row"] - 1, column] = match["suggested_value"]

    return csv_response(corrected, analysis["filename"], len(request.approved_match_ids))


def csv_response(frame: pd.DataFrame, filename: str, corrections: int, suffix: str = "corregido") -> Response:
    csv_bytes = frame.to_csv(index=False).encode("utf-8-sig")
    original_name = filename.rsplit(".", 1)[0]
    output_name = f"{original_name}_{suffix}.csv"
    return Response(
        content=csv_bytes,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{output_name}"',
            "X-Applied-Corrections": str(corrections),
            "Access-Control-Expose-Headers": "Content-Disposition, X-Applied-Corrections",
        },
    )
