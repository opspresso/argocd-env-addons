import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "token.sh"
SECRET_NAME = "/k8s/common/argocd-server-secret"
TOKEN_NAME = "/k8s/common/mcp-argocd/argocd-api-token"
TOKENS_NAME = "/k8s/common/argocd-mcp-tokens"
SECRET = "existing-fixture-secret"

# Fake aws keeps Secrets Manager in a JSON file. A value of None stands for a
# secret without SecretString (a binary secret).
AWS = r'''
import json
import os
from pathlib import Path
import sys

args = sys.argv[1:]
root = Path(os.environ["FIXTURE_ROOT"])
state_path = root / "secrets.json"
state = json.loads(state_path.read_text())
operation = args[1]
name = args[args.index("--name" if operation == "create-secret" else "--secret-id") + 1]
with (root / "calls.jsonl").open("a") as stream:
    stream.write(json.dumps([operation, name]) + "\n")


def fail(code, action):
    print(f"An error occurred ({code}) when calling the {action} operation: fixture", file=sys.stderr)
    sys.exit(254)


action = {
    "describe-secret": "DescribeSecret", "get-secret-value": "GetSecretValue",
    "create-secret": "CreateSecret", "put-secret-value": "PutSecretValue",
}[operation]
if operation in ("describe-secret", "get-secret-value") and name == os.environ.get("DENY_SECRET"):
    fail("AccessDeniedException", action)
if operation == "describe-secret" and name == os.environ.get("DENY_DESCRIBE"):
    fail("AccessDeniedException", action)
if operation == "create-secret" and os.environ.get("KEY_RACE") and name.endswith("/argocd-server-secret"):
    state[name] = "concurrent-fixture-secret"
    state_path.write_text(json.dumps(state))
if operation == "create-secret":
    if name in state:
        fail("ResourceExistsException", action)
elif name not in state:
    fail("ResourceNotFoundException", action)

if operation == "describe-secret":
    print(json.dumps({"Name": name}))
elif operation == "get-secret-value":
    response = {"Name": name, "VersionId": "v1"}
    if state[name] is not None:
        response["SecretString"] = state[name]
    print(json.dumps(response))
else:
    state[name] = args[args.index("--secret-string") + 1]
    state_path.write_text(json.dumps(state))
    print(json.dumps({"Name": name, "VersionId": f"v-{len(state[name])}"}))
'''


def b64(value):
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def valid_state():
    issued_at = int(time.time())
    head = b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    claims = b64(json.dumps({
        "iss": "argocd", "sub": "mcp:apiKey", "jti": "fixture-id", "iat": issued_at, "nbf": issued_at,
    }).encode())
    message = f"{head}.{claims}"
    signature = b64(hmac.new(SECRET.encode(), message.encode(), hashlib.sha256).digest())
    return {
        SECRET_NAME: SECRET,
        TOKEN_NAME: f"{message}.{signature}",
        TOKENS_NAME: json.dumps([{"id": "fixture-id", "iat": issued_at}]),
    }


def run_token(tmp_path, state, *args, **settings):
    state_path = tmp_path / "secrets.json"
    state_path.write_text(json.dumps(state))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    command = bin_dir / "aws"
    command.write_text(f"#!{sys.executable}\n{AWS}")
    command.chmod(0o755)
    result = subprocess.run(
        ["bash", str(SCRIPT), *args],
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "FIXTURE_ROOT": str(tmp_path),
            **settings,
        },
        capture_output=True, text=True, timeout=15,
    )
    assert SECRET not in result.stdout + result.stderr
    calls = [json.loads(line) for line in (tmp_path / "calls.jsonl").read_text().splitlines()]
    return result, json.loads(state_path.read_text()), calls


@pytest.mark.parametrize("name", [SECRET_NAME, TOKEN_NAME, TOKENS_NAME])
def test_read_error_never_changes_existing_secrets(tmp_path, name):
    before = valid_state()
    result, after, calls = run_token(tmp_path, before, DENY_SECRET=name)
    assert result.returncode != 0
    assert "Secrets Manager 조회 실패" in result.stderr
    assert after == before
    assert writes(calls) == []


def test_later_read_error_does_not_create_missing_key(tmp_path):
    result, after, calls = run_token(tmp_path, {}, DENY_SECRET=TOKEN_NAME)
    assert result.returncode != 0
    assert after == {}
    assert writes(calls) == []


