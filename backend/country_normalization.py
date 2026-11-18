"""Country aliases and ISO 3166-1 normalization, entirely offline at runtime."""
import gettext
import re
import unicodedata
from collections import defaultdict
from functools import lru_cache

import pandas as pd
import pycountry

# Only explicit, well-known aliases. No fuzzy or subdivision search is used.
ALIASES = {
    'UK': 'GB', 'EEUU': 'US', 'EE UU': 'US', 'EE. UU.': 'US',
    'Estados Unidos de América': 'US', 'South Korea': 'KR', 'Corea del Sur': 'KR',
    'North Korea': 'KP', 'Corea del Norte': 'KP', 'UAE': 'AE',
    'Rusia': 'RU', 'Russia': 'RU', 'Vietnam': 'VN', 'Viet Nam': 'VN',
    'Republic of the Congo': 'CG', 'República del Congo': 'CG',
    'República Democrática del Congo': 'CD', 'Democratic Republic of the Congo': 'CD',
}
AMBIGUOUS = {'congo', 'korea', 'corea', 'virgin islands', 'islas virgenes'}
# Disambiguate canonical output so that it is valid input on subsequent runs too.
DISPLAY_NAMES = {
    'es': {'CG': 'República del Congo', 'CD': 'República Democrática del Congo',
           'KR': 'Corea del Sur', 'KP': 'Corea del Norte'},
    'en': {'CG': 'Republic of the Congo', 'CD': 'Democratic Republic of the Congo',
           'KR': 'South Korea', 'KP': 'North Korea'},
}
COUNTRY_HEADERS = {
    'country', 'countries', 'country name', 'country code', 'country of residence',
    'residence country', 'billing country', 'shipping country', 'birth country',
    'pais', 'paises', 'nombre pais', 'nombre del pais', 'codigo pais', 'codigo de pais',
    'pais residencia', 'pais de residencia', 'pais nacimiento', 'pais de nacimiento',
}


def country_key(value):
    text = ''.join(char for char in unicodedata.normalize('NFKD', value.casefold())
                   if not unicodedata.combining(char)).replace('.', '')
    text = ' '.join(re.sub(r'[^a-z0-9\s]', ' ', text).split())
    if re.fullmatch(r'[a-z](?: [a-z]){1,2}', text):
        return text.replace(' ', '')
    return text


def country_columns(columns):
    return [column for column in columns if country_key(column) in COUNTRY_HEADERS]


@lru_cache(maxsize=1)
def catalog():
    translate = gettext.translation('iso3166-1', pycountry.LOCALES_DIR, languages=['es']).gettext
    index = defaultdict(set)
    output = {}
    for country in pycountry.countries:
        code = country.alpha_2
        common = getattr(country, 'common_name', country.name)
        output[code] = {
            'es': DISPLAY_NAMES['es'].get(code, translate(common)),
            'en': DISPLAY_NAMES['en'].get(code, common),
            'iso2': code, 'iso3': country.alpha_3,
        }
        labels = [country.alpha_2, country.alpha_3, country.numeric]
        for attribute in ['name', 'official_name', 'common_name']:
            value = getattr(country, attribute, None)
            if value:
                labels.extend([value, translate(value)])
        labels.extend(output[code].values())
        for label in labels:
            index[country_key(label)].add(code)
    for alias, code in ALIASES.items():
        index[country_key(alias)].add(code)
    return index, output


def normalize_country(value, output_format='es'):
    """Return canonical value, reason if preserved, and recognized ISO alpha-2."""
    if pd.isna(value) or (isinstance(value, str) and not value.strip()):
        return value, None, None
    if not isinstance(value, str):
        return value, 'Se conserva: el país debe ser un nombre o código textual.', None
    index, output = catalog()
    key = country_key(value)
    candidates = index.get(key, set())
    if key in AMBIGUOUS or len(candidates) > 1:
        return value, 'Nombre de país ambiguo; se conserva sin elegir un país arbitrariamente.', None
    if not candidates:
        return value, 'País no reconocido en el catálogo o los alias; se conserva sin corrección difusa.', None
    code = next(iter(candidates))
    return output[code][output_format], None, code
