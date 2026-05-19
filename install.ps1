<#
.SYNOPSIS
    Hockey Analytics App — Windows Installer

.DESCRIPTION
    Installs and configures the Hockey Analytics App on Windows.
    Run this script as Administrator.

    What this script does:
      1. Downloads the application code from GitHub
      2. Installs Python 3.11 (if not already installed)
      3. Creates a Python virtual environment and installs packages
      4. Installs MySQL 8.0 (if not already installed)
      5. Creates the database and schema
      6. Prompts for your SportLogIQ and database credentials
      7. Creates a double-clickable start.bat to launch the app
#>

#Requires -Version 5.1

# ─── Configuration — update these if the repository moves ────────────────────
$REPO_ZIP_URL   = "https://github.com/Veronica123abc/icehockey-secrets/archive/refs/heads/master.zip"
$REPO_SUBDIR    = "icehockey-secrets-master"   # folder name inside the extracted ZIP
$PYTHON_URL     = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
$MYSQL_URL      = "https://dev.mysql.com/get/Downloads/MySQL-8.0/mysql-8.0.39-winx64.zip"
$MYSQL_SUBDIR   = "mysql-8.0.39-winx64"        # folder name inside the MySQL ZIP
# ─────────────────────────────────────────────────────────────────────────────

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

