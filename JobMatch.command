#!/bin/bash
# Finder opens .command files in Terminal; keep this window for server shutdown.
set -u

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)" || exit 1
cd "$PROJECT_DIR" || exit 1
PYTHON="$PROJECT_DIR/.venv/bin/python"
URL="http://127.0.0.1:8000/"
server_pid=""

stop_server() {
    if [ -n "$server_pid" ]; then
        kill -TERM "$server_pid" 2>/dev/null || true
        wait "$server_pid" 2>/dev/null || true
        server_pid=""
    fi
}

fail() {
    stop_server
    printf '\nJobMatch: %s\n' "$1" >&2
    if [ -t 0 ]; then
        read -r -p "Press Return to close this window. " reply
    fi
    exit 1
}

[ -x "$PYTHON" ] || fail "The .venv Python environment is missing. Follow the initial setup in README.md."
"$PYTHON" -c 'import fastapi, uvicorn, openai, pydantic, pydantic_settings' >/dev/null 2>&1 ||
    fail "Dependencies are missing or the virtual environment is broken. Run .venv/bin/python -m pip install -r requirements.txt from this folder."

probe_jobmatch() {
    # Exit 0: JobMatch ready; 1: no listener; 2: occupied or unrecognised service.
    # Direct loopback requests avoid proxies and never follow redirects.
    "$PYTHON" - <<'PY'
import http.client
import json
import socket
import sys

try:
    with socket.create_connection(("127.0.0.1", 8000), timeout=0.5):
        pass
except ConnectionRefusedError:
    sys.exit(1)
except OSError:
    sys.exit(2)

def get(path):
    connection = http.client.HTTPConnection("127.0.0.1", 8000, timeout=0.5)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        body = response.read(1_000_001)
        if response.status != 200 or len(body) > 1_000_000:
            raise ValueError("Unexpected response")
        return body
    finally:
        connection.close()

try:
    if json.loads(get("/health")) != {"status": "ok"}:
        sys.exit(2)
    schema = json.loads(get("/openapi.json"))
    if not isinstance(schema, dict):
        sys.exit(2)
    info, paths = schema.get("info"), schema.get("paths")
    expected = {
        "/analyse": {"post"}, "/match": {"post"},
        "/tailoring/preview": {"post"},
        "/experience-bank": {"get", "put"}, "/current-cv": {"get", "put"},
    }
    if not isinstance(info, dict) or info.get("title") != "CV Tailor API" or not isinstance(paths, dict):
        sys.exit(2)
    if any(not isinstance(paths.get(path), dict) or not methods <= paths[path].keys()
           for path, methods in expected.items()):
        sys.exit(2)
    if b"<title>JobMatch CV Tailor</title>" not in get("/"):
        sys.exit(2)
except (OSError, ValueError, http.client.HTTPException):
    sys.exit(2)
PY
}

open_browser() {
    open "$URL" >/dev/null 2>&1 ||
        printf 'Open %s in your browser. Automatic browser opening was unavailable.\n' "$URL"
}

probe_jobmatch
case $? in
    0)
        printf 'JobMatch is already running. Stop it in its original Terminal window.\n'
        open_browser
        exit 0
        ;;
    1) ;;
    *) fail "Port 8000 is occupied by an unrecognised or unready service. Stop that service or try again when JobMatch is ready. No browser was opened." ;;
esac

trap stop_server EXIT
trap 'exit 0' INT TERM HUP

printf 'Starting JobMatch at %s\nKeep this Terminal window open. Press Control-C here to stop JobMatch.\n' "$URL"
"$PYTHON" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 &
server_pid=$!
ready=false
deadline=$((SECONDS + 20))
while kill -0 "$server_pid" 2>/dev/null && [ "$SECONDS" -lt "$deadline" ]; do
    if probe_jobmatch && kill -0 "$server_pid" 2>/dev/null; then
        ready=true
        break
    fi
    sleep 0.2
done

if [ "$ready" != true ]; then
    fail "The server did not become ready. Check the server message above; no browser was opened."
fi

open_browser
wait "$server_pid"
status=$?
server_pid=""
[ "$status" -eq 0 ] || fail "The server stopped unexpectedly. Check the server message above."
printf 'JobMatch stopped. You can close this Terminal window.\n'
