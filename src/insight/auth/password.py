"""Password hashing with Argon2id.

Argon2id won the Password Hashing Competition and is what OWASP recommends
over bcrypt for new systems: it is memory-hard, so an attacker with GPUs
gains far less than they would against a CPU-bound hash.

Parameters follow the OWASP minimum (19 MiB, 2 iterations, 1 degree of
parallelism). They are recorded inside every hash, so raising them later
does not invalidate existing passwords - `needs_rehash` detects the old
ones and they are upgraded transparently at next sign-in.
"""

from __future__ import annotations

from contextlib import suppress

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

# OWASP Password Storage Cheat Sheet, Argon2id minimum.
_hasher = PasswordHasher(
    time_cost=2,
    memory_cost=19_456,  # KiB == 19 MiB
    parallelism=1,
    hash_len=32,
    salt_len=16,
)

# Verifying against this when the account does not exist keeps the response
# time for "unknown email" and "wrong password" roughly equal. Without it,
# an unknown email returns in microseconds and a known one takes ~50ms -
# which is a reliable account-enumeration oracle.
_DUMMY_HASH = _hasher.hash("dummy-password-for-constant-time-comparison")


def hash_password(password: str) -> str:
    """Hash a plaintext password. The salt and parameters live in the output."""
    if not password:
        raise ValueError("password must not be empty")
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    """Check a password against a stored hash.

    Returns False rather than raising for every failure mode, including a
    missing hash (an SSO-only user) and a corrupt one. Callers get a boolean
    and cannot accidentally treat an exception as success.

    A None hash still burns a verification against the dummy, so SSO-only
    accounts are not distinguishable by response time either.
    """
    if password_hash is None:
        verify_dummy()
        return False
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def verify_dummy() -> None:
    """Spend the same work as a real verification, and discard the result.

    Call this on the no-such-user path so timing does not reveal whether an
    email is registered.
    """
    with suppress(VerifyMismatchError, VerificationError, InvalidHashError):
        _hasher.verify(_DUMMY_HASH, "not-the-password")


def needs_rehash(password_hash: str) -> bool:
    """True when the hash was made with weaker parameters than current.

    Checked after a successful sign-in: it is the only moment the plaintext
    is available to re-hash with.
    """
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True
