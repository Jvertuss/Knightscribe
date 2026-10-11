
import hashlib
import secrets

from datetime import datetime, timedelta, timezone
from typing import Annotated

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from pydantic import BaseModel, EmailStr, Field
from psycopg.errors import UniqueViolation

from database import get_connection


# --------------------------------------
# Configuration
# --------------------------------------

router = APIRouter(prefix="/auth", tags=["Authentication"])

password_hasher = PasswordHasher()
bearer_scheme = HTTPBearer(auto_error=False)

SESSION_DURATION_DAYS = 7


# --------------------------------------
# Request schemas
# --------------------------------------

class RegisterRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


# --------------------------------------
# Helper functions
# --------------------------------------

def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def require_token(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer_scheme)
    ],
) -> str:

    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return credentials.credentials


def get_current_user(
    token: Annotated[str, Depends(require_token)]
):

    token_hash = hash_token(token)

    with get_connection() as conn:
        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT
                    u.id,
                    u.name,
                    u.email,
                    u.role
                FROM sessions s
                JOIN users u ON u.id = s.user_id
                WHERE s.token_hash = %s
                  AND s.expires_at > NOW()
                """,
                (token_hash,)
            )

            user = cur.fetchone()

    if user is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired session",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


# --------------------------------------
# POST /auth/register
# --------------------------------------

@router.post("/register", status_code=201)
def register(request: RegisterRequest):

    name = request.name.strip()
    email = str(request.email).lower()

    if not name:
        raise HTTPException(
            status_code=422,
            detail="Name cannot be empty"
        )

    password_hash = password_hasher.hash(
        request.password
    )

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:

                cur.execute(
                    """
                    INSERT INTO users (
                        name,
                        email,
                        password_hash,
                        role
                    )
                    VALUES (%s, %s, %s, 'viewer')
                    RETURNING id, name, email, role
                    """,
                    (name, email, password_hash)
                )

                user = cur.fetchone()

    except UniqueViolation:
        raise HTTPException(
            status_code=409,
            detail="Email is already registered"
        )

    return user


# --------------------------------------
# POST /auth/login
# --------------------------------------

@router.post("/login")
def login(request: LoginRequest):

    email = str(request.email).lower()

    with get_connection() as conn:
        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT id, email, password_hash
                FROM users
                WHERE email = %s
                """,
                (email,)
            )

            user = cur.fetchone()

    invalid_credentials = HTTPException(
        status_code=401,
        detail="Invalid email or password"
    )

    if user is None:
        raise invalid_credentials

    try:
        password_hasher.verify(
            user["password_hash"],
            request.password
        )
    except (VerificationError, InvalidHashError):
        raise invalid_credentials

    # Generate a secure random session token
    token = secrets.token_urlsafe(32)
    token_hash = hash_token(token)

    expires_at = datetime.now(timezone.utc) + timedelta(
        days=SESSION_DURATION_DAYS
    )

    with get_connection() as conn:
        with conn.cursor() as cur:

            cur.execute(
                """
                INSERT INTO sessions (
                    token_hash,
                    user_id,
                    expires_at
                )
                VALUES (%s, %s, %s)
                """,
                (
                    token_hash,
                    user["id"],
                    expires_at
                )
            )

    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_at": expires_at.isoformat()
    }


# --------------------------------------
# GET /auth/me
# --------------------------------------

@router.get("/me")
def get_my_account(
    current_user: Annotated[
        dict,
        Depends(get_current_user)
    ]
):

    return current_user


# --------------------------------------
# POST /auth/logout
# --------------------------------------

@router.post("/logout")
def logout(
    token: Annotated[str, Depends(require_token)],
    current_user: Annotated[
        dict,
        Depends(get_current_user)
    ]
):

    with get_connection() as conn:
        with conn.cursor() as cur:

            cur.execute(
                """
                DELETE FROM sessions
                WHERE token_hash = %s
                """,
                (hash_token(token),)
            )

    return {"message": "Logged out successfully"}
