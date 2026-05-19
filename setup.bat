@echo off
::
::  Hockey Analytics App — Setup launcher
::
::  HOW TO USE:
::    Right-click this file and choose "Run as administrator"
::    An internet connection is required.
::

setlocal

:: Auto-elevate to Administrator if not already elevated
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo Requesting administrator privileges...
    powershell -Command "Start-Process cmd -ArgumentList '/c \"%~f0\"' -Verb RunAs"
    exit /b
)

echo.
echo  ======================================================
echo    Hockey Analytics App  ^|  Setup
echo  ======================================================
echo.
echo  Downloading installer from GitHub...
echo.

powershell -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; (New-Object Net.WebClient).DownloadFile('https://raw.githubusercontent.com/Veronica123abc/icehockey-secrets/claude/master/install.ps1', '%TEMP%\hockey_install.ps1')"

if %errorLevel% neq 0 (
    echo.
    echo  ERROR: Could not download the installer.
    echo  Check your internet connection and try again.
    echo.
    pause
    exit /b 1
)

powershell -ExecutionPolicy Bypass -File "%TEMP%\hockey_install.ps1"

endlocal
pause
