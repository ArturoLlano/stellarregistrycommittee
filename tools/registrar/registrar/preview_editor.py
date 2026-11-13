"""Editable preview fields shared by review and commit (no filesystem writes)."""
from copy import deepcopy
from datetime import date
import math
import re

from .schema import _build_legend_en
from .vizier import compute_constellation_best_effort

# name, label, payload path, input type, required
FIELDS = [
    ('inscription_name', 'Nombre de la inscripción', 'object.inscription.name', 'text', True),
    ('inscription_motto', 'Dedicatoria', 'object.inscription.motto', 'text', False),
    ('inscription_date', 'Fecha de inscripción', 'object.inscription.inscribed_on', 'date', True),
    ('recorded_by', 'Registrado por', 'provenance.recorded_by', 'text', False),
    ('sponsor', 'Patrocinador / firma del certificado', 'provenance.sponsor', 'text', False),
    ('ra_hms', 'Ascensión recta J2000 (hh mm ss)', 'object.coordinates.ra_hms', 'text', False),
    ('dec_dms', 'Declinación J2000 (+dd mm ss)', 'object.coordinates.dec_dms', 'text', False),
    ('visual_ra_hms', 'Mapa: ascensión recta J2000 (hh mm ss)', 'object.coordinatesV.ra_hms', 'text', False),
    ('visual_dec_dms', 'Mapa: declinación J2000 (+dd mm ss)', 'object.coordinatesV.dec_dms', 'text', False),
    ('v_mag', 'Magnitud visual', 'object.photometry.v_mag', 'number', False),
    ('p_mag', 'Magnitud fotográfica', 'object.photometry.p_mag', 'number', False),
    ('spectral_type', 'Tipo espectral', 'object.spectral.type', 'text', False),
    ('constellation_name', 'Constelación', 'object.constellation.name', 'text', False),
    ('constellation_abbr', 'Abreviatura IAU', 'object.constellation.iau_abbr', 'text', False),
]


def _get(payload, path):
    value = payload
    for key in path.split('.'):
        value = value.get(key, {}) if isinstance(value, dict) else {}
    return '' if value is None or isinstance(value, dict) else value


def editor_fields(payload, submitted=None):
    return [dict(name=name, label=label, value=(submitted.get(name, '') if submitted is not None else _get(payload, path)),
                 type=kind, required=required)
            for name, label, path, kind, required in FIELDS]


def _set(payload, path, value):
    keys = path.split('.')
    parent = payload
    for key in keys[:-1]:
        parent = parent.setdefault(key, {})
    if value == '' or value is None:
        parent.pop(keys[-1], None)
    else:
        parent[keys[-1]] = value


def _coordinate(value, ra):
    parts = value.replace(':', ' ').split()
    if len(parts) != 3 or not re.fullmatch(r'[+-]?\d+(?:\.\d+)?', parts[0]):
        raise ValueError('Usa tres componentes: hh mm ss o +dd mm ss.')
    a, m, s = map(float, parts)
    if not all(math.isfinite(x) for x in (a, m, s)) or not 0 <= m < 60 or not 0 <= s < 60:
        raise ValueError('Los minutos y segundos deben estar entre 0 y menos de 60.')
    if not a.is_integer() or (ra and (parts[0].startswith('-') or not 0 <= a < 24)):
        raise ValueError('La hora debe ser un entero entre 0 y 23.')
    if not ra and (abs(a) > 90 or (abs(a) == 90 and (m or s))):
        raise ValueError('La declinación debe estar entre -90 y +90 grados.')
    sign = -1 if parts[0].startswith('-') else 1
    degrees = (abs(a) + m / 60 + s / 3600) * (15 if ra else sign)
    return ' '.join(parts), round(degrees, 8)


