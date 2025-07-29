from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2AuthorizationCodeBearer
from fief_client import FiefAccessTokenInfo, FiefAsync, FiefUserInfo
from fief_client.integrations.fastapi import FiefAuth

app = FastAPI()

# Fief client setup
fief = FiefAsync(
    "http://localhost:8000",
    "6bc8e7d1-9f2a-4e1b-b67c-8d2a4567890c",
    "NJqwx0LkOg3iHJ6-1Qw5cvS2fkGT9U19MhVZPT8gMyw",
)

# OAuth2 scheme setup
oauth2_scheme = OAuth2AuthorizationCodeBearer(
    "http://localhost:8000/authorize",
    "http://localhost:8000/api/token",
    scopes={"openid": "openid", "offline_access": "offline_access"},
    auto_error=False,
)

# Fief auth integration
auth = FiefAuth(fief, oauth2_scheme)


# Current user dependency
async def get_current_user(
    access_token_info: FiefAccessTokenInfo = Depends(auth.authenticated()),
) -> FiefUserInfo:
    """Get current authenticated user details"""
    try:
        user_info = await fief.userinfo(access_token_info.access_token)
        return user_info
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )


# Routes
@app.get("/")
async def root():
    """Public homepage"""
    return {"message": "Welcome to the API! Go to /docs to test authentication"}


@app.get("/login")
async def login():
    """Redirect to Fief login page"""
    auth_url = await fief.auth_url(
        redirect_uri="http://localhost:5000/callback",
        scope=["openid", "offline_access"],
    )
    return RedirectResponse(auth_url)


@app.get("/callback")
async def callback(request: Request, response: Response):
    """Handle the OAuth callback"""
    try:
        code = request.query_params.get("code")
        tokens = await fief.auth_callback(code, "http://localhost:5000/callback")

        # Here you can set cookies, create a session, etc.
        response = RedirectResponse("/profile")
        response.set_cookie(
            "access_token",
            tokens["access_token"],
            httponly=True,
            max_age=3600,
            secure=False,  # Set to True in production with HTTPS
        )
        return response
    except Exception as e:
        return {"error": str(e)}


@app.get("/profile")
async def profile(user: FiefUserInfo = Depends(get_current_user)):
    """Protected route that requires authentication"""
    return {"message": f"Hello, {user.email}!", "user_info": user}


@app.get("/logout")
async def logout():
    """Log the user out"""
    logout_url = await fief.logout_url("http://localhost:5000/")
    response = RedirectResponse(logout_url)
    response.delete_cookie("access_token")
    return response


# Admin permission checking dependency
async def require_admin(access_token_info: FiefAccessTokenInfo = Depends(auth.authenticated())):
    """Check if user has admin permission"""
    if "admin" not in access_token_info.permissions:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions"
        )
    return access_token_info


# Admin-only endpoint example
@app.get("/admin")
async def admin_only(
    user: FiefUserInfo = Depends(get_current_user),
    # Use the custom permission check
    admin_check: FiefAccessTokenInfo = Depends(require_admin),
):
    """Protected route that requires admin permissions"""
    return {"message": f"Hello Admin {user.email}!", "permissions": admin_check.permissions}