# ─── Auto-elevate to Administrator ───────────────────────────────────────────
if (-not ([Security.Principal.WindowsPrincipal]
         [Security.Principal.WindowsIdentity]::GetCurrent()
         ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "This installer needs to run as Administrator." -ForegroundColor Yellow
    Write-Host "Restarting with elevated privileges..."
    $scriptPath = if ($PSCommandPath) { $PSCommandPath } else { $MyInvocation.MyCommand.Path }
    Start-Process powershell -ArgumentList "-ExecutionPolicy Bypass -File `"$scriptPath`"" -Verb RunAs
    exit
}

# ─── Helper functions ─────────────────────────────────────────────────────────
function Write-Step($n, $msg)  { Write-Host "`n[Step $n] $msg" -ForegroundColor Cyan }
function Write-OK($msg)        { Write-Host "  OK  $msg" -ForegroundColor Green }
function Write-Info($msg)      { Write-Host "      $msg" -ForegroundColor Gray }
function Write-Err($msg)       { Write-Host "  ERROR  $msg" -ForegroundColor Red }

function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" +
                [Environment]::GetEnvironmentVariable("Path","User")
}

function Download-File($url, $dest) {
    Write-Info "Downloading $(Split-Path $dest -Leaf) ..."
    $wc = New-Object System.Net.WebClient
    $wc.DownloadFile($url, $dest)
}

function SecureToPlain([securestring]$ss) {
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($ss)
    try   { [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
}

# ─── Banner ───────────────────────────────────────────────────────────────────
Clear-Host
Write-Host ""
Write-Host "  ╔══════════════════════════════════════════════════╗" -ForegroundColor Blue
Write-Host "  ║       Hockey Analytics App  —  Installer        ║" -ForegroundColor Blue
Write-Host "  ╚══════════════════════════════════════════════════╝" -ForegroundColor Blue
Write-Host ""
Write-Host "  This will install everything needed to run the app."
Write-Host "  Estimated time: 5-15 minutes (depending on internet speed)."
Write-Host ""
Read-Host "  Press ENTER to start (or Ctrl+C to cancel)"

# ─── Step 1: Choose install location and download code ───────────────────────
Write-Step 1 "Application directory"
$defaultInstallDir = "C:\HockeyApp"
$installDir = (Read-Host "  Install location (press ENTER for $defaultInstallDir)").Trim()
if (-not $installDir) { $installDir = $defaultInstallDir }
$installDir = $installDir.TrimEnd("\")
$appDir = "$installDir\$REPO_SUBDIR"

if ($installDir -match " ") {
    Write-Host "  WARNING: The install path contains a space. MySQL may fail to start." -ForegroundColor Yellow
    Write-Host "  Recommended: use a path without spaces (e.g. C:\HockeyApp)." -ForegroundColor Yellow
    $continue = Read-Host "  Continue anyway? (y/N)"
    if ($continue -notmatch "^[yY]") { exit 0 }
}

if (Test-Path "$appDir\app.py") {
    Write-Info "App files already present — skipping download."
} else {
    New-Item -ItemType Directory -Path $installDir -Force | Out-Null
    $zipDest = "$env:TEMP\hockey_repo.zip"
    Write-Info "Downloading application code from GitHub..."
    Download-File $REPO_ZIP_URL $zipDest
    Write-Info "Extracting..."
    Expand-Archive -LiteralPath $zipDest -DestinationPath $installDir -Force
    Remove-Item $zipDest -ErrorAction SilentlyContinue
    Write-OK "Code downloaded to $appDir"
}

Set-Location $appDir

# ─── Step 2: Python 3.11 ─────────────────────────────────────────────────────
Write-Step 2 "Python 3.11"

# $pyCmd holds the command (array) used for all subsequent python invocations
$pyCmd = $null
try {
    $v = & py -3.11 --version 2>&1
    if ("$v" -match "3\.11") { $pyCmd = @("py","-3.11"); Write-OK "Found: $v" }
} catch {}
if (-not $pyCmd) {
    try {
        $v = & python --version 2>&1
        if ("$v" -match "3\.11") { $pyCmd = @("python"); Write-OK "Found: $v" }
    } catch {}
}

if (-not $pyCmd) {
    Write-Info "Python 3.11 not found. Downloading installer (~27 MB)..."
    $pyInst = "$env:TEMP\python311_setup.exe"
    Download-File $PYTHON_URL $pyInst
    Write-Info "Installing Python 3.11 (this may take a minute)..."
    $p = Start-Process -FilePath $pyInst -Wait -PassThru `
        -ArgumentList "/quiet InstallAllUsers=1 PrependPath=1 Include_launcher=1 Include_test=0"
    Remove-Item $pyInst -ErrorAction SilentlyContinue
    if ($p.ExitCode -ne 0) {
        Write-Err "Python installer exited with code $($p.ExitCode). Install Python 3.11 manually from python.org and re-run."
        Read-Host; exit 1
    }
    Refresh-Path
    $pyCmd = @("py","-3.11")
    Write-OK "Python 3.11 installed"
}

# ─── Step 3: Virtual environment and packages ────────────────────────────────
Write-Step 3 "Python virtual environment and packages"

$venvPython = "$appDir\venv\Scripts\python.exe"
$venvPip    = "$appDir\venv\Scripts\pip.exe"

if (-not (Test-Path $venvPython)) {
    Write-Info "Creating virtual environment..."
    $pyExtra = if ($pyCmd.Count -gt 1) { $pyCmd[1..($pyCmd.Count-1)] } else { @() }
    & $pyCmd[0] @pyExtra -m venv "$appDir\venv"
    Write-OK "Virtual environment created"
} else {
    Write-Info "Virtual environment already exists — skipping."
}

Write-Info "Installing Python packages (this takes a few minutes)..."
& $venvPip install --upgrade pip --quiet 2>&1 | Out-Null
& $venvPip install -r "$appDir\requirements.txt"
if ($LASTEXITCODE -ne 0) {
    Write-Err "Package installation failed. Check your internet connection and try again."
    Read-Host; exit 1
}
Write-OK "Packages installed"

# ─── Step 4: MySQL ────────────────────────────────────────────────────────────
Write-Step 4 "MySQL 8.0"

$mysqlDir  = "$installDir\mysql"
$mysqlData = "$installDir\mysql-data"
$mysqldExe = "$mysqlDir\bin\mysqld.exe"
$mysqlExe  = "$mysqlDir\bin\mysql.exe"
$myIni     = "$installDir\my.ini"
$usingExternalMySQL = $false
$rootPwdArgs = @()   # empty = no password

# Check for an existing MySQL installation
$existingSvc = Get-Service -Name "MySQL*","MariaDB*" -ErrorAction SilentlyContinue |
               Where-Object { $_.Status -eq "Running" } | Select-Object -First 1

if ($existingSvc) {
    Write-Info "Found existing MySQL/MariaDB service: $($existingSvc.Name)"
    $systemMysql = Get-Command mysql -ErrorAction SilentlyContinue
    if ($systemMysql) {
        $mysqlExe = $systemMysql.Source
        Write-OK "Using existing MySQL at $mysqlExe"
    } else {
        Write-Info "mysql.exe not in PATH — looking in common install locations..."
        $candidates = @(
            "C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe",
            "C:\Program Files\MySQL\MySQL Server 5.7\bin\mysql.exe",
            "C:\xampp\mysql\bin\mysql.exe"
        )
        foreach ($c in $candidates) {
            if (Test-Path $c) { $mysqlExe = $c; break }
        }
    }
    $usingExternalMySQL = $true
    Write-Info "Will use existing MySQL — root password may be required."
} else {
    # Install MySQL from ZIP (silent, no GUI)
    if (Test-Path $mysqldExe) {
        Write-Info "MySQL already extracted to $mysqlDir"
    } else {
        $mysqlZip = "$env:TEMP\mysql_server.zip"
        Write-Info "Downloading MySQL 8.0 (~200 MB — this is the longest step)..."
        Download-File $MYSQL_URL $mysqlZip
        Write-Info "Extracting MySQL..."
        $tmpExtract = "$env:TEMP\mysql_extract"
        Expand-Archive -LiteralPath $mysqlZip -DestinationPath $tmpExtract -Force
        if (Test-Path $mysqlDir) { Remove-Item $mysqlDir -Recurse -Force }
        Move-Item "$tmpExtract\$MYSQL_SUBDIR" $mysqlDir
        Remove-Item $tmpExtract, $mysqlZip -Recurse -ErrorAction SilentlyContinue
        Write-OK "MySQL extracted to $mysqlDir"
    }

    # Write my.ini (use forward slashes — mysqld prefers them on Windows)
    $fwdMysqlDir  = $mysqlDir.Replace("\","/")
    $fwdMysqlData = $mysqlData.Replace("\","/")
    @"
[mysqld]
basedir=$fwdMysqlDir
datadir=$fwdMysqlData
port=3306
default_authentication_plugin=mysql_native_password

[mysql]
default-character-set=utf8mb4
"@ | Set-Content -Path $myIni -Encoding UTF8

    # Initialize data directory (only if it hasn't been done yet)
    if (-not (Test-Path "$mysqlData\mysql")) {
        Write-Info "Initializing MySQL data directory..."
        New-Item -ItemType Directory -Path $mysqlData -Force | Out-Null
        $proc = Start-Process -FilePath $mysqldExe -Wait -PassThru -WindowStyle Hidden `
            -ArgumentList "--defaults-file=`"$myIni`"", "--initialize-insecure", "--datadir=`"$mysqlData`""
        if ($proc.ExitCode -ne 0) {
            Write-Err "MySQL initialization failed (exit $($proc.ExitCode))."
            Read-Host; exit 1
        }
        Write-OK "MySQL data directory initialized"
    }

    # Install as Windows service (if not already)
    $hockeySvc = Get-Service -Name "HockeyMySQL" -ErrorAction SilentlyContinue
    if (-not $hockeySvc) {
        Write-Info "Registering MySQL as a Windows service..."
        & $mysqldExe --install HockeyMySQL "--defaults-file=$myIni" | Out-Null
        Write-OK "MySQL service registered"
    }

    # Start the service
    $hockeySvc = Get-Service -Name "HockeyMySQL" -ErrorAction SilentlyContinue
    if ($hockeySvc.Status -ne "Running") {
        Write-Info "Starting MySQL service..."
        Start-Service HockeyMySQL
        Write-Info "Waiting for MySQL to come up..."
        Start-Sleep 8
    }
    Write-OK "MySQL service is running"
}

# ─── Step 5: Database credentials + schema ───────────────────────────────────
Write-Step 5 "Database setup"

if ($usingExternalMySQL) {
    Write-Host "  MySQL root password (press ENTER if none): " -NoNewline
    $rootSs  = Read-Host -AsSecureString
    $rootPwd = SecureToPlain $rootSs
    if ($rootPwd) { $rootPwdArgs = @("-p$rootPwd") }
}

$defaultDbUser = "hockeyuser"
$dbUser = (Read-Host "  Database username for the app (press ENTER for '$defaultDbUser')").Trim()
if (-not $dbUser) { $dbUser = $defaultDbUser }

$dbPwd = ""
while (-not $dbPwd) {
    Write-Host "  Password for database user '$dbUser': " -NoNewline
    $dbPwd = SecureToPlain (Read-Host -AsSecureString)
    if (-not $dbPwd) { Write-Info "Password cannot be empty. Please try again." }
}

# Create database + user
Write-Info "Creating database and user..."
$setupSql = (
    "CREATE DATABASE IF NOT EXISTS sportlogiq " +
    "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci; " +
    "CREATE USER IF NOT EXISTS '${dbUser}'@'localhost' " +
    "IDENTIFIED WITH mysql_native_password BY '${dbPwd}'; " +
    "GRANT ALL PRIVILEGES ON sportlogiq.* TO '${dbUser}'@'localhost'; " +
    "FLUSH PRIVILEGES;"
)
& $mysqlExe -u root @rootPwdArgs -e $setupSql
if ($LASTEXITCODE -ne 0) {
    Write-Err "Could not create the database or user. Check the MySQL root password."
    Read-Host; exit 1
}

# Load schema via a temporary batch file (avoids PowerShell redirect quoting issues)
Write-Info "Loading database schema..."
$schemaPath = "$appDir\hockey\db\schema\schema.sql"
$tmpBat = "$env:TEMP\load_schema.bat"
$rootFlag = if ($rootPwdArgs) { $rootPwdArgs[0] } else { "" }
Set-Content -Path $tmpBat -Encoding ASCII -Value (
    "@echo off`r`n" +
    "`"$mysqlExe`" -u root $rootFlag sportlogiq < `"$schemaPath`"`r`n"
)
& cmd /c $tmpBat
Remove-Item $tmpBat -ErrorAction SilentlyContinue
if ($LASTEXITCODE -ne 0) {
    Write-Err "Schema load failed (exit $LASTEXITCODE). Check that MySQL is running and the root password is correct."
    Read-Host; exit 1
}
Write-OK "Database schema loaded"

# ─── Step 6: SportLogIQ credentials ──────────────────────────────────────────
Write-Step 6 "SportLogIQ credentials"
Write-Host ""
Write-Host "  Enter the username and password for your SportLogIQ account."
Write-Host "  These are used to download game data on demand."
Write-Host ""
$slUser = (Read-Host "  SportLogIQ username (email)").Trim()
$slPwd  = ""
while (-not $slPwd) {
    Write-Host "  SportLogIQ password: " -NoNewline
    $slPwd = SecureToPlain (Read-Host -AsSecureString)
    if (-not $slPwd) { Write-Info "Password cannot be empty. Please try again." }
}

# ─── Step 7: Game data directory ─────────────────────────────────────────────
Write-Step 7 "Game data directory"
$defaultData = "$installDir\data"
$dataDir = (Read-Host "  Where should game files be stored? (press ENTER for $defaultData)").Trim()
if (-not $dataDir) { $dataDir = $defaultData }
New-Item -ItemType Directory -Path $dataDir -Force | Out-Null
Write-OK "Game data directory: $dataDir"

# ─── Step 8: Write .env ───────────────────────────────────────────────────────
Write-Step 8 "Writing configuration"

$envLines = @(
    "DATA_ROOT_DIR=$dataDir",
    "SPORTLOGIQ_USERNAME=$slUser",
    "SPORTLOGIQ_PWD=$slPwd",
    "DATABASE_HOST_AZURE=localhost",
    "DATABASE_USERNAME_AZURE=$dbUser",
    "DATABASE_PWD_AZURE=$dbPwd",
    "DATABASE_NAME_AZURE=sportlogiq"
)
Set-Content -Path "$appDir\.env" -Value ($envLines -join "`n") -Encoding UTF8
Write-OK ".env written to $appDir\.env"

# ─── Step 9: Create start.bat ─────────────────────────────────────────────────
$startBat = @"
@echo off
cd /d %~dp0
echo Starting Hockey Analytics App...
echo.
call venv\Scripts\activate.bat
flask run
echo.
echo The app has stopped.
pause
"@
Set-Content -Path "$appDir\start.bat" -Value $startBat -Encoding ASCII
Write-OK "start.bat created at $appDir\start.bat"

# ─── Done ─────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "  ╔══════════════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "  ║            Installation complete!               ║" -ForegroundColor Green
Write-Host "  ╚══════════════════════════════════════════════════╝" -ForegroundColor Green
Write-Host ""
Write-Host "  App installed to:"
Write-Host "    $appDir" -ForegroundColor Yellow
Write-Host ""
Write-Host "  TO START THE APP:" -ForegroundColor White
Write-Host "    1. Open the folder above in File Explorer"
Write-Host "    2. Double-click  start.bat"
Write-Host "    3. Open your browser to  http://localhost:5000" -ForegroundColor Cyan
Write-Host ""
Write-Host "  When you open a game, the app will automatically download"
Write-Host "  its data from SportLogIQ the first time."
Write-Host ""
Read-Host "  Press ENTER to close this window"
