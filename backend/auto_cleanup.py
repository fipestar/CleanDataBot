"""Pure automatic-cleanup planner. No session mutation or implicit fuzzy replacement."""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from functools import lru_cache
from itertools import combinations
from typing import Any, Callable, Literal

import pandas as pd
from fastapi import HTTPException
from pydantic import BaseModel, Field, model_validator
from date_normalization import date_columns, normalize_date


class Replacement(BaseModel):
    variant: str
    canonical: str = Field(min_length=1)


class ColumnRule(BaseModel):
    column: str
    trim: bool = True
    collapse_spaces: bool = True
    replacements: list[Replacement] = Field(default_factory=list)

    @property
    def letter_case(self):
        # Compatible with the existing clean_text transformer; no hidden case rule.
        return "unchanged"


class FieldMapping(BaseModel):
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    identifiers: list[str] = Field(default_factory=list)


class AutoCleanupRequest(BaseModel):
    revision: int = Field(ge=0)
    all_columns: bool = True
    normalize_dates: bool = True
    date_order: Literal["auto", "dmy", "mdy"] = "auto"
    column_rules: list[ColumnRule] = Field(default_factory=list)
    fields: FieldMapping = Field(default_factory=FieldMapping)
    merge_clients: bool = True
    name_threshold: float = Field(default=97, ge=90, le=100)
    review_threshold: float = Field(default=85, ge=60, le=100)
    ignored_columns: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_thresholds(self):
        if self.review_threshold > self.name_threshold:
            raise ValueError("El umbral de revisión no puede superar al automático.")
        return self


class AutoApproval(BaseModel):
    revision: int = Field(ge=0)
    plan_id: str


class ExceptionDecision(BaseModel):
    revision: int = Field(ge=0)
    run_id: str
    group_id: str
    action: Literal["keep_all", "remove_selected"]
    keep_row: int | None = Field(default=None, ge=1)
    remove_rows: list[int] = Field(default_factory=list)


def empty(value):
    return bool(pd.isna(value)) or (isinstance(value, str) and not value.strip())


