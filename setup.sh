#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python3 install.py
mkdir -p "$HOME/.local/share/applications"
cat > "$HOME/.local/share/applications/live-server.desktop" <<EOF
[Desktop Entry]
Name=Live Server
Comment=JNR Corporations Live Server — fast secure LAN preview
Exec=$PWD/run.sh
Icon=network-workgroup
Terminal=true
Type=Application
Categories=Development;WebDevelopment;
StartupNotify=true
EOF
echo "[Live Server] Optional Linux desktop launcher installed at $HOME/.local/share/applications/live-server.desktop"
