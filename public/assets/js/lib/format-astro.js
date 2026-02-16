function splitParts(s) {
  return String(s || "").trim().replace(/\s+/g, " ").split(" ");
}

export function formatRaHms(ra_hms) {
  const p = splitParts(ra_hms);
  if (p.length < 3) return String(ra_hms || "");
  return `${p[0]}h ${p[1]}m ${p[2]}s`;
}

export function formatDecDms(dec_dms) {
  const p = splitParts(dec_dms);
  if (p.length < 3) return String(dec_dms || "");
  // p[0] ya trae signo en tu JSON (+12)
  return `${p[0]}° ${p[1]}′ ${p[2]}″`;
}
