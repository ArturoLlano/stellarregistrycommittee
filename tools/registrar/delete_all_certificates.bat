@echo off
setlocal

REM Go to repo root (this .bat lives in tools\registrar)
cd /d "%~dp0..\.."

echo Running: delete_all_certificates.py
echo Repo: %cd%
echo.

python tools\registrar\delete_all_certificates.py
echo.
pause