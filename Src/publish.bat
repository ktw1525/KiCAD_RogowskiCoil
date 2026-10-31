@echo off
setlocal EnableExtensions DisableDelayedExpansion
rem Standalone Windows batch: no PowerShell, Python or KiCad required.
set "RESULT=1"
set "OUTPUT=%~dp0..\Publish"
set "NAME=Rogowski_TI_Gerber_PCM_KiCad10.zip"
set "WORK=%TEMP%\RogowskiPublish-%RANDOM%-%RANDOM%"
set "TAR=%SystemRoot%\System32\tar.exe"
if not exist "%TAR%" (
    echo [ERROR] Windows tar.exe is required.
    goto finish
)
for %%F in (metadata.json README_KO.txt plugins\__init__.py plugins\rogowski_action.py plugins\geometry.py plugins\preview.py plugins\coil_model.json plugins\toolbar.png resources\icon.png) do (
    if not exist "%~dp0%%F" (
        echo [ERROR] Missing source file: %%F
        goto finish
    )
)
if exist "%WORK%" (
    echo [ERROR] Temporary directory already exists. Run again.
    goto finish
)
mkdir "%WORK%"
if errorlevel 1 goto finish
echo [1/3] Creating plugin ZIP...
"%TAR%" --format zip -cf "%WORK%\%NAME%" -C "%~dp0." metadata.json README_KO.txt plugins/__init__.py plugins/rogowski_action.py plugins/geometry.py plugins/preview.py plugins/coil_model.json plugins/toolbar.png resources/icon.png
if errorlevel 1 (
    echo [ERROR] ZIP creation failed.
    goto finish
)
echo [2/3] Checking plugin ZIP...
"%TAR%" -tf "%WORK%\%NAME%"
if errorlevel 1 (
    echo [ERROR] ZIP verification failed.
    goto finish
)
echo [3/3] Saving to Publish...
if not exist "%OUTPUT%\." mkdir "%OUTPUT%"
copy /b /y "%WORK%\%NAME%" "%OUTPUT%\%NAME%" >nul
if errorlevel 1 goto blocked
fc /b "%WORK%\%NAME%" "%OUTPUT%\%NAME%" >nul
if errorlevel 1 (
    echo [ERROR] Saved ZIP differs from build. Verified original:
    echo "%WORK%\%NAME%"
    goto finish
)
echo [OK] "%OUTPUT%\%NAME%"
set "RESULT=0"
goto finish
:blocked
echo.
echo [WARNING] ZIP CREATED, but Windows blocked writing to Publish.
echo ZIP: "%WORK%\%NAME%"
echo Target: "%OUTPUT%"
echo Copy the ZIP using File Explorer. The generated ZIP will be kept.
echo Check Windows Security - Ransomware protection - Controlled folder access.
if /I not "%~1"=="/nopause" (
    start "" explorer.exe /select,"%WORK%\%NAME%"
    start "" explorer.exe "%OUTPUT%"
)
set "RESULT=2"
:finish
if /I not "%~1"=="/nopause" pause
endlocal & exit /b %RESULT%
