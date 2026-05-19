<#
.SYNOPSIS
    Hockey Analytics App - Windows Installer

.DESCRIPTION
    Installs and configures the Hockey Analytics App on Windows.
    Run this script as Administrator.

    What this script does:
      1. Downloads the application code from GitHub
      2. Installs Python 3.11 (if not already installed)
      3. Creates a Python virtual environment and installs packages
      4. Installs Visual C++ 2019 Redistributable (required by MySQL)
      5. Installs MySQL 8.0 (if not already installed)
      6. Creates the database and schema
      7. Prompts for your SportLogIQ and database credentials
      8. Creates a double-clickable start.bat to launch the app
#>

#Requires -Version 5.1

# --- Configuration: update these if the repository moves ---------------------
$REPO_ZIP_URL   = "https://github.com/Veronica123abc/icehockey-secrets/archive/refs/heads/master.zip"
$REPO_SUBDIR    = "icehockey-secrets-master"   # folder name inside the extracted ZIP
$PYTHON_URL     = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
$MYSQL_VERSION  = "8.0.46"   # final MySQL 8.0 release; update here if needed
# Tried in order -- first URL that succeeds is used
$MYSQL_URLS = @(
    "https://cdn.mysql.com/Downloads/MySQL-8.0/mysql-$MYSQL_VERSION-winx64.zip",
    "https://dev.mysql.com/get/Downloads/MySQL-8.0/mysql-$MYSQL_VERSION-winx64.zip",
    "https://ftp.osuosl.org/pub/mysql/Downloads/MySQL-8.0/mysql-$MYSQL_VERSION-winx64.zip",
    "https://mirrors.dotsrc.org/mysql/Downloads/MySQL-8.0/mysql-$MYSQL_VERSION-winx64.zip"
)
# -----------------------------------------------------------------------------

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

# --- Auto-elevate to Administrator -------------------------------------------
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "This installer needs to run as Administrator." -ForegroundColor Yellow
    Write-Host "Restarting with elevated privileges..."
    $scriptPath = if ($PSCommandPath) { $PSCommandPath } else { $MyInvocation.MyCommand.Path }
    Start-Process powershell -ArgumentList "-ExecutionPolicy Bypass -File `"$scriptPath`"" -Verb RunAs
    exit
}

# --- Helper functions --------------------------------------------------------
function Write-Step($n, $msg)  { Write-Host "" ; Write-Host "[Step $n] $msg" -ForegroundColor Cyan }
function Write-OK($msg)        { Write-Host "  OK: $msg" -ForegroundColor Green }
function Write-Info($msg)      { Write-Host "      $msg" -ForegroundColor Gray }
function Write-Err($msg)       { Write-Host "  ERROR: $msg" -ForegroundColor Red }

function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" +
                [Environment]::GetEnvironmentVariable("Path","User")
}

function Download-File($url, $dest) {
    if (-not $url) {
        Write-Err "BUG: Download-File called with empty URL (dest=$dest). Check that all config variables are set."
        Read-Host; exit 1
    }
    Write-Info "Downloading: $url"
    $wc = New-Object System.Net.WebClient
    $wc.Headers.Add("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36")
    $wc.DownloadFile($url, $dest)
}

function SecureToPlain([securestring]$ss) {
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($ss)
    try   { [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
}

# --- Banner ------------------------------------------------------------------
Clear-Host
Write-Host ""
Write-Host "  +==================================================+" -ForegroundColor Blue
Write-Host "  |     Hockey Analytics App  -  Installer          |" -ForegroundColor Blue
Write-Host "  +==================================================+" -ForegroundColor Blue
Write-Host ""
Write-Host "  This will install everything needed to run the app."
Write-Host "  Estimated time: 5-15 minutes (depending on internet speed)."
Write-Host ""
Read-Host "  Press ENTER to start (or Ctrl+C to cancel)"

# --- Step 1: Choose install location and download code -----------------------
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
    Write-Info "App files already present -- skipping download."
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

# --- Step 2: Python 3.11 -----------------------------------------------------
Write-Step 2 "Python 3.11"

function Find-Python311 {
    # Ask the py launcher for the actual executable path
    try {
        $exe = (& py -3.11 -c "import sys; print(sys.executable)" 2>&1).Trim()
        if ((Test-Path $exe) -and ("$(& `"$exe`" --version 2>&1)" -match "3\.11")) {
            return $exe
        }
    } catch {}

    # Check if the python in PATH is 3.11
    try {
        $v = & python --version 2>&1
        if ("$v" -match "3\.11") {
            $src = (Get-Command python -ErrorAction SilentlyContinue).Source
            if ($src) { return $src }
        }
    } catch {}

    # Check known install locations (AllUsers install and per-user install)
    $candidates = @(
        "C:\Program Files\Python311\python.exe",
        "C:\Python311\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe"
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) {
            $v = & "$c" --version 2>&1
            if ("$v" -match "3\.11") { return $c }
        }
    }
    return $null
}

