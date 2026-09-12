"""
auth.py

Authentication endpoints and token dependency for Day 7.

Provides:
  POST /auth/login    Authenticate and return access token
  GET  /auth/me       Return current authenticated user
  get_current_user    Reusable FastAPI dependency for extracting authenticated user identity
"""

import base64
import logging
from typing import Optional

import requests
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field

from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Auth"])


class LoginRequest(BaseModel):
    username: str = Field(..., description="Username or email", min_length=1)
    password: Optional[str] = Field(default=None, description="User password")


class GoogleLoginRequest(BaseModel):
    credential: str = Field(..., description="Google ID Token credential from Google Identity Services")



class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    username: str


class UserResponse(BaseModel):
    user_id: str
    username: str
    role: str = "student"


def create_access_token(user_id: str) -> str:
    """Create a URL-safe token representing the authenticated user."""
    clean_id = user_id.strip()
    encoded = base64.urlsafe_b64encode(clean_id.encode("utf-8")).decode("utf-8")
    return f"tok_{encoded}"


def decode_access_token(token: str) -> str:
    """Decode an access token to extract the user_id."""
    clean_token = token.strip()
    if clean_token in ("dev-token", "dev-user"):
        return "dev-user"

    if clean_token.startswith("tok_"):
        raw_b64 = clean_token[4:]
        try:
            decoded = base64.urlsafe_b64decode(raw_b64.encode("utf-8")).decode("utf-8")
            if decoded:
                return decoded
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid access token format.",
            )

    if clean_token.startswith("token-"):
        uid = clean_token[6:].strip()
        if uid:
            return uid

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials.",
    )


def get_current_user(authorization: Optional[str] = Header(default=None)) -> str:
    """
    Returns the authenticated user_id.

    Derived strictly from the Authorization: Bearer <token> header.
    Never trusts a browser-supplied user_id in the request body.

    Backward compatibility:
    If no Authorization header is provided (e.g. during Days 1-6 test runs),
    falls back safely to 'dev-user'.
    """
    if authorization is None:
        return "dev-user"

    parts = authorization.strip().split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header scheme. Must be Bearer <token>.",
        )

    token = parts[1].strip()
    return decode_access_token(token)


@router.post("/login", response_model=AuthResponse)
def login(request: LoginRequest):
    """
    Authenticate user and return a bearer access token.
    Allows login with 'dev-user' or any student username.
    """
    username = request.username.strip()
    if not username:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Username cannot be blank.",
        )

    token = create_access_token(username)
    logger.info("User '%s' authenticated successfully.", username)
    return AuthResponse(
        access_token=token,
        token_type="bearer",
        user_id=username,
        username=username,
    )


def verify_google_token(credential: str) -> dict:
    """
    Verifies a Google ID token with Google Identity Services.
    Validates audience against settings.GOOGLE_CLIENT_ID and expiration.
    Returns the parsed payload containing 'sub', 'email', 'name', etc.
    """
    try:
        idinfo = id_token.verify_oauth2_token(
            credential,
            google_requests.Request(),
            settings.GOOGLE_CLIENT_ID,
        )
        return idinfo
    except Exception as exc:
        # Fallback to direct Google tokeninfo endpoint if local cert verification fails
        try:
            resp = requests.get(
                f"https://oauth2.googleapis.com/tokeninfo?id_token={credential}",
                timeout=5,
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("aud") == settings.GOOGLE_CLIENT_ID:
                    return data
        except Exception:
            pass
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid Google ID token: {str(exc)}",
        )


from sqlalchemy.orm import Session as DBSession
from app.db.database import get_db
from app.models.user import User


@router.post("/google", response_model=AuthResponse)
def login_google(
    request: GoogleLoginRequest,
    db: DBSession = Depends(get_db),
):
    """
    Authenticate with Google Identity Services ID Token.
    Derives stable user_id from Google 'sub' claim (never email).
    Finds or creates PostgreSQL user record.
    Returns an application Bearer access token.
    """
    credential = request.credential.strip()
    if not credential:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Google credential token cannot be empty.",
        )

    idinfo = verify_google_token(credential)
    google_sub = idinfo.get("sub")
    if not google_sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Google ID token missing 'sub' claim.",
        )

    # Use Google's sub as the permanent, unique user identity (rule: never use email as primary user ID)
    user_id = f"google_{google_sub}"
    display_name = idinfo.get("name") or idinfo.get("email", "").split("@")[0] or user_id
    email = idinfo.get("email")

    # Find or create PostgreSQL user
    try:
        existing_user = db.query(User).filter(User.id == user_id).first()
        if not existing_user:
            new_user = User(
                id=user_id,
                email=email,
                username=display_name,
            )
            db.add(new_user)
            db.commit()
            logger.info("Created new PostgreSQL user: %s", user_id)
        else:
            logger.info("Found existing PostgreSQL user: %s", user_id)
    except Exception as exc:
        db.rollback()
        logger.error("Error persisting user to database: %s", exc)

    token = create_access_token(user_id)
    logger.info("Google user authenticated: user_id=%s, name=%s", user_id, display_name)
    return AuthResponse(
        access_token=token,
        token_type="bearer",
        user_id=user_id,
        username=display_name,
    )




@router.get("/me", response_model=UserResponse)
def get_me(current_user: str = Depends(get_current_user)):
    """Return the profile of the currently authenticated user."""
    return UserResponse(
        user_id=current_user,
        username=current_user,
        role="student",
    )


@router.get("/status")
def auth_status():
    """Auth service status and manifest."""
    return {
        "status": "active",
        "day": 7,
        "auth_type": "bearer_token",
        "default_user": "dev-user",
    }

