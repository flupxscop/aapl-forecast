#!/usr/bin/env bash
# Copy this project from your Mac to the server and (re)deploy it.
#   ./deploy/upload-from-mac.sh ~/Downloads/stock-forecast-key.pem 13.250.10.20
set -euo pipefail

KEY="${1:?Usage: $0 <path-to-key.pem> <server-public-ip>}"
HOST="${2:?Usage: $0 <path-to-key.pem> <server-public-ip>}"
USER_NAME="${SSH_USER:-ubuntu}"
REMOTE_DIR="stock-forecast"
cd "$(dirname "${BASH_SOURCE[0]}")/.."

chmod 400 "$KEY"
SSH=(ssh -i "$KEY" -o StrictHostKeyChecking=accept-new)

echo "==> Uploading code to $USER_NAME@$HOST:~/$REMOTE_DIR"
rsync -az --delete \
  --exclude '.git' --exclude 'node_modules' --exclude '.next' --exclude 'bin' --exclude 'obj' \
  --exclude '__pycache__' --exclude '.venv' --exclude 'data' --exclude '.env' --exclude '*.zip' \
  -e "${SSH[*]}" ./ "$USER_NAME@$HOST:$REMOTE_DIR/"

# Kaggle token (optional): copied once so the server can download the datasets
if [[ -f "$HOME/.kaggle/kaggle.json" ]]; then
  "${SSH[@]}" "$USER_NAME@$HOST" 'mkdir -p ~/.kaggle && chmod 700 ~/.kaggle'
  scp -i "$KEY" -q "$HOME/.kaggle/kaggle.json" "$USER_NAME@$HOST:.kaggle/kaggle.json"
  "${SSH[@]}" "$USER_NAME@$HOST" 'chmod 600 ~/.kaggle/kaggle.json'
fi

echo "==> Running the installer on the server"
"${SSH[@]}" -t "$USER_NAME@$HOST" "cd $REMOTE_DIR && bash deploy/setup-server.sh"
