\# Stellar Registry Committee — Local Registry Entry Registrar (Phase 1)



This tool runs locally and creates a new registry entry JSON in:



public/data/entries/<ID>.json



Then it attempts to:

\- git add the new JSON

\- git commit it

\- git push it to your GitHub remote (so Cloudflare Pages publishes it)



No secrets are stored. It relies on your existing local Git credentials.



---



\## Requirements

\- Windows 10/11

\- Python 3.10+

\- Git installed (and repo already cloned with a working remote)



---



\## Run (one command)

From \*\*anywhere\*\* (repo root or inside it):



tools\\registrar\\run.bat



Then open:

http://127.0.0.1:5055



(Port can be changed with REGISTRAR\_PORT env var.)



---



\## Form fields

\- SAO number (required, numeric)

\- Inscription name (required)

\- Inscription motto (optional)

\- Recorded by (optional; can be "Anonymous")

\- Sponsor (optional)



---



\## Duplicate checking (how it works)

On Preview/Commit, the tool scans:

public/data/entries/\*.json



A duplicate is detected if EITHER:

1\) Any filename starts with: "SAO-<SAO>-"

&nbsp;  e.g. SAO-12345-XXXX.json

OR

2\) Any JSON file contains:

&nbsp;  object.catalog\[] entry with scheme "SAO" and id == <SAO>



If duplicates exist, the tool shows a clear message listing the existing entries,

and it will NOT create/upload a new entry.



---



\## Coordinates lookup (best-effort)

The tool can attempt to fetch RA/Dec from CDS VizieR (I/131A) via HTTP.

If lookup fails (offline, blocked, etc.), it will still create the entry but leave

coordinates blank.



---



\## Git behavior

The tool stages \*\*only\*\* the newly created JSON file, commits it, then pushes.



Common failure cases:

\- Git not installed → tool keeps the generated JSON and shows the error.

\- No remote configured → tool keeps JSON and explains what to fix.

\- Push rejected (remote ahead) → tool keeps JSON and suggests:

&nbsp; git pull --rebase

&nbsp; git push



The tool never deletes your generated JSON.



