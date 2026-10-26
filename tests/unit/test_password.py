"""Argon2id password hashing."""

from __future__ import annotations

import pytest
from argon2 import PasswordHasher

from insight.auth.password import (
    hash_password,
    needs_rehash,
    verify_dummy,
    verify_password,
)

PASSWORD = "correct horse battery staple"


class TestHashing:
    def test_hash_is_argon2id(self) -> None:
        assert hash_password(PASSWORD).startswith("$argon2id$")

    def test_hash_does_not_contain_the_password(self) -> None:
        assert PASSWORD not in hash_password(PASSWORD)

    def test_same_password_hashes_differently(self) -> None:
        """Random salt per hash; identical passwords must not collide."""
        assert hash_password(PASSWORD) != hash_password(PASSWORD)

    def test_empty_password_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="must not be empty"):
            hash_password("")

    def test_parameters_meet_the_owasp_minimum(self) -> None:
        encoded = hash_password(PASSWORD)
        assert "m=19456" in encoded
        assert "t=2" in encoded
        assert "p=1" in encoded


class TestVerification:
    def test_correct_password_verifies(self) -> None:
        assert verify_password(PASSWORD, hash_password(PASSWORD)) is True

    def test_wrong_password_fails(self) -> None:
        assert verify_password("wrong", hash_password(PASSWORD)) is False

    def test_verification_is_case_sensitive(self) -> None:
        assert verify_password(PASSWORD.upper(), hash_password(PASSWORD)) is False

    def test_none_hash_returns_false(self) -> None:
        """SSO-only users have no local password; this must not raise."""
        assert verify_password(PASSWORD, None) is False

    @pytest.mark.parametrize(
        "bad_hash", ["", "not-a-hash", "$argon2id$garbage", "$2b$12$bcrypt-shaped"]
    )
    def test_malformed_hash_returns_false_rather_than_raising(self, bad_hash: str) -> None:
        """A caller must never be able to mistake an exception for success."""
        assert verify_password(PASSWORD, bad_hash) is False

    def test_verify_dummy_does_not_raise(self) -> None:
        """Called on the no-such-user path, where it must never blow up."""
        verify_dummy()


class TestRehashing:
    def test_current_parameters_do_not_need_rehashing(self) -> None:
        assert needs_rehash(hash_password(PASSWORD)) is False

    def test_weaker_parameters_need_rehashing(self) -> None:
        weak = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1).hash(PASSWORD)
        assert needs_rehash(weak) is True

    def test_malformed_hash_is_treated_as_needing_rehash(self) -> None:
        assert needs_rehash("not-a-hash") is True

    def test_an_upgraded_hash_still_verifies_the_same_password(self) -> None:
        weak = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1).hash(PASSWORD)
        assert verify_password(PASSWORD, weak) is True
        upgraded = hash_password(PASSWORD)
        assert verify_password(PASSWORD, upgraded) is True
        assert needs_rehash(upgraded) is False
