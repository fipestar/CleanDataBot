"""Strict date normalization: no locale guessing, no numeric Excel serial inference."""
import re
from datetime import date, datetime

import pandas as pd

DATE_PART = r'(\d{1,4})([-/.])(\d{1,2})\2(\d{1,4})'
TIME_PART = r'(?:[T ](\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:\d{2})?))?'
DATE_PATTERN = re.compile('^' + DATE_PART + TIME_PART + '$')


def looks_like_date(value):
    if not isinstance(value, str):
        return False
    match = DATE_PATTERN.fullmatch(value.strip())
    if not match:
        return False
    first, _, _, last, _ = match.groups()
    return (len(first) == 4 and len(last) <= 2) or (len(last) == 4 and len(first) <= 2)


def date_columns(frame, normalize, excluded=()):
    result = []
    for column in frame.columns:
        heading = normalize(column.replace('_', ' ').replace('-', ' '))
        words = set(heading.split())
        protected = words & {'id', 'codigo', 'code', 'document', 'documento', 'cedula', 'telefono', 'phone', 'email', 'correo', 'nit', 'reference', 'ref', 'identificacion', 'identifier', 'identificador', 'pasaporte', 'passport', 'cuenta', 'account'}
        if protected or column in excluded:
            continue
        values = frame[column].dropna()
        populated = [value for value in values if not isinstance(value, str) or value.strip()]
        typed = pd.api.types.is_datetime64_any_dtype(frame[column]) or (populated and all(isinstance(value, (date, datetime)) for value in populated))
        named = bool(words & {'fecha', 'fechas', 'date', 'dates', 'datetime', 'timestamp', 'nacimiento', 'birth', 'dob'}) or heading in {'created at', 'updated at', 'registered at'}
        shaped = bool(populated) and all(looks_like_date(value) for value in populated)
        if typed or named or shaped:
            result.append(column)
    return result


def normalize_date(value, order='auto'):
    if pd.isna(value) or (isinstance(value, str) and not value.strip()):
        return value, None
    if isinstance(value, (datetime, date)):
        return value.isoformat(), None
    if not isinstance(value, str):
        return value, 'Valor no textual; no se interpretan números como fechas.'
    text = value.strip()
    match = DATE_PATTERN.fullmatch(text)
    if not match:
        return value, 'Formato no reconocido; se conserva sin interpretar.'
    first, _, middle, last, clock = match.groups()
    if len(first) == 4 and len(last) <= 2:
        year, month, day = int(first), int(middle), int(last)
    elif len(last) == 4 and len(first) <= 2:
        a, b, year = int(first), int(middle), int(last)
        if order == 'dmy':
            day, month = a, b
        elif order == 'mdy':
            month, day = a, b
        elif a == b or a > 12 >= b:
            day, month = a, b
        elif b > 12 >= a:
            month, day = a, b
        elif 1 <= a <= 12 and 1 <= b <= 12:
            return value, 'Fecha ambigua: selecciona día/mes o mes/día para interpretarla.'
        else:
            return value, 'Fecha inválida; se conserva sin interpretar.'
    else:
        return value, 'Se requiere un año de cuatro dígitos.'
    try:
        day_value = date(year, month, day).isoformat()
        if clock:
            # No timezone conversion and no dropping of time or fractional seconds.
            return datetime.fromisoformat(f"{day_value}T{clock.replace('Z', '+00:00')}").isoformat(), None
        return day_value, None
    except ValueError:
        return value, 'Fecha u hora inválida; se conserva sin interpretar.'
