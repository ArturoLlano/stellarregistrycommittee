export async function fetchEntryById(id) {
  const url = `/data/entries/${encodeURIComponent(id)}.json`;
  const r = await fetch(url, { cache: "no-store" });
  if (!r.ok) {
    const err = new Error(`Entry not found (${r.status})`);
    err.status = r.status;
    throw err;
  }
  return await r.json();
}