$python311 = Find-Python311
if ($python311) {
    $v = & "$python311" --version 2>&1
    Write-OK "Found: $v"
    Write-Info "Path: $python311"
} else {
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
    $python311 = Find-Python311
    if (-not $python311) {
        # MSI installs to this path with InstallAllUsers=1
        $python311 = "C:\Program Files\Python311\python.exe"
    }
    Write-OK "Python 3.11 installed"
    Write-Info "Path: $python311"
}

# --- Step 3: Virtual environment and packages --------------------------------
Write-Step 3 "Python virtual environment and packages"

$venvPython = "$appDir\venv\Scripts\python.exe"
$venvPip    = "$appDir\venv\Scripts\pip.exe"

# Clean up a broken venv (e.g. from a previous interrupted run)
if ((Test-Path "$appDir\venv") -and (-not (Test-Path $venvPython))) {
    Write-Info "Incomplete virtual environment detected -- recreating..."
    Remove-Item "$appDir\venv" -Recurse -Force
}

if (-not (Test-Path $venvPython)) {
    Write-Info "Creating virtual environment with $python311 ..."
    & "$python311" -m venv "$appDir\venv"
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $venvPython)) {
        Write-Err "Virtual environment creation failed."
        Read-Host; exit 1
    }
    Write-OK "Virtual environment created"
} else {
    Write-Info "Virtual environment already exists -- skipping."
}

Write-Info "Installing Python packages (this takes a few minutes)..."
& $venvPython -m pip install --upgrade pip --quiet 2>&1 | Out-Null
& $venvPython -m pip install -r "$appDir\requirements.txt"
if ($LASTEXITCODE -ne 0) {
    Write-Err "Package installation failed. Check your internet connection and try again."
    Read-Host; exit 1
}
Write-OK "Packages installed"

# --- Step 4: Visual C++ 2019 Redistributable (required by MySQL) -------------
Write-Step 4 "Visual C++ 2019 Redistributable"

Write-Info "Downloading Visual C++ 2019 Redistributable (~25 MB)..."
$vcInst = "$env:TEMP\vc_redist.x64.exe"
Download-File "https://aka.ms/vs/17/release/vc_redist.x64.exe" $vcInst
Write-Info "Installing (safe to run even if already installed)..."
$p = Start-Process -FilePath $vcInst -Wait -PassThru -ArgumentList "/install /quiet /norestart"
Remove-Item $vcInst -ErrorAction SilentlyContinue
# 0 = success, 1638 = newer version already installed, 3010 = success + reboot suggested
if ($p.ExitCode -notin @(0, 1638, 3010)) {
    Write-Err "Visual C++ installer failed (exit $($p.ExitCode))."
    Read-Host; exit 1
}
Write-OK "Visual C++ 2019 Redistributable ready"

# --- Step 5: MySQL 8.0 -------------------------------------------------------
Write-Step 5 "MySQL 8.0"

$mysqlDir  = "$installDir\mysql"
$mysqlData = "$installDir\mysql-data"
$mysqldExe = "$mysqlDir\bin\mysqld.exe"
$mysqlExe  = "$mysqlDir\bin\mysql.exe"
$myIni     = "$installDir\my.ini"

function Find-MysqlExe {
    $candidates = @(
        "$mysqlDir\bin\mysql.exe",
        "C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe",
        "C:\Program Files\MySQL\MySQL Server 8.4\bin\mysql.exe",
        "C:\xampp\mysql\bin\mysql.exe"
    )
    foreach ($c in $candidates) { if (Test-Path $c) { return $c } }
    $found = Get-Command mysql -ErrorAction SilentlyContinue
    if ($found) { return $found.Source }
    return $null
}

