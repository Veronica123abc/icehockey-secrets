# Deploying Ice Hockey Analytics to Azure Web App

A practical guide based on deploying this Flask app to Azure App Service.

---

## Table of Contents

1. [Project Overview](#project-overview)
2. [Creating a Web App in Azure Portal](#creating-a-web-app-in-azure-portal)
3. [Creating a Web App with Azure CLI](#creating-a-web-app-with-azure-cli)
4. [Configuring the Web App](#configuring-the-web-app)
5. [Deploying Code](#deploying-code)
6. [CI/CD with GitHub Actions](#cicd-with-github-actions)
7. [Uploading Data Files](#uploading-data-files)
8. [Managing Secrets and Environment Variables](#managing-secrets-and-environment-variables)
9. [Troubleshooting](#troubleshooting)
10. [File Reference](#file-reference)

---

## Project Overview

The web app is a Flask application (`app.py`) that wraps the `hockey/` analytics module. It serves:

- **Home page** (`/`) — lists available games from the data directory
- **Game page** (`/game/<id>`) — interactive Plotly shift-TOI chart with scoring chances
- **REST API** — `/api/games`, `/api/game/<id>`, `/api/game/<id>/events`

The visualization logic lives in `hockey/visualize/shift_toi.py`. The web app calls it
directly to avoid code duplication.

---

## Creating a Web App in Azure Portal

1. Go to [portal.azure.com](https://portal.azure.com)
2. Click **Create a resource** > search for **Web App** > click **Create**
3. Fill in:
   - **Resource Group**: create new or pick existing
   - **Name**: your app name (becomes `<name>.azurewebsites.net`)
   - **Publish**: **Code** (not Container)
   - **Runtime stack**: **Python 3.11**
   - **Operating System**: **Linux**
   - **Region**: pick one close to you (e.g. Sweden Central)
4. Click **Review + create** > **Create**
5. After creation, go to **Configuration** > **General settings**:
   - Set **Startup Command** to:
     ```
     gunicorn --bind=0.0.0.0:8000 --timeout 120 --workers 2 app:app
     ```
   - Click **Save**

> **Note:** The startup command tells Azure how to run your app. Without it, Azure
> tries to auto-detect, which may or may not work. Always set it explicitly.

---

## Creating a Web App with Azure CLI

If you prefer the command line:

```bash
# Login (opens browser for authentication + 2FA)
az login

# Create and deploy in one step
cd /path/to/icehockey-secrets
az webapp up --name <your-app-name> --resource-group <your-rg> --runtime "PYTHON:3.11"
```

`az webapp up` does several things at once:
- Creates the Web App if it doesn't exist
- Zips your local code and uploads it
- Installs dependencies from `requirements.txt`
- Saves settings to `.azure/config` so next time you can just run `az webapp up`

After the first run, `az webapp up` with no arguments reuses the saved config.

> **Tip:** Add `.azure/` to `.gitignore` — it contains local settings and subscription IDs.

---

## Configuring the Web App

### Startup Command

Azure Portal > your Web App > **Configuration** > **General settings** > **Startup Command**:

```
gunicorn --bind=0.0.0.0:8000 --timeout 120 --workers 2 app:app
```

### Python Version

Azure Portal > your Web App > **Configuration** > **Stack settings** > **Python version**.

**Important:** The Python version here must match the version used to build your
dependencies. If you build with 3.11 but run with 3.10, you'll see errors like:

```
error while loading shared libraries: libpython3.11.so.1.0: cannot open shared object file
```

### Environment Variables

Azure Portal > your Web App > **Environment variables** (under Settings in the left sidebar).

This is where you set configuration like `DATA_ROOT_DIR` and `SCM_DO_BUILD_DURING_DEPLOYMENT`.
These are the Azure equivalent of a `.env` file.

Key settings for this app:

| Name | Value | Purpose |
|------|-------|---------|
| `DATA_ROOT_DIR` | `/home/data` | Where game JSON files are stored |
| `SCM_DO_BUILD_DURING_DEPLOYMENT` | `true` | Tells Azure to run `pip install` during deploy |

> **Note:** "Environment variables" is a separate menu item under Settings.
> It is NOT inside Configuration. The Azure Portal layout changes occasionally,
> so if you can't find something, try searching in the portal search bar.

---

## Deploying Code

There are two ways to deploy. You only need one.

### Option 1: Azure CLI (manual)

```bash
cd /path/to/icehockey-secrets
az webapp up
```

This zips your local code and pushes it directly. Deployments show as
**"Created via push deployment"** in the deployment history.

### Option 2: GitHub Actions (automatic)

When you connect GitHub in the **Deployment Center**, Azure creates a workflow
file and pushes it to your repo. Every push to the configured branch triggers
a build and deploy. These show as **"OneDeploy"** in the deployment history.

See the next section for details.

---

## CI/CD with GitHub Actions

### How It Gets Set Up

1. Azure Portal > your Web App > **Deployment Center**
2. **Source**: GitHub
3. Select your repository and branch
4. Click **Save**

Azure automatically:
- Creates `.github/workflows/<branch>_<appname>.yml` in your repo
- Configures GitHub secrets for Azure authentication
- Pushes the workflow file to your branch

### What the Workflow Does

The generated workflow has two jobs:

1. **build** — checks out code, sets up Python, installs dependencies, uploads artifact
2. **deploy** — downloads artifact, logs into Azure, deploys to your Web App

### Files Affected

```
.github/
  workflows/
    <branch>_<appname>.yml    # Auto-generated by Azure
```

### Common Pitfalls

- **Python version mismatch**: The workflow has a `python-version` field. It MUST
  match the Python version configured in your Azure Web App. If Azure generates it
  with `3.10` but your app runs `3.11`, change it in the `.yml` file.

- **Duplicate workflows**: If you set up Deployment Center multiple times (e.g.
  after renaming your app), you may end up with multiple workflow files. Each one
  triggers on push, causing race conditions. Delete the old ones.

- **Workflow runs on push**: The workflow triggers on every push to the configured
  branch. This includes commits made via the GitHub API, not just local pushes.

### Example Workflow

See `.github/workflows/claude-deploy-azure-webapp-deub7_hockeystats-demo-eneffkg6gbh4gcgg.yml`

---

## Uploading Data Files

The app reads game data from `DATA_ROOT_DIR` (e.g. `/home/data`). Each game is a
folder named by its ID containing JSON files:

```
/home/data/
  168742/
    game-info.json
    playsequence.json
    playerTOI.json
    roster.json
  202401/
    ...
```

The `/home` directory on Azure Web App is **persistent** — it survives restarts
and redeployments. Everything else is ephemeral.

### Option 1: Kudu File Browser (drag & drop)

The easiest method for a few files:

1. Azure Portal > your Web App > **Advanced Tools** > click **Go**
2. Click **Debug console** > **Bash** in the top menu
3. In the console, run: `mkdir -p /home/data`
4. Navigate to `/home/data` by clicking the folder names in the file browser
   (it's the panel ABOVE the console)
5. **Drag and drop** game folders from your file manager into the browser

### Option 2: Azure CLI SSH

```bash
# Open an SSH session to your web app
az webapp ssh --name <your-app-name>

# Inside the SSH session:
mkdir -p /home/data
# (then use scp or other tools to transfer files)
```

### Option 3: Azure CLI Deploy

```bash
# Zip your game data
cd /path/to/game/data
zip -r gamedata.zip 168742/ 202401/

# Deploy the zip
az webapp deploy --name <your-app-name> --src-path gamedata.zip --target-path /home/data --type zip
```

### Option 4: FTP

1. Azure Portal > your Web App > **Deployment Center** > **FTPS credentials**
2. Note the FTP endpoint, username, and password
3. Use any FTP client (FileZilla, etc.) to connect and upload to `/home/data`

> **Note:** You cannot use regular `scp` with Azure Web Apps — there is no
> public SSH endpoint. Use the methods above instead.

---

## Managing Secrets and Environment Variables

### The Golden Rule

**Never commit credentials to git.** Even if you delete the file later, the
credentials remain in git history forever. If you accidentally commit secrets:

1. **Change the passwords immediately** — this is the only real fix
2. Delete the file from the repo
3. Make sure `.gitignore` prevents it from being committed again

### Where to Put Secrets

| Context | Where | How |
|---------|-------|-----|
| Local development | `.env` file | Loaded by the app at startup |
| Azure Web App | Environment variables | Set in Azure Portal (encrypted at rest) |
| GitHub Actions | Repository secrets | Set in GitHub > Settings > Secrets |

### .env File Safety

- `.env` is in `.gitignore` — it will not be committed
- `.env.example` shows the expected variables without real values
- Copy `.env.example` to `.env` and fill in your values for local dev

### When to Use Azure Key Vault

For this app, Azure Environment Variables are sufficient. Consider Key Vault
if you later add:
- Database connections from the web app
- Third-party API keys used at runtime
- Secrets shared across multiple Azure services

---

## Troubleshooting

### "Application Error" on the web page

Check the logs: Azure Portal > your Web App > **Log stream** (under Monitoring).
Common causes:

1. **`ModuleNotFoundError`** — dependencies weren't installed. Check that
   `SCM_DO_BUILD_DURING_DEPLOYMENT` is set to `true` in Environment variables.
2. **`No module named 'app'`** — the code wasn't deployed properly. Redeploy.
3. **Startup command not set** — the log will show `App Command Line not configured`.

### Python version mismatch

If the log shows `error while loading shared libraries: libpython3.X.so`:
- Check Stack settings in Configuration — make sure the Python version matches
  what was used to build (in your GitHub Actions workflow or `az webapp up` command)

### Deployment succeeds but app doesn't update

You might have multiple deployment methods active (CLI + GitHub Actions).
They can overwrite each other. Pick one and stick with it.

Check deployment history to see which deployment is actually running.

### "No framework detected" in logs

Oryx (Azure's build system) couldn't find your app. Make sure:
- `app.py` (or `application.py`) is in the root of your repo
- `requirements.txt` is in the root of your repo

### Timeout during restart

Azure gives the app ~230 seconds to start responding. If your app takes
longer, it shows a timeout. This doesn't necessarily mean the app failed —
check if it works by browsing to the URL.

To increase the timeout, add this Environment variable:
- Name: `WEBSITES_CONTAINER_START_TIME_LIMIT`
- Value: `600` (seconds)

---

## File Reference

| File | Purpose |
|------|---------|
| `app.py` | Flask web application — the entry point for Azure |
| `requirements.txt` | Python dependencies (installed by Azure during build) |
| `startup.sh` | Gunicorn startup command (reference; the actual command is set in Azure Configuration) |
| `.deployment` | Tells Azure to build during deployment |
| `.env.example` | Template for local environment variables |
| `.gitignore` | Keeps secrets, caches, and local config out of git |
| `templates/base.html` | Base HTML template (dark theme, navigation) |
| `templates/index.html` | Home page listing available games |
| `templates/game.html` | Game visualization page with Plotly chart |
| `hockey/visualize/shift_toi.py` | The visualization function called by the web app |
| `.github/workflows/*.yml` | CI/CD pipeline (auto-generated by Azure Deployment Center) |
| `.azure/config` | Local Azure CLI settings (gitignored) |
