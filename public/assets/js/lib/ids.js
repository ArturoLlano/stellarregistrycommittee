export function normalizeRecordId(input) {
  const raw = String(input || "").trim();
  if (!raw) return "";
  return raw
    .toUpperCase()
    .replace(/\s+/g, "-")
    .replace(/[^A-Z0-9-]/g, "");
}

export function isValidRecordId(id) {
  // Ajustable. Por ahora: letras/números/guión, 3..40 chars
  return /^[A-Z0-9-]{3,40}$/.test(id);
}
