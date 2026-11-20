"""A mocked S3 for the tests of the S3 store: no network, no real credentials.

Both are skipped when boto3 or moto is not installed, which is the case
for `pip install chartbook` without the `s3` extra; the test environments
install them (pyproject.toml: the `dev` dependency group, and
`[tool.hatch.envs.hatch-test]`).
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

    A store in a bucket is withdrawn in ChartBook 0.6: a URL that names
    one is refused where it would become a store. The tests of the class,
    which keep its code from rotting until a bucket is brought to this
    version's layout, make the class directly; inside this block a bucket's
    URL makes it too, as it will again then, so that the class is still
    driven by a pin, a snapshot and a read as well as by its own methods.
    The refusal itself is held by ``tests/test_bucket_withdrawn.py``.
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
        from chartbook import multi_store
        from chartbook import store as store_module
        from chartbook.stores.s3 import S3Store

        opened = store_module.store_for_url

        def made_directly(url):
            return S3Store(url) if str(url).startswith("s3://") else opened(url)

        monkeypatch.setattr(store_module, "store_for_url", made_directly)
        monkeypatch.setattr(multi_store, "store_for_url", made_directly)
        yield client
