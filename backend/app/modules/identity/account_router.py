"""Same-origin account APIs and an explicit, non-consuming email-link landing page."""

import html
import secrets
import time
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Query, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.core.errors import ApiError, ErrorResponse
from app.modules.identity.accounts import AccountService, LinkType
from app.modules.identity.dependencies import get_session_service, session_token
from app.modules.identity.provider import SupabaseProvider
from app.modules.identity.router import set_session_cookie
from app.modules.identity.schemas import SessionResponse, SessionUser
from app.modules.identity.types import InvalidIdentity

router = APIRouter(
    prefix="/api/v1/auth",
    tags=["Accounts"],
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)


class EmailInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    email: EmailStr = Field(max_length=320, repr=False)


class LoginInput(EmailInput):
    password: str = Field(min_length=1, max_length=128, repr=False)


class RegisterInput(EmailInput):
    password: str = Field(min_length=12, max_length=128, repr=False)


class PasswordInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    password: str = Field(min_length=12, max_length=128, repr=False)


class MessageResponse(BaseModel):
    message: str


class RecoveryResponse(BaseModel):
    csrf_token: str


def get_accounts(request: Request) -> AccountService:
    sessions = get_session_service(request)
    provider = getattr(request.app.state, "identity_provider", None)
    if not isinstance(provider, SupabaseProvider):
        raise ApiError(503, "AUTH_NOT_CONFIGURED", "Account services are not available.")
    return AccountService(sessions, provider)


AccountsDependency = Annotated[AccountService, Depends(get_accounts)]


def origin_check(request: Request) -> None:
    if (
        request.headers.get("Origin") != request.app.state.settings.auth_site_url
        or request.headers.get("Sec-Fetch-Site") == "cross-site"
    ):
        raise ApiError(403, "CSRF_REJECTED", "Reload the page and try again.")


def rate(request: Request, service: AccountService, action: str, email: str = "") -> None:
    peer = request.client.host if request.client else "unknown"
    service.limit(action, peer, email)


def authenticated_token(request: Request, service: AccountService, purpose: str) -> str:
    origin_check(request)
    opaque = session_token(request, request.app.state.settings)
    if opaque is None:
        raise ApiError(401, "AUTH_REQUIRED", "Sign in or request a new recovery link.")
    result, _ = service.account_access(opaque, purpose)
    supplied = request.headers.get("X-CSRF-Token", "")
    if not secrets.compare_digest(supplied.encode(), result.csrf_token.encode()):
        raise ApiError(403, "CSRF_REJECTED", "Reload the page and try again.")
    return opaque


@router.post("/register", operation_id="registerAccount", response_model=MessageResponse)
def register(body: RegisterInput, request: Request, service: AccountsDependency) -> MessageResponse:
    origin_check(request)
    rate(request, service, "register", str(body.email))
    service.send("register", str(body.email), body.password)
    return MessageResponse(
        message="If registration is available, check your email to verify your account."
    )


@router.post("/login", operation_id="loginAccount", response_model=SessionResponse)
def login(
    body: LoginInput, request: Request, response: Response, service: AccountsDependency
) -> SessionResponse:
    origin_check(request)
    rate(request, service, "login", str(body.email))
    result = service.login(
        str(body.email), body.password, session_token(request, request.app.state.settings)
    )
    set_session_cookie(response, request.app.state.settings, result)
    return SessionResponse(
        user=SessionUser(id=result.user_id, role="Admin" if result.role == "Admin" else "Member"),
        aal="aal2" if result.aal == "aal2" else "aal1",
        expires_at=result.expires_at,
        csrf_token=result.csrf_token,
    )


@router.post("/recover", operation_id="requestAccountRecovery", response_model=MessageResponse)
def recover(body: EmailInput, request: Request, service: AccountsDependency) -> MessageResponse:
    origin_check(request)
    rate(request, service, "recover", str(body.email))
    service.send("recover", str(body.email))
    return MessageResponse(message="If the account is eligible, a recovery email has been sent.")


@router.post("/resend", operation_id="resendAccountVerification", response_model=MessageResponse)
def resend(body: EmailInput, request: Request, service: AccountsDependency) -> MessageResponse:
    origin_check(request)
    rate(request, service, "resend", str(body.email))
    service.send("resend", str(body.email))
    return MessageResponse(message="If verification is needed, check your email for a new link.")


def callback_cookie(request: Request) -> str:
    return (
        "__Host-roombook_callback"
        if request.app.state.settings.auth_cookie_secure
        else "roombook_callback"
    )


