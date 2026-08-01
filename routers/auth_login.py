# routers/auth.py
from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse
from utils.auth import authenticate_domain_user, create_session_cookie
from main import templates

router = APIRouter()

@router.get("/login")
async def login_form(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@router.post("/login")
async def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    if not authenticate_domain_user(username, password):
        return templates.TemplateResponse("login.html", {
            "request": request, "error": "Invalid username or password"
        })

    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(
        key="app_session",
        value=create_session_cookie(username.strip()),
        httponly=True,
        secure=True,       # requires HTTPS — you're already on TLS per the earlier error messages
        samesite="lax",
        max_age=8 * 3600,
    )
    return response

@router.get("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("app_session")
    return response