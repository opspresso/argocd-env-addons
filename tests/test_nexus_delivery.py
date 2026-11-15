import json
import os
from pathlib import Path
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit


ROOT = Path(__file__).resolve().parents[1]


def exercise(fail=False):
    state = {"security/users/anonymous": {"userId": "anonymous", "roles": ["nx-anonymous"], "status": "active"}}
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def handle_request(self):
            url = urlsplit(self.path)
            path = url.path.removeprefix("/v1/")
            data = json.loads(self.rfile.read(int(self.headers["Content-Length"]))) if self.headers.get("Content-Length") else None
            calls.append((self.command, path, data))
            status, result = 200, {}
            if fail and path == "security/roles/public-packages":
                status = 503
            elif self.command == "GET":
                if path == "repositories":
                    result = [{"name": "maven-releases", "format": "maven2"}] + [
                        {"name": value["name"], "format": key.split("/")[1]}
                        for key, value in state.items() if key.startswith("repositories/")]
                elif path == "security/users":
                    user = parse_qs(url.query)["userId"][0]
                    result = [state["security/users/" + user]] if "security/users/" + user in state else []
                elif path in state:
                    result = state[path]
                else:
                    status = 404
            elif self.command == "POST":
                key = data.get("userId", data.get("id", data.get("name")))
                state[path + "/" + key] = data
                status = 201
            elif self.command == "PUT":
                state[path] = data
            self.send_response(status)
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())

        do_GET = do_POST = do_PUT = handle_request

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    env = {**os.environ, "NEXUS_ADMIN_PASSWORD": "test-admin", "NEXUS_PUBLISHER_PASSWORD": "test-publisher",
           "NEXUS_READER_PASSWORD": "test-reader", "NEXUS_CLEANER_PASSWORD": "test-cleaner", "NEXUS_PUBLIC_REPOSITORIES": '["maven-releases"]',
           "B": f"http://127.0.0.1:{server.server_port}"}
    command = 'api() { curl -fsS -H "Content-Type: application/json" "$@"; }; . "$1"'
    try:
        first = subprocess.run(["bash", "-c", command, "bash", str(ROOT / "charts/nexus/delivery.sh")], env=env, capture_output=True, text=True)
        if not fail:
            assert first.returncode == 0, first.stderr
            created = len([c for c in calls if c[0] == "POST"])
            # Reconcile unexpected access on a managed account without resetting its password.
            state["security/users/runway-reader"]["roles"].append("nx-admin")
            second = subprocess.run(["bash", "-c", command, "bash", str(ROOT / "charts/nexus/delivery.sh")], env=env, capture_output=True, text=True)
            assert second.returncode == 0, second.stderr
            assert len([c for c in calls if c[0] == "POST"]) == created
        return first, state, calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_private_repositories_and_scoped_credentials_are_repeatable():
    result, state, calls = exercise()
    assert state["security/users/anonymous"]["roles"] == ["public-packages"]
    assert state["security/roles/public-packages"]["privileges"] == [
        "nx-repository-view-maven2-maven-releases-read", "nx-repository-view-maven2-maven-releases-browse"]
    assert state["security/users/runway-reader"]["roles"] == ["runway-reader"]
    reader = state["security/roles/runway-reader"]["privileges"]
    assert len(reader) == 4 and all(p.endswith(("-read", "-browse")) for p in reader)
    publisher = state["security/roles/runway-publisher"]["privileges"]
    assert len(publisher) == 8 and not any(p.endswith("-delete") for p in publisher)
    cleaner = state["security/roles/runway-cleaner"]["privileges"]
    assert len(cleaner) == 6 and all(p.endswith(("-read", "-browse", "-delete")) for p in cleaner)
    for kind, name in [("raw", "runway-artifacts"), ("docker", "runway-images")]:
        assert state[f"repositories/{kind}/hosted/{name}"]["storage"]["writePolicy"] == "ALLOW_ONCE"
    anonymous_changed = next(i for i, c in enumerate(calls) if c[:2] == ("PUT", "security/users/anonymous"))
    repository_created = next(i for i, c in enumerate(calls) if c[0] == "POST" and c[1].startswith("repositories/"))
    assert anonymous_changed < repository_created
    assert "test-publisher" not in result.stdout + result.stderr
    assert "test-reader" not in result.stdout + result.stderr


def test_failed_read_is_not_treated_as_missing_and_stops_writes():
    result, _, calls = exercise(fail=True)
    assert result.returncode != 0
    assert "HTTP 503" in result.stderr
    assert all(method == "GET" for method, _, _ in calls)
