"""A mocked S3 for the tests of the S3 store: no network, no real credentials.

Both are skipped when boto3 or moto is not installed, which is the case
for `pip install chartbook` without the `s3` extra; the test environments
install them (pyproject.toml, `[tool.hatch.envs.hatch-test]`).
"""

import contextlib

import pytest

BUCKET = "chartbook-test"
URL = f"s3://{BUCKET}/stores/one"


@contextlib.contextmanager
def mocked_s3(monkeypatch):
    """A mocked AWS with one bucket, and credentials that reach nothing real.

    Yields a boto3 client for the bucket. Inside, ``boto3.client("s3")``
    made anywhere in the process, as the store makes its own, talks to the
    same mock.
    """
    boto3 = pytest.importorskip("boto3")
    moto = pytest.importorskip("moto")
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SECURITY_TOKEN", "AWS_SESSION_TOKEN"):
        monkeypatch.setenv(name, "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    monkeypatch.delenv("AWS_ENDPOINT_URL", raising=False)
    with moto.mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=BUCKET)
        yield client
