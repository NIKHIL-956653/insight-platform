"""Request and response bodies for authentication."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from insight.models.membership import WorkspaceRole


class LoginRequest(BaseModel):
    email: EmailStr
    # No max length would let a megabyte of input reach Argon2, which is
    # memory-hard by design - a cheap way to exhaust the server.
    password: str = Field(min_length=1, max_length=1024)

    @field_validator("email")
    @classmethod
    def normalise_email(cls, value: str) -> str:
        """Lowercase to match the database's case-insensitive identity."""
        return value.strip().lower()


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 - the RFC 6750 scheme name
    expires_in: int = Field(description="Seconds until the access token expires.")


class WorkspaceSummary(BaseModel):
    """One workspace the signed-in user can reach, and their role in it."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    role: WorkspaceRole


class CurrentUserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str

    # Drives the portal's workspace switcher. Empty means the account is
    # real but has not been added to anything yet - a valid state, not an
    # error.
    workspaces: list[WorkspaceSummary]
