@echo off
setlocal ENABLEDELAYEDEXPANSION

REM Run from repo root or anywhere inside it.
REM Creates a local venv under tools\registrar\.venv (gitignored).

set TOOL_DIR=%~dp0
pushd "%TOOL_DIR%"

if not exist ".venv" (
  python -m venv .venv
)

call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip >nul
pip install -r requirements.txt

REM Optional: set a fixed port (default is 5055)
REM set REGISTRAR_PORT=5055

set TSRC_PUBLIC_BASE_URL=https://stellarregistrycommittee.pages.dev

python app.py

popd
endlocal