def apply_edits(original, submitted):
    payload = deepcopy(original)
    if submitted.get('editor_version') != '1':
        return payload  # compatibility with previews opened before the update
    changes = {}
    for name, label, path, kind, required in FIELDS:
        old = _get(original, path)
        raw = submitted.get(name, str(old)).strip()
        if raw == str(old):
            continue
        if required and not raw:
            raise ValueError(f'{label}: este campo es obligatorio.')
        value = raw
        if kind == 'number' and raw:
            try:
                value = float(raw)
                if not math.isfinite(value):
                    raise ValueError()
            except ValueError:
                raise ValueError(f'{label}: introduce un número finito.') from None
            if value == old:
                continue
        if kind == 'date' and raw:
            try:
                date.fromisoformat(raw)
            except ValueError:
                raise ValueError(f'{label}: fecha inválida.') from None
        _set(payload, path, value)
        changes[path] = {'original': old, 'value': value}

    if not changes:
        return payload
    obj = payload['object']
    if any(path.startswith('object.coordinatesV.') for path in changes):
        coords = obj['coordinatesV']
        ra, dec = coords.get('ra_hms', ''), coords.get('dec_dms', '')
        if bool(ra) != bool(dec):
            raise ValueError('Mapa: completa ambas coordenadas de visualización o deja ambas vacías.')
        if ra:
            coords['ra_hms'], coords['ra_deg'] = _coordinate(ra, True)
            coords['dec_dms'], coords['dec_deg'] = _coordinate(dec, False)
            coords['epoch'] = 'J2000'
        else:
            obj.pop('coordinatesV', None)
        if all(path.startswith('object.coordinatesV.') for path in changes):
            return payload
    if any('object.coordinates.' in path for path in changes):
        coords = obj.setdefault('coordinates', {})
        ra, dec = coords.get('ra_hms', ''), coords.get('dec_dms', '')
        if bool(ra) != bool(dec):
            raise ValueError('Completa ambas coordenadas o deja ambas vacías.')
        if ra:
            coords['ra_hms'], coords['ra_deg'] = _coordinate(ra, True)
            coords['dec_dms'], coords['dec_deg'] = _coordinate(dec, False)
        else:
            coords.pop('ra_deg', None)
            coords.pop('dec_deg', None)
        if not any(path.startswith('object.constellation.') for path in changes):
            obj.pop('constellation', None)
            if ra:
                constellation, _ = compute_constellation_best_effort(coords['ra_deg'], coords['dec_deg'])
                if constellation:
                    obj['constellation'] = {**constellation, 'method': 'IAU Delporte boundaries (via astropy)'}

    if 'object.spectral.type' in changes:
        obj['spectral']['is_composite'] = obj['spectral'].get('type') == '+++'
    for block in ('photometry', 'spectral'):
        if any(path.startswith('object.' + block + '.') for path in changes):
            obj[block]['source'] = 'Manual correction (catalogue values preserved in provenance.manual_overrides)'
    if any(path.startswith('object.constellation.') for path in changes):
        obj['constellation']['method'] = 'Manual correction'

    # Keep a per-field record without labelling manual corrections as catalogue facts.
    catalogue_changes = {k: v for k, v in changes.items()
                         if k.startswith('object.') and not k.startswith(('object.inscription.', 'object.coordinatesV.'))}
    if catalogue_changes:
        overrides = payload.setdefault('provenance', {}).setdefault('manual_overrides', {})
        for path, change in catalogue_changes.items():
            if path in overrides:
                change['original'] = overrides[path]['original']
            overrides[path] = change
        note = 'Manual corrections applied before certificate generation; see provenance.manual_overrides.'
        if note not in payload.setdefault('notes', []):
            payload['notes'].append(note)
    certificate = payload.setdefault('certificate', {})
    sao = int(next(c['id'] for c in obj['catalog'] if c['scheme'] == 'SAO'))
    legend = _build_legend_en(sao=sao, obj=obj)
    if legend:
        certificate['legend_en'] = legend
    else:
        certificate.pop('legend_en', None)
    return payload