@router.get("/confirm", operation_id="showAccountConfirmation", response_class=HTMLResponse)
def confirmation_page(
    request: Request,
    service: AccountsDependency,
    token_hash: Annotated[str, Query(min_length=20, max_length=256, pattern=r"^[A-Za-z0-9_-]+$")],
    type: LinkType,
) -> HTMLResponse:
    # Link scanners may GET this page: only a deliberate same-origin POST consumes the OTP.
    nonce = secrets.token_urlsafe(32)
    csrf = service.sessions.cipher.csrf_token(nonce)
    style_nonce = secrets.token_urlsafe(16)
    response = HTMLResponse(
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>Confirm your account link | RoomBook</title>"
        f'<style nonce="{style_nonce}">'
        "body{font:1rem/1.5 system-ui;margin:0;background:#f4f3ef;color:#171717}"
        "main{max-width:30rem;margin:10vh auto;padding:2rem;background:white;border-radius:.75rem}"
        "button{font:inherit;padding:.8rem 1rem;background:#cf251e;color:white;"
        "border:0;border-radius:.4rem;cursor:pointer}"
        "button:focus-visible,a:focus-visible{outline:3px solid #171717;outline-offset:4px}"
        "@media(prefers-color-scheme:dark){body{background:#121212;color:#f5f3ef}main{background:#1c1c1c}}"
        "</style></head><body><main><p>RoomBook</p><h1>Confirm your account link</h1>"
        "<p>Continue only if you requested this email. "
        "Verification does not automatically sign you in.</p>"
        '<form method="post" action="/api/v1/auth/confirm">'
        f'<input type="hidden" name="token_hash" value="{html.escape(token_hash, quote=True)}">'
        f'<input type="hidden" name="type" value="{html.escape(type, quote=True)}">'
        f'<input type="hidden" name="csrf" value="{csrf}">'
        '<button type="submit" disabled>Confirm link</button></form>'
        '<p role="alert" id="confirmation-error"></p>'
        "<noscript>Enable JavaScript to confirm this link securely.</noscript>"
        '<p><a href="/account/login">Back to sign in</a></p>'
        f'<script nonce="{style_nonce}">'
        'const form=document.querySelector("form"),button=form.querySelector("button");'
        "button.disabled=false;"
        'form.addEventListener("submit",async(event)=>{event.preventDefault();'
        "if(button.disabled)return;button.disabled=true;"
        "const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),15000);"
        "try{const response=await fetch(form.action,{method:'POST',body:new FormData(form),"
        "credentials:'same-origin',mode:'cors',referrerPolicy:'no-referrer',signal:controller.signal});"
        "const target=new URL(response.url);"
        "if(response.redirected&&target.origin===location.origin&&"
        "['/account/login','/account/reset'].includes(target.pathname)){"
        "location.replace(target.href);return;}"
        "}catch{}finally{clearTimeout(timer);}"
        'document.getElementById("confirmation-error").textContent='
        '"The link could not be confirmed. Open the email link again or request a new one.";'
        "button.disabled=false;});</script>"
        "</main></body></html>"
    )
    response.set_cookie(
        callback_cookie(request),
        service.sessions.cipher.encrypt(f"{int(time.time())}:{nonce}"),
        secure=request.app.state.settings.auth_cookie_secure,
        httponly=True,
        samesite="lax",
        max_age=600,
    )
    response.headers["Content-Security-Policy"] = (
        f"default-src 'none'; style-src 'nonce-{style_nonce}'; "
        f"script-src 'nonce-{style_nonce}'; connect-src 'self'; "
        "form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
    )
    response.headers["X-Frame-Options"] = "DENY"
    return response


@router.post("/confirm", operation_id="confirmAccountEmail", response_class=RedirectResponse)
def confirm(
    request: Request,
    service: AccountsDependency,
    token_hash: Annotated[str, Form(min_length=20, max_length=256, pattern=r"^[A-Za-z0-9_-]+$")],
    type: Annotated[LinkType, Form()],
    csrf: Annotated[str, Form(max_length=128)],
) -> RedirectResponse:
    origin_check(request)
    rate(request, service, "confirm")
    try:
        value = service.sessions.cipher.decrypt(request.cookies.get(callback_cookie(request), ""))
        timestamp, nonce = value.split(":", 1)
        if not 0 <= time.time() - int(timestamp) <= 600 or not secrets.compare_digest(
            csrf.encode(), service.sessions.cipher.csrf_token(nonce).encode()
        ):
            raise ValueError
    except (InvalidIdentity, ValueError):
        raise ApiError(
            403, "LINK_CONFIRMATION_EXPIRED", "Open the email link again to continue."
        ) from None
    try:
        result = service.confirm(
            token_hash, type, session_token(request, request.app.state.settings)
        )
        target = "/account/reset" if type == "recovery" else "/account/login?notice=verified"
        if type == "email_change":
            target = "/account/login?notice=email-change"
        response = RedirectResponse(target, status_code=303)
        if result is not None:
            set_session_cookie(response, request.app.state.settings, result)
    except ApiError:
        response = RedirectResponse("/account/login?notice=link-error", status_code=303)
    response.delete_cookie(
        callback_cookie(request),
        secure=request.app.state.settings.auth_cookie_secure,
        httponly=True,
        samesite="lax",
    )
    return response


@router.get("/recovery-session", operation_id="getRecoverySession", response_model=RecoveryResponse)
def recovery_session(request: Request, service: AccountsDependency) -> RecoveryResponse:
    opaque = session_token(request, request.app.state.settings)
    if opaque is None:
        raise ApiError(401, "AUTH_REQUIRED", "Request a new recovery link.")
    result, _ = service.account_access(opaque, "recovery")
    return RecoveryResponse(csrf_token=result.csrf_token)


@router.post("/reset-password", operation_id="resetAccountPassword", response_model=MessageResponse)
def reset_password(
    body: PasswordInput, request: Request, response: Response, service: AccountsDependency
) -> MessageResponse:
    opaque = authenticated_token(request, service, "recovery")
    rate(request, service, "reset-password")
    service.change(opaque, body.password, recovery=True)
    response.delete_cookie(
        request.app.state.settings.auth_cookie_name,
        secure=request.app.state.settings.auth_cookie_secure,
        httponly=True,
        samesite="lax",
    )
    return MessageResponse(message="Password changed. Sign in with your new password.")


@router.post("/change-email", operation_id="changeAccountEmail", response_model=MessageResponse)
def change_email(
    body: EmailInput, request: Request, response: Response, service: AccountsDependency
) -> MessageResponse:
    opaque = authenticated_token(request, service, "standard")
    rate(request, service, "change-email", str(body.email))
    service.change(opaque, str(body.email), recovery=False)
    response.delete_cookie(
        request.app.state.settings.auth_cookie_name,
        secure=request.app.state.settings.auth_cookie_secure,
        httponly=True,
        samesite="lax",
    )
    return MessageResponse(
        message="Check both email addresses to confirm the change, then sign in again."
    )
