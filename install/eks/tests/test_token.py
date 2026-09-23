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
SECRET_PARAM = "/k8s/common/argocd-server-secret"
TOKEN_PARAM = "/k8s/common/mcp-argocd/argocd-api-token"
TOKENS_PARAM = "/k8s/common/argocd-mcp-tokens"
SECRET = "existing-fixture-secret"

AWS = r'''
import json
import os
from pathlib import Path
import sys

args = sys.argv[1:]
root = Path(os.environ["FIXTURE_ROOT"])
state_path = root / "ssm.json"
state = json.loads(state_path.read_text())
parameter = args[args.index("--name") + 1]
operation = args[1]
with (root / "calls.jsonl").open("a") as stream:
    stream.write(json.dumps([operation, parameter, "--overwrite" in args]) + "\n")

if operation == "get-parameter":
    if parameter == os.environ.get("DENY_PARAMETER"):
        print("An error occurred (AccessDeniedException) when calling the GetParameter operation: denied", file=sys.stderr)
        sys.exit(254)
    if parameter not in state:
        print("An error occurred (ParameterNotFound) when calling the GetParameter operation: missing", file=sys.stderr)
        sys.exit(254)
    print(json.dumps({"Parameter": {"Value": state[parameter]}}))
elif operation == "put-parameter":
    if os.environ.get("KEY_RACE") and parameter.endswith("/argocd-server-secret"):
        state[parameter] = "concurrent-fixture-secret"
        state_path.write_text(json.dumps(state))
    if parameter in state and "--overwrite" not in args:
        print("An error occurred (ParameterAlreadyExists) when calling the PutParameter operation: already exists", file=sys.stderr)
        sys.exit(254)
    state[parameter] = args[args.index("--value") + 1]
    state_path.write_text(json.dumps(state))
    print('{"Version": 1}')
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
        SECRET_PARAM: SECRET,
        TOKEN_PARAM: f"{message}.{signature}",
        TOKENS_PARAM: json.dumps([{"id": "fixture-id", "iat": issued_at}]),
    }


def run_token(tmp_path, state, *args, **settings):
    state_path = tmp_path / "ssm.json"
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


@pytest.mark.parametrize("parameter", [SECRET_PARAM, TOKEN_PARAM, TOKENS_PARAM])
def test_ssm_error_never_changes_existing_parameters(tmp_path, parameter):
    before = valid_state()
    result, after, calls = run_token(tmp_path, before, DENY_PARAMETER=parameter)
    assert result.returncode != 0
    assert after == before
    assert not any(call[0] == "put-parameter" for call in calls)


def test_later_read_error_does_not_create_missing_key(tmp_path):
    result, after, calls = run_token(tmp_path, {}, DENY_PARAMETER=TOKEN_PARAM)
    assert result.returncode != 0
    assert after == {}
    assert not any(call[0] == "put-parameter" for call in calls)


@pytest.mark.parametrize("value", [None, "", 123])
def test_invalid_existing_key_is_not_replaced(tmp_path, value):
    before = {SECRET_PARAM: value}
    result, after, calls = run_token(tmp_path, before)
    assert result.returncode != 0
    assert after == before
    assert not any(call[0] == "put-parameter" for call in calls)


def test_valid_token_is_idempotent(tmp_path):
    before = valid_state()
    result, after, calls = run_token(tmp_path, before)
    assert result.returncode == 0, result.stderr
    assert after == before
    assert not any(call[0] == "put-parameter" for call in calls)


def assert_signed_token(state):
    head, claims, signature = state[TOKEN_PARAM].split(".")
    expected = b64(hmac.new(state[SECRET_PARAM].encode(), f"{head}.{claims}".encode(), hashlib.sha256).digest())
    assert signature == expected
    payload = json.loads(base64.urlsafe_b64decode(claims + "=" * (-len(claims) % 4)))
    assert payload["sub"] == "mcp:apiKey"
    assert payload["iss"] == "argocd"
    assert json.loads(state[TOKENS_PARAM]) == [{"id": payload["jti"], "iat": payload["iat"]}]


def test_missing_parameters_create_key_without_overwrite(tmp_path):
    result, after, calls = run_token(tmp_path, {})
    assert result.returncode == 0, result.stderr
    assert_signed_token(after)
    assert [call for call in calls if call[0] == "put-parameter"] == [
        ["put-parameter", SECRET_PARAM, False],
        ["put-parameter", TOKENS_PARAM, True],
        ["put-parameter", TOKEN_PARAM, True],
    ]


def test_rotate_changes_token_and_preserves_signing_key(tmp_path):
    before = valid_state()
    result, after, calls = run_token(tmp_path, before, "--rotate")
    assert result.returncode == 0, result.stderr
    assert after[SECRET_PARAM] == before[SECRET_PARAM]
    assert after[TOKEN_PARAM] != before[TOKEN_PARAM]
    assert after[TOKENS_PARAM] != before[TOKENS_PARAM]
    assert_signed_token(after)
    assert not any(call[:2] == ["put-parameter", SECRET_PARAM] for call in calls)


def test_concurrent_key_creation_is_not_overwritten(tmp_path):
    result, after, calls = run_token(tmp_path, {}, KEY_RACE="1")
    assert result.returncode != 0
    assert after == {SECRET_PARAM: "concurrent-fixture-secret"}
    assert [call for call in calls if call[0] == "put-parameter"] == [
        ["put-parameter", SECRET_PARAM, False],
    ]
