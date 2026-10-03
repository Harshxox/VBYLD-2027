"""
Admin login.

POST /api/admin/login   {username, password} -> {token, expires_at, username}
GET  /api/admin/me      check a token (used when the admin page reloads)
"""
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.security import check_login, require_admin

router = APIRouter()


class LoginIn(BaseModel):
    username: str = Field(..., max_length=100)
    password: str = Field(..., max_length=200)


@router.post("/login")
def login(payload: LoginIn, request: Request):
    return check_login(request, payload.username.strip(), payload.password)


@router.get("/me")
def me(user: str = Depends(require_admin)):
    return {"username": user}
