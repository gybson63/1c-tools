@echo off
setlocal
cd /d "%~dp0"
set PYTHONPATH=%~dp0src

rem pythonw — без чёрного окна cmd; если нет — обычный python.
where pythonw >nul 2>&1
if %ERRORLEVEL%==0 (
  start "" /D "%~dp0" pythonw -m cfe_tools.gui_app %*
  exit /b 0
)

python -m cfe_tools.gui_app %*
