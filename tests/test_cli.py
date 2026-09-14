from contextlib import nullcontext

import pytest

from transfercar import cli


@pytest.mark.parametrize(
    "args,expected",
    [
        ([], {}),
        (["--pickup", "custom:queenstown"], {"pickup": "custom:queenstown"}),
        (["--dropoff", "custom:auckland"], {"dropoff": "custom:auckland"}),
        (
            ["--pickup", "custom:queenstown", "--dropoff", "custom:auckland"],
            {"pickup": "custom:queenstown", "dropoff": "custom:auckland"},
        ),
    ],
)
def test_collection_scope_reaches_http_fetcher_without_default_city(monkeypatch, args, expected):
    received = []
    monkeypatch.setattr("sys.argv", ["transfercar", "collect", *args])
    monkeypatch.setattr(cli.db, "connect", lambda: nullcontext(object()))

    def fake_collect(conn, fetch, scope, **kwargs):
        assert fetch.scope == scope
        received.append({k: v for k, v in scope.items() if k in ("pickup", "dropoff")})
        return {"status": "test_no_network"}

    monkeypatch.setattr(cli, "collect", fake_collect)
    cli.main()
    assert received == [expected]
