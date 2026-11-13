/* Shared by the registry iframe links and the standalone sky viewer. */
(function (root) {
  'use strict';
  function sexagesimal(value, isRA) {
    if (typeof value !== 'string') return null;
    var parts = value.trim().replace(/:/g, ' ').split(/\s+/);
    if (parts.length !== 3 || !parts.every(function (p) { return /^[+-]?\d+(?:\.\d+)?$/.test(p); })) return null;
    var a = Number(parts[0]), m = Number(parts[1]), s = Number(parts[2]);
    if (!Number.isInteger(a) || m < 0 || m >= 60 || s < 0 || s >= 60) return null;
    if (isRA && (parts[0][0] === '-' || a < 0 || a >= 24)) return null;
    if (!isRA && (Math.abs(a) > 90 || (Math.abs(a) === 90 && (m || s)))) return null;
    return (Math.abs(a) + m / 60 + s / 3600) * (isRA ? 15 : (parts[0][0] === '-' ? -1 : 1));
  }
  function pair(coords) {
    if (!coords || typeof coords !== 'object') return null;
    var ra = sexagesimal(coords.ra_hms || coords.ra, true), dec = sexagesimal(coords.dec_dms || coords.dec, false);
    if (ra !== null && dec !== null) return { raDeg: ra, decDeg: dec };
    if (typeof coords.ra_deg === 'number' && typeof coords.dec_deg === 'number' &&
        Number.isFinite(coords.ra_deg) && Number.isFinite(coords.dec_deg) &&
        coords.ra_deg >= 0 && coords.ra_deg < 360 && Math.abs(coords.dec_deg) <= 90) {
      return { raDeg: coords.ra_deg, decDeg: coords.dec_deg };
    }
    return null;
  }
  function forEntry(entry) {
    entry = entry || {};
    var obj = entry.object || {};
    return pair(obj.coordinatesV) || pair(entry.coordinatesV) ||
           pair(obj.coordinates) || pair(entry.coordinates) || pair(entry);
  }
  root.TSRCMapCoordinates = { forEntry: forEntry };
})(typeof window !== 'undefined' ? window : globalThis);
