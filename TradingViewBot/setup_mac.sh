#!/bin/bash
# ============================================================
#  TradingView Analysis Bot - setup for macOS
#  In Terminal:   bash setup_mac.sh   (or type "bash " and drag this file in)
#  Safe to run again at any time. Installs (only if missing): Python 3.12 and
#  the app's packages, and puts a "TradingView Bot" shortcut on the Desktop.
# ============================================================
set -e
cd "$(dirname "$0")"
echo
echo "=== TradingView Analysis Bot setup (macOS) ==="
echo

py_ok() { "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' >/dev/null 2>&1; }
have() { command -v "$1" >/dev/null 2>&1; }

# Put Homebrew on PATH if it's installed but this shell doesn't know about it
for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do
  if [ -x "$b" ]; then eval "$("$b" shellenv)"; break; fi
done

# ---------- 1. Python 3.9 or newer ----------
PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3 /Library/Frameworks/Python.framework/Versions/Current/bin/python3; do
  if have "$c"; then
    p="$(command -v "$c")"
    # /usr/bin/python3 is only a stub until Apple's command line tools are installed (it would pop up a dialog)
    if [ "$p" = "/usr/bin/python3" ] && ! xcode-select -p >/dev/null 2>&1; then continue; fi
    if py_ok "$p"; then PY="$p"; break; fi
  fi
done

if [ -z "$PY" ]; then
  echo "[1/3] Python not found - installing Python 3.12 ..."
  if have brew; then
    brew install python@3.12
    PY="$(brew --prefix python@3.12)/bin/python3.12"
  else
    echo "      Downloading from python.org (you'll be asked for your Mac password) ..."
    PKG="/tmp/python-3.12.10-macos11.pkg"
    curl -fL --progress-bar -o "$PKG" "https://www.python.org/ftp/python/3.12.10/python-3.12.10-macos11.pkg"
    sudo installer -pkg "$PKG" -target /
    PY="/Library/Frameworks/Python.framework/Versions/3.12/bin/python3"
  fi
fi
py_ok "$PY" || { echo "Python install did not complete. Install Python 3.12 from https://www.python.org/downloads/ and run this again."; exit 1; }
echo "[1/3] Python OK: $PY"

# ---------- 2. Private environment (.venv) with the app's packages ----------
echo "[2/3] Installing the app's packages (this can take a few minutes the first time) ..."
[ -x .venv/bin/python ] || "$PY" -m venv --clear .venv
VPY="$PWD/.venv/bin/python"
"$VPY" -m pip install --upgrade pip --quiet --disable-pip-version-check
"$VPY" -m pip install -r requirements.txt --quiet --disable-pip-version-check
echo "      Packages OK"

# ---------- 3. Make the launchers double-clickable + Desktop shortcut ----------
chmod +x start_app.command run_tests.sh check_track_record.sh setup_mac.sh 2>/dev/null || true
# Files downloaded from the internet (e.g. Google Drive) are flagged by macOS and may refuse to open.
# Clear that flag for this app's own folder only.
xattr -dr com.apple.quarantine "$PWD" 2>/dev/null || true
ln -sf "$PWD/start_app.command" "$HOME/Desktop/TradingView Bot.command" 2>/dev/null \
  && echo "[3/3] Desktop shortcut 'TradingView Bot' created"

echo
echo "=== Setup complete ==="
echo "To use the app, double-click 'TradingView Bot' on your Desktop, or start_app.command in this folder."
echo
if [ "$1" != "--no-launch" ]; then
  open "$PWD/start_app.command"
fi
