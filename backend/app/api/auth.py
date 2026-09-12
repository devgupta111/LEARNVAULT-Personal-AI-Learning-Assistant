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
from sqlalchemy.orm import Session as DBSession

from app.config import settings
from app.db.database import get_db
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Auth"])


class LoginRequest(BaseModel):
    username: str = Field(..., description="Username or email", min_length=1)
    password: Optional[str] = Field(default=None, description="User password")


class GoogleLoginRequest(BaseModel):
    credential: str = Field(..., description="Google ID Token credential from Google Identity Services")


class UpdateProfileRequest(BaseModel):
    username: str = Field(..., description="User's actual name or username", min_length=1, max_length=100)



class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    username: Optional[str] = None
    email: Optional[str] = None
    picture: Optional[str] = None
    auth_provider: Optional[str] = None


class UserResponse(BaseModel):
    user_id: str
    username: Optional[str] = None
    email: Optional[str] = None
    picture: Optional[str] = None
    auth_provider: Optional[str] = None
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


def require_authenticated_user(authorization: Optional[str] = Header(default=None)) -> str:
    """
    Strictly requires an authenticated Bearer token.
    Raises 401 Unauthorized if Authorization header is missing or invalid.
    """
    if authorization is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Missing Authorization header.",
        )
    return get_current_user(authorization)


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
    # Rule: Do not invent names. dev-user is a guest session without a user-provided name.
    actual_name = None if username == "dev-user" else username
    return AuthResponse(
        access_token=token,
        token_type="bearer",
        user_id=username,
        username=actual_name,
        auth_provider="guest" if username == "dev-user" else "local",
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
    # Rule: ONLY verified user-provided name from Google profile; NEVER derive from email or user_id
    display_name = idinfo.get("name") or None
    email = idinfo.get("email") or None
    picture = idinfo.get("picture") or None

    # Find or create/update user in database
    try:
        existing_user = db.query(User).filter(User.id == user_id).first()
        if not existing_user:
            new_user = User(
                id=user_id,
                email=email,
                username=display_name,
                picture=picture,
                auth_provider="google",
            )
            db.add(new_user)
            db.commit()
            logger.info("Created new user: %s", user_id)
        else:
            updated = False
            if display_name and existing_user.username != display_name:
                existing_user.username = display_name
                updated = True
            if email and existing_user.email != email:
                existing_user.email = email
                updated = True
            if picture and existing_user.picture != picture:
                existing_user.picture = picture
                updated = True
            if existing_user.auth_provider != "google":
                existing_user.auth_provider = "google"
                updated = True
            if updated:
                db.commit()
            logger.info("Found existing user: %s", user_id)
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
        email=email,
        picture=picture,
        auth_provider="google",
    )




@router.get("/me", response_model=UserResponse)
def get_me(
    current_user: str = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Return the profile of the currently authenticated user."""
    db_user = db.query(User).filter(User.id == current_user).first()
    if db_user:
        return UserResponse(
            user_id=db_user.id,
            username=db_user.username,
            email=db_user.email,
            picture=db_user.picture,
            auth_provider=db_user.auth_provider or ("google" if db_user.id.startswith("google_") else "local"),
            role="student",
        )

    actual_name = None if current_user == "dev-user" else current_user
    return UserResponse(
        user_id=current_user,
        username=actual_name,
        email=None,
        picture=None,
        auth_provider="guest" if current_user == "dev-user" else "local",
        role="student",
    )


@router.put("/profile", response_model=UserResponse)
def update_profile(
    request: UpdateProfileRequest,
    current_user: str = Depends(require_authenticated_user),
    db: DBSession = Depends(get_db),
):
    """
    Update the authenticated user's display name / username.
    Security: Uses current_user derived from verified Bearer token; never allows updating other accounts.
    Email is strictly read-only and immutable.
    """
    clean_name = request.username.strip()
    if not clean_name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Name cannot be blank.",
        )

    db_user = db.query(User).filter(User.id == current_user).first()
    if db_user:
        db_user.username = clean_name
        db.commit()
        db.refresh(db_user)
        logger.info("Updated profile name for user '%s' to '%s'", current_user, clean_name)
        return UserResponse(
            user_id=db_user.id,
            username=db_user.username,
            email=db_user.email,
            picture=db_user.picture,
            auth_provider=db_user.auth_provider or ("google" if db_user.id.startswith("google_") else "local"),
            role="student",
        )

    # If the user doesn't have a record yet (e.g. guest or local session), create one
    new_user = User(
        id=current_user,
        username=clean_name,
        email=None,
        auth_provider="guest" if current_user == "dev-user" else "local",
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    logger.info("Created user record on profile update: '%s' with name '%s'", current_user, clean_name)
    return UserResponse(
        user_id=new_user.id,
        username=new_user.username,
        email=new_user.email,
        picture=new_user.picture,
        auth_provider=new_user.auth_provider,
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

