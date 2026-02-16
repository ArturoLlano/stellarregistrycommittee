import { normalizeRecordId, isValidRecordId } from "../lib/ids.js";

const form = document.querySelector("[data-record-lookup]");
if (form) {
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const input = form.querySelector("input[name='record_id']");
    const msg = form.querySelector("[data-msg]");
    msg.textContent = "";

    const id = normalizeRecordId(input.value);
    input.value = id;

    if (!isValidRecordId(id)) {
      msg.textContent = "Please enter a valid Record ID (A–Z, 0–9, hyphen).";
      msg.className = "error";
      return;
    }

    // Siempre resolver por /r/<ID> (arquitectura QR)
    location.href = `/r/${encodeURIComponent(id)}`;
  });
}
