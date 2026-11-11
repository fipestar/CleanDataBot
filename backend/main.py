from __future__ import annotations

import io
import json
import os
import re
import threading
import unicodedata
import uuid
from typing import Any, Literal
from urllib.parse import quote

import pandas as pd
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field

try:
    from rapidfuzz import fuzz
    def similarity(a: str, b: str) -> float:
        return float(fuzz.ratio(a, b))
except ImportError:
    from difflib import SequenceMatcher
    def similarity(a: str, b: str) -> float:
        return SequenceMatcher(None, a, b).ratio() * 100

app = FastAPI(title="CleanDataBot Demo", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.getenv(
        "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    ).split(",") if origin.strip()],
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)
# Single-process session storage. Mutations are serialized per analysis.
analyses: dict[str, dict[str, Any]] = {}

class MatchRequest(BaseModel):
    column: str
    threshold: float = Field(default=85, ge=50, le=100)

class RevisionRequest(BaseModel):
    revision: int = Field(ge=0)

class MatchApproval(RevisionRequest):
    proposal_id: str
    approved_match_ids: list[str] = Field(min_length=1)

class TextCleanupRequest(BaseModel):
    columns: list[str] = Field(min_length=1)
    trim: bool = False
    collapse_spaces: bool = False
    letter_case: Literal["unchanged", "upper", "lower"] = "unchanged"

class TextCleanupApproval(RevisionRequest):
    preview_id: str
    approved_change_ids: list[str] = Field(min_length=1)

class DuplicateSearchRequest(BaseModel):
    column: str | None = None
    threshold: float = Field(default=85, ge=60, le=100)

class DuplicateApplyRequest(RevisionRequest):
    review_id: str

class DuplicateDecisionRequest(DuplicateApplyRequest):
    pair_id: str
    action: Literal["keep_left", "keep_right", "different", "pending"]

class GroupApproval(RevisionRequest):
    proposal_id: str
    group_id: str
    variants: list[str] = Field(min_length=1)
    canonical: str = Field(min_length=1)

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
    text = "".join(char for char in unicodedata.normalize("NFD", text) if unicodedata.category(char) != "Mn")
    return " ".join(text.split())

def json_records(frame: pd.DataFrame, limit: int = 50) -> list[dict[str, Any]]:
    return json.loads(frame.head(limit).to_json(orient="records", date_format="iso"))

def empty_values(series: pd.Series) -> pd.Series:
    return series.isna() | series.map(lambda value: isinstance(value, str) and not value.strip())

def data_type(series: pd.Series) -> str:
    populated = series.loc[~empty_values(series)]
    if populated.empty:
        return "Sin datos"
    return {"boolean": "Booleano", "integer": "Entero", "floating": "Decimal",
        "mixed-integer-float": "Decimal", "datetime": "Fecha y hora", "datetime64": "Fecha y hora",
        "date": "Fecha", "string": "Texto", "unicode": "Texto", "bytes": "Texto"
    }.get(pd.api.types.infer_dtype(populated, skipna=True), "Mixto")

def create_state(frame: pd.DataFrame, filename: str) -> dict[str, Any]:
    frame = frame.copy(deep=True).reset_index(drop=True)
    frame.columns = frame.columns.map(str)
    if not frame.columns.is_unique:
        raise HTTPException(status_code=400, detail="Los nombres de las columnas deben ser únicos.")
    return {"frame": frame, "original_frame": frame.copy(deep=True), "filename": filename,
            "revision": 0, "lock": threading.RLock(), "equivalences": []}

def get_state(analysis_id: str) -> dict[str, Any]:
    state = analyses.get(analysis_id)
    if state is None:
        raise HTTPException(status_code=404, detail="El análisis ya no está disponible. Vuelve a cargar el archivo.")
    return state

def require_text_column(frame: pd.DataFrame, column: str) -> None:
    if column not in frame.columns or not (pd.api.types.is_object_dtype(frame[column]) or pd.api.types.is_string_dtype(frame[column])):
        raise HTTPException(status_code=400, detail="Selecciona una columna de texto válida.")

def summary(analysis_id: str, state: dict[str, Any]) -> dict[str, Any]:
    frame, original = state["frame"], state["original_frame"]
    nulls = {column: int(empty_values(frame[column]).sum()) for column in frame.columns}
    aligned = original.loc[frame.index]
    same = frame.eq(aligned) | (frame.isna() & aligned.isna())
    modified = int((~same.fillna(False)).sum().sum())
    cells = frame.size
    return {"analysis_id": analysis_id, "revision": state["revision"], "filename": state["filename"],
        "columns": list(frame.columns),
        "text_columns": [column for column in frame.columns if pd.api.types.is_object_dtype(frame[column]) or pd.api.types.is_string_dtype(frame[column])],
        "rows": len(frame), "original_rows": len(original), "column_count": len(frame.columns),
        "modified_values": modified, "deleted_rows": len(original) - len(frame),
        "null_count": sum(nulls.values()), "exact_duplicate_count": int(frame.duplicated().sum()),
        "completeness": round(100 * (cells - sum(nulls.values())) / cells, 2) if cells else 100.0,
        "nulls_by_column": nulls,
        "column_profiles": [{"name": column, "data_type": data_type(frame[column]), "empty_count": nulls[column],
            "completeness": round(100 * (len(frame) - nulls[column]) / len(frame), 2) if len(frame) else 100.0,
            "unique_count": int(frame.loc[~empty_values(frame[column]), column].nunique())} for column in frame.columns],
        "preview": json_records(frame), "preview_limit": min(50, len(frame)),
        "preview_row_numbers": [int(index) + 1 for index in frame.head(50).index],
        "equivalences": list(state["equivalences"])}

def require_proposal(state: dict[str, Any], key: str, identifier: str, revision: int) -> dict[str, Any]:
    proposal = state.get(key)
    if revision != state["revision"] or proposal is None or proposal["id"] != identifier or proposal["revision"] != revision:
        raise HTTPException(status_code=409, detail={"code": "stale_proposal",
            "message": "La propuesta está obsoleta o ya fue aplicada. Actualiza el dataset y genera una nueva revisión."})
    return proposal

def selected_changes(changes: list[dict[str, Any]], identifiers: list[str]) -> list[dict[str, Any]]:
    known = {change["id"]: change for change in changes}
    if not identifiers or any(identifier not in known for identifier in identifiers):
        raise HTTPException(status_code=400, detail="Hay cambios seleccionados que no pertenecen a esta propuesta.")
    return [known[identifier] for identifier in dict.fromkeys(identifiers)]

def commit(analysis_id: str, state: dict[str, Any], frame: pd.DataFrame, changed: int = 0,
           deleted: int = 0, equivalence: dict[str, Any] | None = None) -> dict[str, Any]:
    # Called with the lock held, after validating the entire operation on a copy.
    if changed or deleted:
        next_state = {**state, "frame": frame, "revision": state["revision"] + 1,
                      "equivalences": state["equivalences"] + ([equivalence] if equivalence else [])}
        # Even derived metrics must succeed before publishing the new version.
        result = summary(analysis_id, next_state)
        state.update(next_state)
        for key in ["cleanup", "matches", "groups", "duplicates"]:
            state.pop(key, None)
    else:
        result = summary(analysis_id, state)
    return {"analysis": result, "changed_values": changed, "deleted_rows": deleted}

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
    analysis_id = str(uuid.uuid4())
    state = create_state(frame, file.filename or "dataset.csv")
    analyses[analysis_id] = state
    return summary(analysis_id, state)

@app.get("/api/analyses/{analysis_id}")
def get_analysis(analysis_id: str) -> dict[str, Any]:
    state = get_state(analysis_id)
    with state["lock"]:
        return summary(analysis_id, state)

@app.get("/api/analyses/{analysis_id}/empty-rows")
def get_empty_rows(analysis_id: str, column: str) -> dict[str, Any]:
    state = get_state(analysis_id)
    with state["lock"]:
        frame = state["frame"]
        if column not in frame.columns:
            raise HTTPException(status_code=400, detail="La columna seleccionada no existe en el archivo.")
        affected = frame.loc[empty_values(frame[column])]
        return {"revision": state["revision"], "rows": json_records(affected, len(affected)),
                "row_numbers": [int(index) + 1 for index in affected.index], "total": len(affected)}

@app.post("/api/analyses/{analysis_id}/text-cleanup/preview")
def preview_text_cleanup(analysis_id: str, request: TextCleanupRequest) -> dict[str, Any]:
    state = get_state(analysis_id)
    with state["lock"]:
        frame = state["frame"]
        for column in request.columns:
            require_text_column(frame, column)
        if not (request.trim or request.collapse_spaces or request.letter_case != "unchanged"):
            raise HTTPException(status_code=400, detail="Selecciona al menos una transformación.")
        changes = []
        for column in dict.fromkeys(request.columns):
            for index, original in frame[column].items():
                if not isinstance(original, str):
                    continue
                proposed = clean_text(original, request)
                if proposed != original:
                    changes.append({"id": str(uuid.uuid4()), "row": int(index) + 1, "column": column, "original": original, "proposed": proposed})
        preview_id = str(uuid.uuid4())
        proposal = {"id": preview_id, "preview_id": preview_id, "revision": state["revision"], "changes": changes, "total": len(changes)}
        state["cleanup"] = proposal
        return proposal

@app.post("/api/analyses/{analysis_id}/text-cleanup/apply")
def apply_text_cleanup(analysis_id: str, request: TextCleanupApproval) -> dict[str, Any]:
    state = get_state(analysis_id)
    with state["lock"]:
        proposal = require_proposal(state, "cleanup", request.preview_id, request.revision)
        changes = selected_changes(proposal["changes"], request.approved_change_ids)
        corrected = state["frame"].copy(deep=True)
        for change in changes:
            corrected.at[change["row"] - 1, change["column"]] = change["proposed"]
        return commit(analysis_id, state, corrected, changed=len(changes))

@app.post("/api/analyses/{analysis_id}/matches")
def find_matches(analysis_id: str, request: MatchRequest) -> dict[str, Any]:
    state = get_state(analysis_id)
    with state["lock"]:
        frame = state["frame"]
        require_text_column(frame, request.column)
        # Compare distinct values once; preserve the earliest reference on ties.
        earlier: dict[str, tuple[int, str]] = {}
        proposals: dict[str, tuple[int, str, float] | None] = {}
        duplicate_rows = frame.duplicated(keep="first")
        matches = []
        for index, target in frame[request.column].items():
            if not isinstance(target, str) or not target.strip():
                continue
            if target not in proposals:
                normalized = normalize_for_match(target)
                best = None
                for reference, (reference_index, reference_normalized) in earlier.items():
                    score = similarity(reference_normalized, normalized)
                    if score >= request.threshold and (best is None or score > best[2]):
                        best = (reference_index, reference, score)
                    # A newly seen reference can improve future occurrences of an
                    # older target. Do not freeze the first occurrence's proposal.
                    previous = proposals[reference]
                    if score >= request.threshold and (previous is None or score > previous[2]):
                        proposals[reference] = (int(index), target, score)
                proposals[target] = best
                earlier[target] = (int(index), normalized)
            best = proposals[target]
            if best is not None and not duplicate_rows.loc[index]:
                reference_index, canonical, score = best
                matches.append({"id": str(uuid.uuid4()), "target_row": int(index) + 1,
                    "reference_row": reference_index + 1, "current_value": target,
                    "suggested_value": canonical, "similarity": round(score, 1)})
        proposal_id = str(uuid.uuid4())
        proposal = {"id": proposal_id, "proposal_id": proposal_id, "revision": state["revision"],
                    "column": request.column, "threshold": request.threshold, "matches": matches}
        state["matches"] = proposal
        return proposal

@app.post("/api/analyses/{analysis_id}/matches/apply")
def apply_matches(analysis_id: str, request: MatchApproval) -> dict[str, Any]:
    state = get_state(analysis_id)
    with state["lock"]:
        proposal = require_proposal(state, "matches", request.proposal_id, request.revision)
        changes = selected_changes(proposal["matches"], request.approved_match_ids)
        corrected = state["frame"].copy(deep=True)
        for change in changes:
            corrected.at[change["target_row"] - 1, proposal["column"]] = change["suggested_value"]
        return commit(analysis_id, state, corrected, changed=len(changes))

@app.post("/api/analyses/{analysis_id}/groups/search")
def find_groups(analysis_id: str, request: MatchRequest) -> dict[str, Any]:
    state = get_state(analysis_id)
    with state["lock"]:
        frame = state["frame"]
        require_text_column(frame, request.column)
        counts = frame[request.column].value_counts(sort=False)
        buckets: dict[str, list[dict[str, Any]]] = {}
        for value, count in counts.items():
            if isinstance(value, str) and value.strip():
                buckets.setdefault(normalize_for_match(value), []).append({"value": value, "count": int(count)})
        groups = []
        def add_group(variants, canonical, kind):
            groups.append({"id": str(uuid.uuid4()), "column": request.column, "kind": kind,
                "canonical": canonical, "variants": variants,
                "changed_values": sum(v["count"] for v in variants if v["value"] != canonical)})
        items = list(buckets.items())
        assigned: set[str] = set()
        for position, (normalized, variants) in enumerate(items):
            canonical = max(variants, key=lambda variant: variant["count"])["value"]
            equivalent = [{**variant, "relation": "normalized", "similarity": 100.0} for variant in variants]
            if len(variants) > 1:
                add_group(equivalent, canonical, "normalized")
            if normalized in assigned:
                continue
            fuzzy = []
            included = []
            for other_normalized, other_variants in items[position + 1:]:
                if other_normalized in assigned:
                    continue
                score = similarity(normalized, other_normalized)
                if score >= request.threshold:
                    fuzzy.extend({**variant, "relation": "approximate", "similarity": round(score, 1)} for variant in other_variants)
                    included.append(other_normalized)
            if fuzzy:
                # Direct matches to this anchor only, never transitive edges.
                # Each normalized bucket belongs to at most one fuzzy star, to
                # avoid a quadratic response with thousands of similar variants.
                assigned.update([normalized, *included])
                add_group(equivalent + fuzzy, canonical, "approximate")
        proposal_id = str(uuid.uuid4())
        proposal = {"id": proposal_id, "proposal_id": proposal_id, "revision": state["revision"], "column": request.column, "groups": groups}
        state["groups"] = proposal
        return proposal

@app.post("/api/analyses/{analysis_id}/groups/apply")
def apply_group(analysis_id: str, request: GroupApproval) -> dict[str, Any]:
    state = get_state(analysis_id)
    with state["lock"]:
        proposal = require_proposal(state, "groups", request.proposal_id, request.revision)
        group = next((group for group in proposal["groups"] if group["id"] == request.group_id), None)
        if group is None or not request.canonical.strip():
            raise HTTPException(status_code=400, detail="El grupo o el valor canónico no es válido.")
        if not set(request.variants).issubset({variant["value"] for variant in group["variants"]}):
            raise HTTPException(status_code=400, detail="Solo puedes aprobar variantes incluidas en este grupo.")
        column = proposal["column"]
        corrected = state["frame"].copy(deep=True)
        mask = corrected[column].isin(request.variants) & corrected[column].ne(request.canonical)
        changed = int(mask.sum())
        corrected.loc[mask, column] = request.canonical
        equivalence = {"column": column, "variants": list(dict.fromkeys(request.variants)),
            "canonical": request.canonical, "changed_values": changed, "revision": state["revision"] + 1}
        return commit(analysis_id, state, corrected, changed=changed, equivalence=equivalence)

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
    state = get_state(analysis_id)
    with state["lock"]:
        frame = state["frame"]
        if request.column is not None:
            require_text_column(frame, request.column)
        records = json_records(frame, len(frame))
        row_ids = [int(index) + 1 for index in frame.index]
        normalized = [normalize_for_match(row[request.column]) if request.column is not None and row[request.column] is not None else "" for row in records]
        first_exact: dict[str, int] = {}
        first_value: dict[str, int] = {}
        best_cache: dict[str, tuple[int, float] | None] = {}
        pairs = []
        for right, record in enumerate(records):
            signature = json.dumps(record, ensure_ascii=False, sort_keys=True)
            exact = signature in first_exact
            left = first_exact.setdefault(signature, right)
            score = 100.0
            value = normalized[right]
            if value and value not in best_cache:
                best = None
                for reference, position in first_value.items():
                    candidate_score = similarity(reference, value)
                    if candidate_score >= request.threshold and (best is None or candidate_score > best[1]):
                        best = (position, candidate_score)
                best_cache[value] = best
            if value in first_value:
                best = (first_value[value], 100.0)
            else:
                best = best_cache.get(value)
                if value:
                    first_value[value] = right
            if not exact:
                if best is None:
                    continue
                left, score = best
            differences = [column for column in frame.columns if records[left][column] != record[column]]
            pairs.append({"id": f"{row_ids[left]}:{row_ids[right]}", "left_row": row_ids[left], "right_row": row_ids[right],
                "left": records[left], "right": record, "differences": differences,
                "kind": "exact" if exact else "similar", "similarity": round(score, 1)})
        review_id = str(uuid.uuid4())
        state["duplicates"] = {"id": review_id, "revision": state["revision"], "pairs": {pair["id"]: pair for pair in pairs}, "decisions": {}}
        return {"review_id": review_id, "revision": state["revision"], "pairs": pairs, "decisions": {}}

@app.post("/api/analyses/{analysis_id}/duplicates/decision")
def confirm_duplicate_decision(analysis_id: str, request: DuplicateDecisionRequest) -> dict[str, Any]:
    state = get_state(analysis_id)
    with state["lock"]:
        review = require_proposal(state, "duplicates", request.review_id, request.revision)
        if request.pair_id not in review["pairs"]:
            raise HTTPException(status_code=400, detail="El par seleccionado no pertenece a esta revisión.")
        decisions = dict(review["decisions"])
        if request.action == "pending":
            decisions.pop(request.pair_id, None)
        else:
            decisions[request.pair_id] = request.action
        removed = duplicate_removals(review["pairs"], decisions)
        review["decisions"] = decisions
        return {"revision": state["revision"], "decisions": decisions, "removed_rows": sorted(removed)}

@app.post("/api/analyses/{analysis_id}/duplicates/apply")
def apply_duplicate_decisions(analysis_id: str, request: DuplicateApplyRequest) -> dict[str, Any]:
    state = get_state(analysis_id)
    with state["lock"]:
        review = require_proposal(state, "duplicates", request.review_id, request.revision)
        removed = duplicate_removals(review["pairs"], review["decisions"])
        corrected = state["frame"].drop(index=[row - 1 for row in removed]).copy(deep=True)
        result = commit(analysis_id, state, corrected, deleted=len(removed))
        state.pop("duplicates", None)
        return result

@app.get("/api/analyses/{analysis_id}/export")
def export_corrected(analysis_id: str) -> Response:
    state = get_state(analysis_id)
    with state["lock"]:
        content = state["frame"].to_csv(index=False).encode("utf-8-sig")
        filename = state["filename"].rsplit(".", 1)[0] + "_corregido.csv"
        return Response(content=content, media_type="text/csv; charset=utf-8", headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename, safe='')}",
            "X-Dataset-Revision": str(state["revision"]),
            "Access-Control-Expose-Headers": "Content-Disposition, X-Dataset-Revision"})
