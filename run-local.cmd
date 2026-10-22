@echo off
rem Runs the site on this computer at http://localhost:8000 (double-click, or type run-local in a terminal here).
rem Passwords: admin / family. Photos you upload stay in the local-data folder and never go to GitHub.
cd /d "%~dp0"

if not exist .venv (
  echo Setting up Python for the first time...
  python -m venv .venv || (
    echo.
    echo Python isn't installed. Get it from https://www.python.org/downloads/ and tick "Add python.exe to PATH".
    pause
    exit /b 1
  )
)
.venv\Scripts\python -m pip install -q --disable-pip-version-check -r requirements.txt

set LOCAL_DEV=1
rem Personal settings go in local.env, one per line. BIRTH_DATE=YYYY-MM-DD turns on the
rem age in the Home masthead and the "age 2" captions; see .env.example for the rest.
if exist local.env for /f "usebackq eol=# tokens=1,* delims==" %%a in ("local.env") do set "%%a=%%b"

echo.
if not defined BIRTH_DATE echo   No BIRTH_DATE set - put BIRTH_DATE=YYYY-MM-DD in local.env for age labels.
echo   Open http://localhost:8000   (admin password: admin, family password: family)
echo   Stop with Ctrl+C
echo.
.venv\Scripts\python -m uvicorn app.main:app --reload --reload-dir app --port 8000
