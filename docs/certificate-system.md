\# TSRC PDF Certificate System (Phase 1)



This document describes the local, JSON-only PDF certificate generator for The Stellar Registry Committee (TSRC).



\## Goals



\- Generate a Letter-size (612 x 792 pt) PDF certificate for each entry.

\- Certificates are fully regenerable from the entry JSON only (no web lookups).

\- QR codes are stable and QR-safe:

&nbsp; - QR encodes the absolute URL: `https://stellarregistrycommittee.pages.dev/r/<ID>`

\- Generated artifacts remain inside `/public`.



\## Key paths (Phase 1)



\- Entry JSON:

&nbsp; - `/public/data/entries/<ID>.json`



\- PDF output (generated):

&nbsp; - `/public/certificates/<ID>/certificate.pdf`



\- Template bundles (source-controlled, immutable):

&nbsp; - `/tools/tsrc/certificates/templates/<template\_id>/`



\## Template bundles are immutable



A template bundle is a folder like:



`tools/tsrc/certificates/templates/tsrc-letter-v1/`



It contains:

\- `manifest.json` (declares template\_id and assets)

\- `layout.json` (positions of all fields, QR, and disclaimer box)

\- `disclaimer.txt` (always printed)

\- `background.jpg` (binary image you supply)



\*\*Rule:\*\* if you change the look, create a new folder:

\- `tsrc-letter-v2`, `tsrc-letter-v3`, etc.



Existing certificates can be regenerated exactly as long as:

\- the entry JSON keeps `certificate.template\_id`

\- the corresponding template folder remains unchanged



\## Background image (required)



Expected file path:



`tools/tsrc/certificates/templates/tsrc-letter-v1/background.jpg`



Notes:

\- Must be a JPEG (recommended).

\- Aspect ratio should match Letter (8.5 x 11).

\- The renderer draws it full-page (stretched to fill Letter).



If the file is missing, the PDF still generates, but without the background.



\## How to generate a certificate (step-by-step)



1\) Confirm you have an entry JSON:

&nbsp;  - `/public/data/entries/SAO-12345-AB12.json`



2\) Confirm `certificate.qr\_url` is correct inside the JSON:

&nbsp;  - `https://stellarregistrycommittee.pages.dev/r/SAO-12345-AB12`



3\) From repo root, run:



&nbsp;  ```bash

&nbsp;  python -m tools.tsrc.cli validate SAO-12345-AB12



