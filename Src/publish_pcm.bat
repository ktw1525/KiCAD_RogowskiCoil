@echo off
setlocal EnableExtensions DisableDelayedExpansion
rem Build the ZIP, then its online PCM index using KiCad's bundled Python.
set "RESULT=1"
call "%~dp0publish.bat" /nopause
if errorlevel 1 goto finish
set "PCM_PYTHON=%ProgramFiles%\KiCad\10.0\bin\python.exe"
if exist "%PCM_PYTHON%" goto generate
where python.exe >nul 2>nul
if errorlevel 1 (
    echo [ERROR] KiCad 10 Python or Python 3.9+ is required to generate the PCM index.
    goto finish
)
set "PCM_PYTHON=python.exe"
:generate
"%PCM_PYTHON%" "%~dp0prepare_pcm_repository.py"
if errorlevel 1 goto finish
set "RESULT=0"
:finish
if /I not "%~1"=="/nopause" pause
endlocal & exit /b %RESULT%
