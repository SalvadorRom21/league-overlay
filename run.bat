@echo off
setlocal
cd /d "%~dp0"
set PYTHONUNBUFFERED=1
where py >nul 2>&1
if %errorlevel%==0 (
  py -3 -m league_overlay %*
  exit /b %errorlevel%
)
python -m league_overlay %*
exit /b %errorlevel%
