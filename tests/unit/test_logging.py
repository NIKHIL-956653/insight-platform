"""Log redaction.

The point of these tests is the safety net: someone will eventually log a
dict that happens to contain a credential, and it must not reach disk.
"""

from __future__ import annotations

from typing import Any

import pytest

from insight.logging import REDACTED, configure_logging, redact_sensitive


def process(**event: Any) -> dict[str, Any]:
    return dict(redact_sensitive(None, "info", dict(event)))


class TestTopLevelRedaction:
    @pytest.mark.parametrize(
        "key",
        [
            "password",
            "db_password",
            "jwt_secret",
            "secret_key",
            "api_key",
            "apikey",
            "access_token",
            "refresh_token",
            "authorization",
            "spicedb_preshared_key",
            "cookie",
            "credential",
        ],
    )
    def test_sensitive_keys_are_redacted(self, key: str) -> None:
        assert process(**{key: "hunter2"})[key] == REDACTED

    def test_case_is_ignored(self) -> None:
        assert process(PASSWORD="hunter2")["PASSWORD"] == REDACTED

    def test_ordinary_keys_survive(self) -> None:
        out = process(event="login", user_id=7, workspace="acme")
        assert out == {"event": "login", "user_id": 7, "workspace": "acme"}


class TestNestedRedaction:
    def test_nested_dict(self) -> None:
        out = process(config={"host": "db", "password": "hunter2"})
        assert out["config"] == {"host": "db", "password": REDACTED}

    def test_list_of_dicts(self) -> None:
        out = process(items=[{"api_key": "k1"}, {"name": "ok"}])
        assert out["items"] == [{"api_key": REDACTED}, {"name": "ok"}]

    def test_deeply_nested(self) -> None:
        out = process(a={"b": {"token": "t"}})
        assert out["a"]["b"]["token"] == REDACTED

    def test_tuple_type_is_preserved(self) -> None:
        out = process(pair=({"secret": "s"}, {"ok": 1}))
        assert isinstance(out["pair"], tuple)
        assert out["pair"][0] == {"secret": REDACTED}

    def test_scalars_pass_through(self) -> None:
        out = process(count=3, ratio=0.5, flag=True, nothing=None)
        assert out == {"count": 3, "ratio": 0.5, "flag": True, "nothing": None}


class TestConfigureLogging:
    def test_json_mode_configures_without_error(self) -> None:
        configure_logging(level="DEBUG", json_logs=True)

    def test_console_mode_configures_without_error(self) -> None:
        configure_logging(level="INFO", json_logs=False)

    def test_unknown_level_falls_back_to_info(self) -> None:
        configure_logging(level="NOT_A_LEVEL", json_logs=False)
