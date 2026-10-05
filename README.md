# ⚡ Live Server — JNR Corporations

### Fast, secure, cross-platform LAN gateway for the **real VS Code Live Server**.

**Organization:** JNR Corporations  
**Developer:** Raj Verma  
**Release:** `2.1.0`  
**Platforms:** Kali/Debian/Ubuntu + Windows 10/11  
**Runtime:** Python 3.11+

> Live Server does **not** replace VS Code Live Server with another static file server. It securely proxies the development server you already run locally and makes it reachable from another device on the same LAN.

## ✨ Highlights

- 🚀 Event-driven live reload; CSS hot-update where practical
- ⚡ HTTP + WebSocket reverse proxying to the real upstream
- 🔎 Local development-server discovery, with `5500` preferred
- 📱 Real LAN URL + QR pairing
- 👥 Browser session registry with Revoke + Restore/Unrevoke
- 🛡️ Loopback-only upstream validation and localhost dashboard
- 🧾 Release integrity manifest + strict startup mode
- 🧪 GitHub Actions CI for Linux and Windows
- 🧭 One-command terminal bootstrap on both platforms
- 🏢 JNR Corporations / Raj Verma branding

## 🧠 Architecture

```text
VS Code + Live Server
127.0.0.1:5500
       │
       ▼
┌────────────────────────────┐
│ Live Server Gateway        │
│ FastAPI + reverse proxy    │
│ Sessions + QR + watcher    │
└──────────────┬─────────────┘
               │ authenticated LAN
        ┌──────┴──────┐
        ▼             ▼
     Phone         Laptop
```

Management dashboard: `http://127.0.0.1:8765`  
LAN preview: generated dynamically, never hardcoded.

# 🚀 Installation

## 🐧 Linux / Kali / Debian / Ubuntu

### One-command start

```bash
cd live-server
python3 start.py
```

Or:

```bash
./run.sh
```

First-time setup only:

```bash
./setup.sh
```

If Kali/Debian says `venv` is unavailable:

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip
```

Verify release files:

```bash
python3 verify_integrity.py
```

Strict mode:

```bash
python3 start.py --strict-integrity
```

## 🪟 Windows PowerShell

```powershell
cd .\live-server
py start.py
```

Or:

```powershell
python start.py
```

First-time setup:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\setup_windows.ps1
```

Verify:

```powershell
py verify_integrity.py
```

Strict mode:

```powershell
py start.py --strict-integrity
```

## 🪟 Windows CMD / Terminal

```bat
cd live-server
run_windows.bat
```

First-time setup:

```bat
setup_windows.bat
```

Direct launcher:

```bat
py start.py
```

# 🧩 Automatic dependency repair

The project creates a local `.venv`, installs the pinned dependencies, verifies imports, and repairs the environment when requirements change.

You normally do **not** need to manually install `httpx`, `fastapi`, `uvicorn`, `websockets`, `watchdog`, `qrcode`, `Pillow`, or `psutil`.

Even this is self-healing:

```bash
python3 app.py
```

Core dependencies:

```text
fastapi
uvicorn
httpx
websockets
watchdog
qrcode[pil]
Pillow
psutil
```

# 🌐 Usage

1. Start VS Code Live Server.
2. Open `http://127.0.0.1:8765`.
3. Test the upstream.
4. Select the correct LAN interface.
5. Click **Start Sharing**.
6. Scan the real QR URL from your phone.

Phone and computer must be on the same LAN/Wi-Fi.

# ⚡ Fast live reload

```text
CSS change   → hot stylesheet refresh when safe
HTML / JS    → automatic page reload
Rapid saves  → debounced/coalesced events
WebSocket    → forwarded to the real upstream
```

Generated folders such as `.git`, `node_modules`, `.venv`, build and cache directories are ignored by default.

# 👥 Sessions

Sessions represent browser contexts, not people. The dashboard supports:

- Active
- Idle
- Revoked
- Restored / Unrevoked
- Revoke all
- Restore all

Revoking a session invalidates it and closes tracked preview connections. Restore clears the revoked state so the browser can pair again while sharing is active.

# 🔐 Security model

- Dashboard is localhost-only by default
- LAN sharing is opt-in
- Upstream targets are restricted to loopback
- No arbitrary filesystem serving
- Management actions use CSRF protection
- Random pairing token
- WebSocket authentication
- Firewall is never disabled automatically
- No root installation requirement
- No cloud account is required for LAN mode

A private LAN URL is never presented as an internet URL.

# 🧾 Release integrity

`integrity.json` contains SHA-256 hashes for protected runtime files.

Check:

```bash
python verify_integrity.py
```

Strict start:

```bash
python start.py --strict-integrity
```

Normal mode shows a warning when protected files differ. Strict mode refuses to start.

> This is **tamper evidence**, not access control. A person who owns a clone can always edit their own copy.

# 🛡️ GitHub repository protection

The official repository should be protected at the GitHub level rather than by destructive self-delete scripts.

Recommended settings for `main`:

- Require pull requests before merge
- Require code-owner approval
- Require CI status checks
- Block force pushes
- Block branch deletion
- Require conversation resolution
- Apply protections to administrators where available
- Restrict who can push to the protected branch where supported

This project includes:

```text
.github/CODEOWNERS
.github/workflows/ci.yml
.github/workflows/integrity.yml
.github/dependabot.yml
.github/PULL_REQUEST_TEMPLATE.md
.github/ISSUE_TEMPLATE/bug_report.md
REPOSITORY_SECURITY.md
```

GitHub's current protected-branch and code-owner controls are designed for this kind of official-repository protection. See:

- https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches
- https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners

# 🧪 Tests

```bash
python -m unittest discover -s tests -v
```

CI covers Linux and Windows across Python 3.11–3.14.

# 🗂️ Structure

```text
live-server/
├── app.py
├── config.py
├── launcher.py
├── start.py
├── install.py
├── verify_integrity.py
├── integrity.json
├── requirements.txt
├── README.md
├── LICENSE
├── SECURITY.md
├── CONTRIBUTING.md
├── REPOSITORY_SECURITY.md
├── CHANGELOG.md
├── backend/
├── frontend/
├── tests/
└── .github/
```

# 🧭 Troubleshooting

### `ModuleNotFoundError: No module named 'httpx'`

Use:

```bash
python3 start.py
```

or:

```bash
python3 app.py
```

The project repairs the isolated environment automatically.

### Sharing port is busy

The preview listener searches for a nearby free port automatically.

### VS Code is not on port 5500

Use **Discover local servers** in Settings or enter the upstream port manually.

### Phone cannot connect

Check the selected LAN interface, same Wi-Fi, firewall policy and AP/client isolation. Do not disable the firewall globally.

### Corrupt instance lock

Linux:

```bash
rm -f ~/.cache/live-server.lock
```

Windows PowerShell:

```powershell
Remove-Item -Force "$env:USERPROFILE\.cache\live-server.lock" -ErrorAction SilentlyContinue
```

# 🏢 Project identity

**Live Server**  
**JNR Corporations**  
**Developer:** Raj Verma  
**Release:** `2.1.0`
