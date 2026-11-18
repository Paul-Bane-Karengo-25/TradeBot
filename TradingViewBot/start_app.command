#!/bin/bash
# ============================================================
#  TradingView Analysis Bot - start the app in your web browser (Mac)
#  Double-click this file (after running setup_mac.sh once).
#  Keep the Terminal window open while you use the app; close it to stop.
# ============================================================
SELF="$0"
[ -L "$SELF" ] && SELF="$(readlink "$SELF")"   # works from the Desktop shortcut too
cd "$(dirname "$SELF")" || exit 1

if [ ! -x .venv/bin/python ]; then
  echo "First-time setup is needed - this takes a few minutes ..."
  bash setup_mac.sh --no-launch || exit 1
fi
VPY=.venv/bin/python
"$VPY" -c "import streamlit, tradingview_ta" 2>/dev/null || "$VPY" -m pip install --quiet --disable-pip-version-check -r requirements.txt

clear
echo
echo "  ==============================================================="
echo "   TradingView Analysis Bot is starting..."
echo "   Your web browser will open as soon as the app is ready"
echo "   (the first start can take up to a minute)."
echo
echo "   If it doesn't, open your browser and go to:  http://localhost:8501"
echo
echo "   KEEP THIS WINDOW OPEN while you use the app."
echo "   Close this window to stop the app."
echo "  ==============================================================="
echo
# open the browser only once the app answers (checks every second, for up to 90 seconds)
(for i in $(seq 1 90); do curl -fs --noproxy '*' http://127.0.0.1:8501/_stcore/health >/dev/null 2>&1 && break; sleep 1; done
 open "http://localhost:8501") &
"$VPY" -m streamlit run app.py