def safe(value):
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        value = value.item()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def record_hash(row):
    serialized = json.dumps({column: safe(value) for column, value in row.items()}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(serialized.encode()).hexdigest()


def group_signature(records):
    value = [(row["row"], record_hash(row["values"])) for row in records]
    return hashlib.sha256(json.dumps(value).encode()).hexdigest()


def infer_mapping(columns, normalize):
    aliases = {
        "name": {"nombre", "nombre completo", "full name", "name", "cliente", "customer name"},
        "email": {"correo", "email", "e mail", "correo electronico", "email address"},
        "phone": {"telefono", "phone", "phone number", "celular", "movil", "tel"},
        "identifiers": {"id", "cedula", "documento", "document", "identificacion", "customer id", "client id", "cliente id", "nit"},
    }
    headings = {column: normalize(column.replace("_", " ").replace("-", " ")) for column in columns}
    result, warnings = {}, []
    for role, names in aliases.items():
        candidates = [column for column, heading in headings.items() if heading in names]
        if role == "identifiers":
            result[role] = candidates
        else:
            result[role] = candidates[0] if len(candidates) == 1 else None
            if len(candidates) > 1:
                warnings.append(f"Asociación ambigua para {role}: {', '.join(candidates)}. Selecciona una columna.")
    return result, warnings


def validate_config(frame, request, transform):
    fields = request.fields
    roles = [value for value in [fields.name, fields.email, fields.phone, *fields.identifiers] if value is not None]
    if len(roles) != len(set(roles)):
        raise HTTPException(400, "Una columna no puede representar varios campos de cliente.")
    configured = [rule.column for rule in request.column_rules]
    if len(configured) != len(set(configured)):
        raise HTTPException(400, "Configura cada columna una sola vez.")
    if not set(roles + configured + request.ignored_columns).issubset(frame.columns):
        raise HTTPException(400, "La configuración contiene columnas que no existen en el archivo.")
    if set(roles) & set(request.ignored_columns):
        raise HTTPException(400, "No puedes ignorar un campo asociado a nombre, contacto o identificador.")
    replacements = {}
    for rule in request.column_rules:
        if not (pd.api.types.is_object_dtype(frame[rule.column]) or pd.api.types.is_string_dtype(frame[rule.column])):
            raise HTTPException(400, f"La columna {rule.column} no es de texto; no se puede normalizar.")
        mapping = {}
        for replacement in rule.replacements:
            source, target = transform(replacement.variant, rule), transform(replacement.canonical, rule)
            if not source.strip() or not target.strip():
                raise HTTPException(400, "Las variantes y valores canónicos deben contener texto.")
            if source in mapping and mapping[source] != target:
                raise HTTPException(400, f"Hay valores canónicos contradictorios en {rule.column}: {source}.")
            mapping[source] = target
        resolved = {}
        for source in mapping:
            visited, target = set(), source
            while target in mapping and mapping[target] != target:
                if target in visited:
                    raise HTTPException(400, f"Hay un ciclo de reemplazos en {rule.column}.")
                visited.add(target)
                target = mapping[target]
            resolved[source] = target
        replacements[rule.column] = resolved
    return replacements


class Components:
    def __init__(self, indices):
        self.parent = {index: index for index in indices}

    def find(self, index):
        while self.parent[index] != index:
            self.parent[index] = self.parent[self.parent[index]]
            index = self.parent[index]
        return index

    def join(self, left, right):
        self.parent[self.find(right)] = self.find(left)

    def groups(self):
        groups = defaultdict(list)
        for index in self.parent:
            groups[self.find(index)].append(index)
        return [members for members in groups.values() if len(members) > 1]


def plan_cleanup(frame: pd.DataFrame, request: AutoCleanupRequest, *, transform: Callable,
                 normalize: Callable, similarity: Callable, separations=None, review_only=False):
    if request.all_columns:
        configured = {rule.column: rule for rule in request.column_rules}
        # Validate user column references before expanding the global rules.
        validate_config(frame, request, transform)
        rules = [configured.get(column, ColumnRule(column=column)).model_copy(update={"trim": True, "collapse_spaces": True})
                 for column in frame.columns if pd.api.types.is_object_dtype(frame[column]) or pd.api.types.is_string_dtype(frame[column])]
        request = request.model_copy(update={"column_rules": rules})
    replacements = validate_config(frame, request, transform)
    work = frame.copy(deep=True)
    events, warnings = [], []
    counts = {"normalized_cells": 0, "standardized_cells": 0, "exact_duplicates_removed": 0,
              "clients_merged": 0, "filled_cells": 0, "duplicates_removed": 0, "pending_groups": 0,
              "previously_separated_groups": 0}
    counts.update({"dates_normalized": 0, "dates_skipped": 0})
    date_issues = []

    def event(rule, **details):
        events.append({"rule": rule, **details})

    def deduplicate(rule):
        nonlocal work
        first, remove = {}, []
        for index, values in work.iterrows():
            key = tuple(None if pd.isna(value) else value for value in values)
            if key in first:
                remove.append(index)
                event(rule, row=int(index) + 1, kept_row=int(first[key]) + 1)
            else:
                first[key] = index
        work = work.drop(index=remove)
        counts["exact_duplicates_removed"] += len(remove)

    # Both passes are intentional: standardization can create new exact duplicates.
    if not review_only:
        deduplicate("exact_duplicate_before")
    for rule in ([] if review_only else request.column_rules):
        for index, value in work[rule.column].items():
            if not isinstance(value, str):
                continue
            normalized = transform(value, rule)
            if normalized != value:
                work.at[index, rule.column] = normalized
                counts["normalized_cells"] += 1
                event("normalize_text", row=int(index) + 1, column=rule.column, before=value, after=normalized,
                      options={"trim": rule.trim, "collapse_spaces": rule.collapse_spaces})
            target = replacements[rule.column].get(normalized, normalized)
            if target != normalized:
                work.at[index, rule.column] = target
                counts["standardized_cells"] += 1
                event("canonical_variant", row=int(index) + 1, column=rule.column, before=normalized, after=target)
    if request.normalize_dates and not review_only:
        excluded = [request.fields.name, request.fields.email, request.fields.phone, *request.fields.identifiers, *request.ignored_columns]
        for column in date_columns(work, normalize, excluded=excluded):
            if pd.api.types.is_datetime64_any_dtype(work[column]):
                work[column] = work[column].astype(object)
            for index, value in work[column].items():
                normalized, reason = normalize_date(value, request.date_order)
                if reason:
                    counts["dates_skipped"] += 1
                    date_issues.append({"row": int(index) + 1, "column": column, "value": safe(value), "reason": reason})
                elif not empty(value) and (not isinstance(value, str) or normalized != value):
                    work.at[index, column] = normalized
                    counts["dates_normalized"] += 1
                    event("normalize_date", row=int(index) + 1, column=column, before=safe(value), after=normalized,
                          options={"date_order": request.date_order, "output": "ISO 8601"})
    if date_issues:
        warnings.append(f"Se conservaron {len(date_issues)} fechas ambiguas, inválidas o no reconocidas. Revisa el orden día/mes si corresponde.")
    if not review_only:
        deduplicate("exact_duplicate_after_standardization")

    fields = request.fields
    contacts = [column for column in [fields.email, fields.phone] if column]
    usable = bool(fields.name and contacts and request.merge_clients)
    if not request.merge_clients:
        warnings.append("Fusión de clientes omitida: la regla está desactivada.")
    if not fields.name:
        warnings.append("Fusión de clientes omitida: falta asociar una columna de nombre.")
    if not contacts:
        warnings.append("Fusión de clientes omitida: falta asociar correo o teléfono; el nombre solo no es evidencia suficiente.")
    # Frozen fingerprints make explicit 'keep all' decisions reusable only while
    # those records remain unchanged. No new source row inherits that decision.
    protected = []
    current_rows = work.to_dict(orient="index")
    for separation in separations or []:
        unchanged = {item["row"] - 1 for item in separation["records"]
                     if item["row"] - 1 in current_rows and record_hash(current_rows[item["row"] - 1]) == item["hash"]}
        if len(unchanged) > 1:
            protected.append(unchanged)

    def contact_key(value):
        return None if empty(value) else str(value).strip()

    @lru_cache(maxsize=10000)
    def name_score(left, right):
        return similarity(left, right) if left and right else 0.0

    def build_rows():
        rows = work.to_dict(orient="index")
        names = {index: normalize(row[fields.name]) if fields.name and isinstance(row[fields.name], str) and not empty(row[fields.name]) else "" for index, row in rows.items()}
        contact_values = {index: {column: contact_key(row[column]) for column in contacts} for index, row in rows.items()}
        comparisons = {index: {column: None if empty(value) else value for column, value in row.items()
                              if column != fields.name and column not in request.ignored_columns} for index, row in rows.items()}
        return rows, names, contact_values, comparisons

    def evidence(left, right):
        return [column for column in contacts if contact_values[left][column] is not None
                and contact_values[left][column] == contact_values[right][column]]

    def conflicts(left, right):
        return [column for column in comparisons[left] if comparisons[left][column] is not None
                and comparisons[right][column] is not None and comparisons[left][column] != comparisons[right][column]]

    rows, names, contact_values, comparisons = build_rows()
    contact_components = Components(rows)
    for column in contacts:
        first = {}
        for index, row in rows.items():
            key = contact_key(row[column])
            if key is not None:
                if key in first:
                    contact_components.join(first[key], index)
                else:
                    first[key] = index
    remove = []
    if usable and not review_only:
        for members in contact_components.groups():
            # Every original pair must pass, not just the anchor or a connected
            # path. A conflict vetoes the entire contact component.
            members.sort()
            safe_group = all(
                evidence(left, right)
                and name_score(names[left], names[right]) >= request.name_threshold
                and not conflicts(left, right)
                and not any(left in group and right in group for group in protected)
                for left, right in combinations(members, 2)
            )
            if not safe_group:
                continue
            keeper = members[0]
            for donor in members[1:]:
                for column in work.columns:
                    if column in request.ignored_columns:
                        continue
                    if empty(work.at[keeper, column]) and not empty(rows[donor][column]):
                        value = rows[donor][column]
                        before = safe(work.at[keeper, column])
                        work.at[keeper, column] = value
                        counts["filled_cells"] += 1
                        event("fill_empty_field", row=int(keeper) + 1, source_row=int(donor) + 1, column=column, before=before, after=safe(value))
                remove.append(donor)
                event("client_exact_contact_and_name", row=int(donor) + 1, kept_row=int(keeper) + 1,
                      evidence=evidence(keeper, donor), name_similarity=round(name_score(names[keeper], names[donor]), 2),
                      threshold=request.name_threshold, ignored_columns=request.ignored_columns)
            counts["clients_merged"] += len(members) - 1
    work = work.drop(index=remove)
    if not review_only:
        deduplicate("exact_duplicate_after_merge")

    # Components below are presentation groups ONLY. They are never used to
    # authorize a merge; a connected component is not proof of a single entity.
    rows, names, contact_values, comparisons = build_rows()
    pending = Components(rows)
    details = defaultdict(lambda: {"reasons": set(), "columns": set(), "links": 0})
    for left, right in combinations(rows, 2):
        contact = evidence(left, right)
        score = name_score(names[left], names[right])
        if not contact and (not names[left] or not names[right] or score < request.review_threshold):
            continue
        pending.join(left, right)
        conflict = conflicts(left, right)
        reasons = []
        if not contact:
            reasons.append("Parecido de nombre sin correo o teléfono coincidente no vacío.")
        if contact and (not names[left] or not names[right] or score < request.name_threshold):
            reasons.append("Contacto compartido con nombre diferente, ausente o por debajo del umbral automático.")
        if conflict:
            reasons.append("Hay campos no vacíos contradictorios.")
        if not usable:
            reasons.append("La regla automática de clientes está desactivada o incompleta.")
        if not reasons:
            reasons.append("Coincidencia de nombre y contacto: requiere comprobar conjuntamente a todos los miembros, o hay una decisión previa de conservar ambos.")
        for index in [left, right]:
            details[index]["reasons"].update(reasons)
            details[index]["columns"].update(conflict)
            details[index]["links"] += 1
    pending_groups = []
    dismissed = {separation["signature"] for separation in separations or []}
    for members in pending.groups():
        records = [{"row": int(index) + 1, "values": {column: safe(value) for column, value in rows[index].items()}} for index in sorted(members)]
        signature = group_signature(records)
        if signature in dismissed:
            counts["previously_separated_groups"] += 1
            continue
        pending_groups.append({"id": signature, "records": records,
            "reasons": sorted(set().union(*(details[index]["reasons"] for index in members))),
            "conflicting_columns": sorted(set().union(*(details[index]["columns"] for index in members))),
            "related_pairs": sum(details[index]["links"] for index in members) // 2})
    counts["pending_groups"] = len(pending_groups)
    counts["duplicates_removed"] = counts["exact_duplicates_removed"] + counts["clients_merged"]
    return work, {"counts": counts, "warnings": warnings, "fields": fields.model_dump(),
                  "events": events, "pending_groups": pending_groups, "date_issues": date_issues}
