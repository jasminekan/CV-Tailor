"""Launcher identity and lifecycle checks with fake processes and no network."""

from contextlib import nullcontext
import http.client
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import time

import pytest


LAUNCHER = Path(__file__).resolve().parents[1] / "JobMatch.command"
PROBE = LAUNCHER.read_text().split("<<'PY'\n", 1)[1].split("\nPY\n", 1)[0]


@pytest.mark.parametrize("case,expected", [
    ("jobmatch", 0), ("free", 1), ("unreachable", 2), ("generic_health", 2),
    ("missing_route", 2), ("redirect", 2), ("malformed", 2), ("foreign_page", 2),
])
def test_probe_requires_jobmatch_identity_without_redirects_or_data_access(monkeypatch, case, expected):
    paths = {path: {method: {} for method in methods} for path, methods in {
        "/analyse": ["post"], "/match": ["post"], "/tailoring/preview": ["post"],
        "/experience-bank": ["get", "put"], "/current-cv": ["get", "put"],
    }.items()}
    schema = {"info": {"title": "CV Tailor API"}, "paths": paths}
    if case == "generic_health":
        schema["info"]["title"] = "Another application"
    if case == "missing_route":
        del paths["/tailoring/preview"]
    responses = {
        "/health": (200, b'{"status":"ok"}'),
        "/openapi.json": (200, json.dumps(schema).encode()),
        "/": (200, b"<title>JobMatch CV Tailor</title>"),
    }
    if case == "redirect":
        responses["/health"] = (302, b"")
    if case == "malformed":
        responses["/openapi.json"] = (200, b"not JSON")
    if case == "foreign_page":
        responses["/"] = (200, b"Unrelated service")
    requests = []

    def connect(address, timeout):
        assert address == ("127.0.0.1", 8000)
        if case == "free":
            raise ConnectionRefusedError
        if case == "unreachable":
            raise TimeoutError
        return nullcontext()

    class Connection:
        def __init__(self, host, port, timeout):
            assert (host, port) == ("127.0.0.1", 8000)

        def request(self, method, path):
            assert method == "GET" and path in responses
            requests.append(path)
            self.status, self.body = responses[path]

        def getresponse(self):
            return self

        def read(self, limit):
            assert limit == 1_000_001
            return self.body

        def close(self):
            pass

    monkeypatch.setattr(socket, "create_connection", connect)
    monkeypatch.setattr(http.client, "HTTPConnection", Connection)
    try:
        exec(compile(PROBE, str(LAUNCHER), "exec"), {})
    except SystemExit as error:
        result = error.code
    else:
        result = 0
    assert result == expected
    assert set(requests) <= {"/health", "/openapi.json", "/"}


@pytest.fixture
def project(tmp_path):
    if os.name != "posix" or not Path("/bin/bash").is_file():
        pytest.skip("Launcher requires a POSIX shell.")
    root = tmp_path / "Project with spaces"
    root.mkdir()
    shutil.copy2(LAUNCHER, root / LAUNCHER.name)
    binary = root / ".venv/bin"
    binary.mkdir(parents=True)
    python = binary / "python"
    python.write_text("""#!/bin/bash
case "$1" in
    -c)
        if [ "$JOBMATCH_TEST_MODE" = dependencies ]; then
            echo 'FAKE_SECRET_MUST_NOT_BE_PRINTED' >&2
            exit 1
        fi
        exit 0 ;;
    -)
        cat >/dev/null
        case "$JOBMATCH_TEST_MODE" in
            existing) exit 0 ;;
            foreign) exit 2 ;;
            running) [ -e "$JOBMATCH_TEST_DIR/server.started" ]; exit $? ;;
            *) exit 1 ;;
        esac ;;
    -m)
        printf '%s\\n' "$PWD" "$@" > "$JOBMATCH_TEST_DIR/server.arguments"
        [ "$JOBMATCH_TEST_MODE" = failed ] && exit 1
        trap 'echo stopped > "$JOBMATCH_TEST_DIR/server.stopped"; exit 0' TERM INT
        touch "$JOBMATCH_TEST_DIR/server.started"
        while :; do sleep 0.1; done ;;
esac
""")
    python.chmod(0o755)
    browser = binary / "open"
    browser.write_text('#!/bin/bash\nprintf "%s\\n" "$@" >> "$JOBMATCH_TEST_DIR/browser.opened"\n')
    browser.chmod(0o755)
    env = os.environ.copy()
    env.update(PATH=f"{binary}{os.pathsep}{env.get('PATH', '')}",
               JOBMATCH_TEST_DIR=str(root), JOBMATCH_TEST_MODE="running")
    return root, env


@pytest.mark.parametrize("mode,expected", [("existing", 0), ("foreign", 1), ("dependencies", 1), ("failed", 1)])
def test_existing_instance_and_startup_failures(project, mode, expected):
    root, env = project
    env["JOBMATCH_TEST_MODE"] = mode
    result = subprocess.run([str(root / LAUNCHER.name)], cwd=root.parent, env=env,
                            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=8)
    assert result.returncode == expected
    assert (root / "browser.opened").exists() == (mode == "existing")
    assert (root / "server.arguments").exists() == (mode == "failed")
    assert not (root / "server.stopped").exists()
    assert "FAKE_SECRET_MUST_NOT_BE_PRINTED" not in result.stdout + result.stderr
    if mode == "existing":
        assert "original Terminal window" in result.stdout
    if mode == "foreign":
        assert "Port 8000" in result.stderr
    if mode == "dependencies":
        assert "pip install -r requirements.txt" in result.stderr


def test_missing_virtual_environment_has_setup_guidance(project):
    root, env = project
    (root / ".venv/bin/python").unlink()
    result = subprocess.run([str(root / LAUNCHER.name)], env=env, stdin=subprocess.DEVNULL,
                            capture_output=True, text=True, timeout=5)
    assert result.returncode == 1
    assert "README.md" in result.stderr and ".venv" in result.stderr
    assert not (root / "browser.opened").exists()


def test_startup_timeout_stops_the_owned_server_without_opening_browser(project):
    root, env = project
    env["JOBMATCH_TEST_MODE"] = "waiting"
    result = subprocess.run([str(root / LAUNCHER.name)], env=env, stdin=subprocess.DEVNULL,
                            capture_output=True, text=True, timeout=26)
    assert result.returncode == 1
    assert "did not become ready" in result.stderr
    assert (root / "server.stopped").read_text().strip() == "stopped"
    assert not (root / "browser.opened").exists()


@pytest.mark.parametrize("stop_signal", [signal.SIGINT, signal.SIGTERM])
def test_launcher_uses_own_directory_and_stops_only_its_server(project, stop_signal):
    root, env = project
    launcher = subprocess.Popen([str(root / LAUNCHER.name)], cwd=root.parent, env=env,
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, start_new_session=True)
    try:
        deadline = time.monotonic() + 5
        while not (root / "browser.opened").exists() and time.monotonic() < deadline:
            assert launcher.poll() is None
            time.sleep(0.05)
        assert (root / "browser.opened").read_text().splitlines() == ["http://127.0.0.1:8000/"]
        assert launcher.poll() is None
        assert (root / "server.arguments").read_text().splitlines() == [
            str(root), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000",
        ]
        launcher.send_signal(stop_signal)
        stdout, stderr = launcher.communicate(timeout=5)
        assert launcher.returncode == 0, stdout + stderr
        assert (root / "server.stopped").read_text().strip() == "stopped"
    finally:
        if launcher.poll() is None:
            os.killpg(launcher.pid, signal.SIGKILL)
            launcher.communicate(timeout=5)