# If a HockeyMySQL service exists but either binary is missing, the previous install
# was incomplete. Remove the service and the partial mysql directory so we start clean.
$staleHockey = Get-Service -Name "HockeyMySQL" -ErrorAction SilentlyContinue
if ($staleHockey -and -not ((Test-Path $mysqldExe) -and (Test-Path $mysqlExe))) {
    Write-Info "Removing incomplete/stale HockeyMySQL service (left by a previous install attempt)..."
    if ($staleHockey.Status -eq "Running") { Stop-Service HockeyMySQL -Force -ErrorAction SilentlyContinue }
    & sc.exe delete HockeyMySQL | Out-Null
    Start-Sleep 2
    if (Test-Path $mysqlDir) { Remove-Item $mysqlDir -Recurse -Force -ErrorAction SilentlyContinue }
    Write-OK "Stale service and partial files removed"
}

# Check for any already-running MySQL service with both binaries present
$existingSvc = Get-Service -Name "MySQL*", "HockeyMySQL" -ErrorAction SilentlyContinue |
    Where-Object { $_.Status -eq "Running" } |
    Select-Object -First 1
$ourMysqlReady = $existingSvc -and (Test-Path $mysqldExe) -and (Test-Path $mysqlExe)

if ($ourMysqlReady) {
    Write-Info "MySQL already installed and running ($($existingSvc.Name))."
    Write-OK "Using MySQL at $mysqlExe"
} else {
    # Install MySQL from the CDN ZIP (no GUI, fully automated)
    if (-not (Test-Path $mysqldExe)) {
        $mysqlZip = "$env:TEMP\mysql_server.zip"
        Write-Info "Downloading MySQL $MYSQL_VERSION (~250 MB -- the longest step)..."
        $downloaded = $false
        foreach ($url in $MYSQL_URLS) {
            Write-Info "Trying $url ..."
            try {
                Download-File $url $mysqlZip
                $downloaded = $true
                break
            } catch {
                Write-Info "Failed: $($_.Exception.Message)"
            }
        }
        if (-not $downloaded) {
            Write-Err "Could not download MySQL from any mirror. Check your internet connection and try again."
            Read-Host; exit 1
        }
        Write-Info "Extracting..."
        $tmpExtract = "$env:TEMP\mysql_extract"
        Expand-Archive -LiteralPath $mysqlZip -DestinationPath $tmpExtract -Force
        if (Test-Path $mysqlDir) { Remove-Item $mysqlDir -Recurse -Force }
        Move-Item "$tmpExtract\mysql-$MYSQL_VERSION-winx64" $mysqlDir
        Remove-Item $tmpExtract, $mysqlZip -Recurse -ErrorAction SilentlyContinue
        Write-OK "MySQL extracted to $mysqlDir"
    } else {
        Write-Info "MySQL already extracted -- skipping download."
    }

    # Write my.ini (mysqld prefers forward slashes on Windows)
    $fwdMysqlDir  = $mysqlDir.Replace("\", "/")
    $fwdMysqlData = $mysqlData.Replace("\", "/")
    $myIniContent = "[mysqld]`r`nbasedir=$fwdMysqlDir`r`ndatadir=$fwdMysqlData`r`nport=3306`r`ndefault_authentication_plugin=mysql_native_password`r`n`r`n[mysql]`r`ndefault-character-set=utf8mb4`r`n"
    [System.IO.File]::WriteAllText($myIni, $myIniContent, [System.Text.Encoding]::ASCII)

    # Initialise data directory (only on first run)
    if (-not (Test-Path "$mysqlData\mysql")) {
        Write-Info "Initialising MySQL data directory..."
        New-Item -ItemType Directory -Path $mysqlData -Force | Out-Null
        $proc = Start-Process -FilePath $mysqldExe -Wait -PassThru -WindowStyle Hidden `
            -ArgumentList "--defaults-file=`"$myIni`"", "--initialize-insecure", "--datadir=`"$mysqlData`""
        if ($proc.ExitCode -ne 0) {
            Write-Err "MySQL initialisation failed (exit $($proc.ExitCode))."
            Read-Host; exit 1
        }
        Write-OK "Data directory initialised"
    }

    # Verify the extraction actually produced mysql.exe before going further
    if (-not (Test-Path $mysqlExe)) {
        Write-Err "mysql.exe not found at $mysqlExe after extraction."
        Write-Info "The ZIP may have extracted to a different folder name."
        Write-Info "Check $($installDir) and look for a mysql-*/bin/mysql.exe."
        Read-Host; exit 1
    }

    # Always (re-)register the service so it points to the current my.ini.
    # A stale registration from a previous run is the most common cause of start failure.
    $svc = Get-Service -Name "HockeyMySQL" -ErrorAction SilentlyContinue
    if ($svc) {
        if ($svc.Status -eq "Running") { Stop-Service HockeyMySQL -Force -ErrorAction SilentlyContinue }
        & sc.exe delete HockeyMySQL | Out-Null
        Start-Sleep 3
    }
    Write-Info "Registering MySQL as a Windows service..."
    & $mysqldExe --install HockeyMySQL "--defaults-file=$myIni"
    Write-OK "Service registered"

    Write-Info "Starting MySQL service..."
    try {
        Start-Service HockeyMySQL -ErrorAction Stop
        Start-Sleep 8
    } catch {
        Write-Err "MySQL service failed to start: $($_.Exception.Message)"
        $errLog = Get-ChildItem $mysqlData -Filter "*.err" -ErrorAction SilentlyContinue |
                  Select-Object -First 1
        if ($errLog) {
            Write-Host "  MySQL error log ($($errLog.FullName)) -- last 30 lines:" -ForegroundColor Yellow
            Get-Content $errLog.FullName -Tail 30 | ForEach-Object { Write-Host "    $_" }
        } else {
            Write-Info "No MySQL error log found in $mysqlData -- check Windows Event Viewer."
        }
        Read-Host; exit 1
    }
    Write-OK "MySQL service is running"
}

# --- Step 6: Database credentials and schema ---------------------------------
Write-Step 6 "Database setup"

Write-Host ""
Write-Host "  Choose a username and password for the app's MySQL account."
Write-Host "  (These will be created automatically -- you can pick anything you like.)"
Write-Host ""
$dbUser = (Read-Host "  Database username (press ENTER for 'hockeyuser')").Trim()
if (-not $dbUser) { $dbUser = "hockeyuser" }
$dbPwd = ""
while (-not $dbPwd) {
    Write-Host "  Database password: " -NoNewline
    $dbPwd = SecureToPlain (Read-Host -AsSecureString)
    if (-not $dbPwd) { Write-Info "Password cannot be empty. Please try again." }
}

function Invoke-Mysql($argList, $sqlFile) {
    $errFile = "$env:TEMP\mysql_stderr.txt"
    $proc = Start-Process -FilePath $mysqlExe `
        -ArgumentList $argList `
        -RedirectStandardInput $sqlFile `
        -RedirectStandardError $errFile `
        -Wait -PassThru -WindowStyle Hidden
    $raw     = if (Test-Path $errFile) { Get-Content $errFile -Raw } else { $null }
    $errText = if ($raw) { $raw.Trim() } else { "" }
    Remove-Item $errFile -ErrorAction SilentlyContinue
    return @{ Code = $proc.ExitCode; Err = $errText }
}

function Write-SqlFile($path, $lines) {
    # Use ASCII to avoid the UTF-8 BOM that PS 5.1 adds, which MySQL misreads.
    [System.IO.File]::WriteAllText($path, ($lines -join "`r`n"), [System.Text.Encoding]::ASCII)
}

# Try connecting as root with no password first; if that fails ask for it.
$rootArgList = @("-u", "root")
$pingFile    = "$env:TEMP\hockey_ping.sql"
Write-SqlFile $pingFile @("SELECT 1;")

Write-Info "Testing connection to MySQL..."
$ping = Invoke-Mysql $rootArgList $pingFile
if ($ping.Code -ne 0) {
    Write-Host ""
    Write-Host "  MySQL root password (press ENTER if none was set during install): " -NoNewline
    $rootPwd = SecureToPlain (Read-Host -AsSecureString)
    if ($rootPwd) { $rootArgList += "-p$rootPwd" }

    $ping = Invoke-Mysql $rootArgList $pingFile
    if ($ping.Code -ne 0) {
        Write-Err "Cannot connect to MySQL as root."
        if ($ping.Err) { Write-Host "      MySQL says: $($ping.Err)" -ForegroundColor Red }
        Write-Host "  Tip: re-run setup.bat -- the service sometimes needs an extra minute." -ForegroundColor Yellow
        Remove-Item $pingFile -ErrorAction SilentlyContinue
        Read-Host; exit 1
    }
}
Remove-Item $pingFile -ErrorAction SilentlyContinue
Write-OK "Connected to MySQL"

Write-Info "Creating database and user..."
$setupFile = "$env:TEMP\hockey_setup.sql"
Write-SqlFile $setupFile @(
    "CREATE DATABASE IF NOT EXISTS sportlogiq CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;",
    "CREATE USER IF NOT EXISTS '${dbUser}'@'localhost' IDENTIFIED WITH mysql_native_password BY '${dbPwd}';",
    "GRANT ALL PRIVILEGES ON sportlogiq.* TO '${dbUser}'@'localhost';",
    "FLUSH PRIVILEGES;"
)
$result = Invoke-Mysql $rootArgList $setupFile
Remove-Item $setupFile -ErrorAction SilentlyContinue
if ($result.Code -ne 0) {
    Write-Err "Could not create database or user."
    if ($result.Err) { Write-Host "      MySQL says: $($result.Err)" -ForegroundColor Red }
    Read-Host; exit 1
}

Write-Info "Loading database schema..."
$schemaPath = "$appDir\hockey\db\schema\schema.sql"
$schemaArgs = $rootArgList + @("sportlogiq")
$result = Invoke-Mysql $schemaArgs $schemaPath
if ($result.Code -ne 0) {
    Write-Err "Schema load failed."
    if ($result.Err) { Write-Host "      MySQL says: $($result.Err)" -ForegroundColor Red }
    Read-Host; exit 1
}
Write-OK "Database schema loaded"

# --- Step 7: SportLogIQ credentials ------------------------------------------
Write-Step 7 "SportLogIQ credentials"
Write-Host ""
Write-Host "  Enter the username and password for your SportLogIQ account."
Write-Host "  These are used to download game data on demand."
Write-Host ""
$slUser = (Read-Host "  SportLogIQ username (email)").Trim()
$slPwd = ""
while (-not $slPwd) {
    Write-Host "  SportLogIQ password: " -NoNewline
    $slPwd = SecureToPlain (Read-Host -AsSecureString)
    if (-not $slPwd) { Write-Info "Password cannot be empty. Please try again." }
}

# --- Step 8: Game data directory ---------------------------------------------
Write-Step 8 "Game data directory"
$defaultData = "$installDir\data"
$dataDir = (Read-Host "  Where should game files be stored? (press ENTER for $defaultData)").Trim()
if (-not $dataDir) { $dataDir = $defaultData }
New-Item -ItemType Directory -Path $dataDir -Force | Out-Null
Write-OK "Game data directory: $dataDir"

# --- Step 9: Write .env ------------------------------------------------------
Write-Step 9 "Writing configuration"

$envLines = @(
    "DATA_ROOT_DIR=$dataDir",
    "SPORTLOGIQ_USERNAME=$slUser",
    "SPORTLOGIQ_PWD=$slPwd",
    "DATABASE_HOST_AZURE=localhost",
    "DATABASE_USERNAME_AZURE=$dbUser",
    "DATABASE_PWD_AZURE=$dbPwd",
    "DATABASE_NAME_AZURE=sportlogiq"
)
Set-Content -Path "$appDir\.env" -Value ($envLines -join "`r`n") -Encoding UTF8
Write-OK ".env written to $appDir\.env"

# --- Create start.bat --------------------------------------------------------
$startBat = "@echo off`r`ncd /d %~dp0`r`necho Starting Hockey Analytics App...`r`necho.`r`ncall venv\Scripts\activate.bat`r`nflask run`r`necho.`r`necho The app has stopped.`r`npause`r`n"
Set-Content -Path "$appDir\start.bat" -Value $startBat -Encoding ASCII
Write-OK "start.bat created at $appDir\start.bat"

# --- Done --------------------------------------------------------------------
Write-Host ""
Write-Host "  +==================================================+" -ForegroundColor Green
Write-Host "  |          Installation complete!                  |" -ForegroundColor Green
Write-Host "  +==================================================+" -ForegroundColor Green
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