@pytest.mark.parametrize("value", [None, "", 123])
def test_invalid_existing_key_is_not_replaced(tmp_path, value):
    before = {SECRET_NAME: value}
    result, after, calls = run_token(tmp_path, before)
    assert result.returncode != 0
    assert after == before
    assert writes(calls) == []


def test_valid_token_is_idempotent(tmp_path):
    before = valid_state()
    result, after, calls = run_token(tmp_path, before)
    assert result.returncode == 0, result.stderr
    assert after == before
    assert writes(calls) == []


WRITES = {"create-secret", "put-secret-value"}


def writes(calls):
    return [call for call in calls if call[0] in WRITES]


def assert_signed_token(state):
    head, claims, signature = state[TOKEN_NAME].split(".")
    expected = b64(hmac.new(state[SECRET_NAME].encode(), f"{head}.{claims}".encode(), hashlib.sha256).digest())
    assert signature == expected
    payload = json.loads(base64.urlsafe_b64decode(claims + "=" * (-len(claims) % 4)))
    assert payload["sub"] == "mcp:apiKey"
    assert payload["iss"] == "argocd"
    assert json.loads(state[TOKENS_NAME]) == [{"id": payload["jti"], "iat": payload["iat"]}]


def test_missing_secrets_create_key_without_overwrite(tmp_path):
    result, after, calls = run_token(tmp_path, {})
    assert result.returncode == 0, result.stderr
    assert_signed_token(after)
    assert writes(calls) == [
        ["create-secret", SECRET_NAME],
        ["create-secret", TOKENS_NAME],
        ["create-secret", TOKEN_NAME],
    ]


def test_rotate_changes_token_and_preserves_signing_key(tmp_path):
    before = valid_state()
    result, after, calls = run_token(tmp_path, before, "--rotate")
    assert result.returncode == 0, result.stderr
    assert after[SECRET_NAME] == before[SECRET_NAME]
    assert after[TOKEN_NAME] != before[TOKEN_NAME]
    assert after[TOKENS_NAME] != before[TOKENS_NAME]
    assert_signed_token(after)
    assert writes(calls) == [
        ["put-secret-value", TOKENS_NAME],
        ["put-secret-value", TOKEN_NAME],
    ]


def test_describe_error_before_overwrite_stops_without_writing(tmp_path):
    before = valid_state()
    result, after, calls = run_token(tmp_path, before, "--rotate", DENY_DESCRIBE=TOKENS_NAME)
    assert result.returncode != 0
    assert "Secrets Manager 조회 실패" in result.stderr
    assert after == before
    assert writes(calls) == []


def test_concurrent_key_creation_is_not_overwritten(tmp_path):
    result, after, calls = run_token(tmp_path, {}, KEY_RACE="1")
    assert result.returncode != 0
    assert after == {SECRET_NAME: "concurrent-fixture-secret"}
    assert writes(calls) == [["create-secret", SECRET_NAME]]


def test_keep_account_signs_its_own_token_and_reuses_the_signing_key(tmp_path):
    before = valid_state()
    result, after, calls = run_token(tmp_path, before, "--account", "keep")
    assert result.returncode == 0, result.stderr
    for name in (SECRET_NAME, TOKEN_NAME, TOKENS_NAME):
        assert after[name] == before[name]
    head, claims, signature = after["/k8s/common/keep/argocd-api-token"].split(".")
    assert signature == b64(hmac.new(SECRET.encode(), f"{head}.{claims}".encode(), hashlib.sha256).digest())
    payload = json.loads(base64.urlsafe_b64decode(claims + "=" * (-len(claims) % 4)))
    assert payload["sub"] == "keep:apiKey"
    assert json.loads(after["/k8s/common/argocd-keep-tokens"]) == [{"id": payload["jti"], "iat": payload["iat"]}]
    assert writes(calls) == [
        ["create-secret", "/k8s/common/argocd-keep-tokens"],
        ["create-secret", "/k8s/common/keep/argocd-api-token"],
    ]


def test_unknown_account_is_rejected_before_any_aws_call(tmp_path):
    (tmp_path / "calls.jsonl").write_text("")
    result, after, calls = run_token(tmp_path, {}, "--account", "admin")
    assert result.returncode == 2
    assert after == {} and calls == []
