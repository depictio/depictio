# app/admin.py
from pathlib import Path
from typing import List

from app.db import Group, User
from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

# Set up templates directory - create it if it doesn't exist
templates_dir = Path(__file__).parent.parent / "templates"
templates_dir.mkdir(exist_ok=True)

admin_templates_dir = templates_dir / "admin"
admin_templates_dir.mkdir(exist_ok=True)

templates = Jinja2Templates(directory=str(templates_dir))

admin_router = APIRouter()

admin_sessions = {}


async def get_admin_user(request: Request):
    session_id = request.cookies.get("admin_session")

    if not session_id or session_id not in admin_sessions:
        print(f"Session not found: {session_id}")
        raise HTTPException(
            status_code=status.HTTP_307_TEMPORARY_REDIRECT, headers={"Location": "/admin/login"}
        )

    user_id = admin_sessions[session_id]
    user = await User.get(user_id)

    if not user or not user.is_active or not user.is_superuser:
        # Clear invalid session
        admin_sessions.pop(session_id, None)
        print("User not found or not active/superuser")
        raise HTTPException(
            status_code=status.HTTP_307_TEMPORARY_REDIRECT, headers={"Location": "/admin/login"}
        )

    return user


@admin_router.get("/login", response_class=HTMLResponse)
async def admin_login_get(request: Request):
    return templates.TemplateResponse("admin/login.html", {"request": request})


@admin_router.post("/login")
async def admin_login_post(request: Request):
    form = await request.form()
    email = form.get("username")  # The form field is named "username" for OAuth compatibility
    password = form.get("password")

    try:
        # Find user by email
        user = await User.find_one(User.email == email)

        if not user:
            return templates.TemplateResponse(
                "admin/login.html", {"request": request, "error": "Invalid email or password"}
            )

        # Verify password using the same helper used by FastAPIUsers
        from fastapi_users.password import PasswordHelper

        password_helper = PasswordHelper()
        verified = password_helper.verify_and_update(password, user.hashed_password)

        if not verified:
            return templates.TemplateResponse(
                "admin/login.html", {"request": request, "error": "Invalid email or password"}
            )

        # Check if user is a superuser
        if not user.is_superuser:
            return templates.TemplateResponse(
                "admin/login.html",
                {"request": request, "error": "Only superusers can access the admin panel"},
            )

        # Generate a simple session key
        import secrets

        session_id = secrets.token_hex(16)

        # Store session in a cookie
        response = RedirectResponse(url="/admin", status_code=303)  # HTTP 303 for POST redirects
        response.set_cookie(key="admin_session", value=session_id, httponly=True)

        # Store the session key and user ID in memory (or Redis in production)
        # For simplicity, we'll use a global dictionary
        from app.admin import admin_sessions

        admin_sessions[session_id] = str(user.id)

        return response

    except Exception as e:
        print(f"Login error: {str(e)}")
        import traceback

        traceback.print_exc()
        return templates.TemplateResponse(
            "admin/login.html", {"request": request, "error": "An error occurred during login"}
        )


@admin_router.get("/logout")
async def admin_logout(request: Request):
    session_id = request.cookies.get("admin_session")
    if session_id and session_id in admin_sessions:
        admin_sessions.pop(session_id, None)

    response = RedirectResponse(url="/admin/login", status_code=303)
    response.delete_cookie("admin_session")
    return response


@admin_router.get("/", response_class=HTMLResponse)
async def admin_dashboard(request: Request, user: User = Depends(get_admin_user)):
    # Make sure the get_admin_user dependency works as expected
    print(f"Admin user: {user.email}")

    # Get counts for dashboard
    user_count = await User.count()
    active_user_count = await User.find(User.is_active == True).count()
    group_count = await Group.count()

    # Get recent users
    recent_users = await User.find().sort(-User.created_at).limit(5).to_list()

    return templates.TemplateResponse(
        "admin/dashboard.html",
        {
            "request": request,
            "current_user": user,
            "user_count": user_count,
            "active_user_count": active_user_count,
            "group_count": group_count,
            "recent_users": recent_users,
        },
    )


# User management routes
@admin_router.get("/users", response_class=HTMLResponse)
async def admin_users(request: Request, user: User = Depends(get_admin_user)):
    users = await User.find().to_list()
    return templates.TemplateResponse(
        "admin/users.html", {"request": request, "current_user": user, "users": users}
    )


@admin_router.get("/users/create", response_class=HTMLResponse)
async def create_user_form(request: Request, user: User = Depends(get_admin_user)):
    groups = await Group.find().to_list()
    return templates.TemplateResponse(
        "admin/user_edit.html",
        {
            "request": request,
            "current_user": user,
            "user": None,
            "groups": groups,
            "user_group_ids": [],
        },
    )


@admin_router.post("/users/create", response_class=HTMLResponse)
async def create_user(request: Request, user: User = Depends(get_admin_user)):
    try:
        # Get form data
        form = await request.form()
        email = form.get("email")
        password = form.get("password")
        first_name = form.get("first_name", "")
        last_name = form.get("last_name", "")
        is_active = "is_active" in form
        is_verified = "is_verified" in form
        is_superuser = "is_superuser" in form

        # Get groups from form
        group_ids = []
        if "groups" in form:
            group_value = form.get("groups")
            if isinstance(group_value, list):
                group_ids = group_value
            else:
                group_ids = [group_value]

        # Import necessary components
        from app.db import get_user_db
        from app.schemas import UserCreate
        from app.users import get_user_manager

        # Get the actual user_db and user_manager instances
        user_db = await anext(get_user_db())
        user_manager = await anext(get_user_manager(user_db))

        # Create a proper UserCreate instance
        user_create = UserCreate(
            email=email, password=password, first_name=first_name, last_name=last_name
        )

        # Create the user
        new_user = await user_manager.create(user_create)

        # Update additional fields if needed
        if (
            new_user.is_active != is_active
            or new_user.is_verified != is_verified
            or new_user.is_superuser != is_superuser
        ):
            new_user.is_active = is_active
            new_user.is_verified = is_verified
            new_user.is_superuser = is_superuser
            await new_user.save()

        # Add groups to the user
        if group_ids:
            group_objs = []
            for group_id in group_ids:
                group = await Group.get(group_id)
                if group:
                    group_objs.append(group)

            # Update the user with groups
            new_user.groups = group_objs
            await new_user.save()

        return RedirectResponse(url="/admin/users", status_code=303)
    except Exception as e:
        print(f"User creation error: {str(e)}")
        import traceback

        traceback.print_exc()

        # Fetch groups for the form
        groups = await Group.find().to_list()

        return templates.TemplateResponse(
            "admin/user_edit.html",
            {
                "request": request,
                "current_user": user,
                "user": None,
                "groups": groups,
                "user_group_ids": [],
                "error": f"Error creating user: {str(e)}",
            },
        )


@admin_router.get("/users/{user_id}", response_class=HTMLResponse)
async def edit_user_form(
    request: Request, user_id: str, current_user: User = Depends(get_admin_user)
):
    user_to_edit = await User.get(user_id)
    if not user_to_edit:
        raise HTTPException(status_code=404, detail="User not found")

    groups = await Group.find().to_list()

    await user_to_edit.fetch_link(User.groups)
    user_group_ids = [str(group.id) for group in user_to_edit.groups]
    return templates.TemplateResponse(
        "admin/user_edit.html",
        {
            "request": request,
            "current_user": current_user,
            "user": user_to_edit,
            "groups": groups,
            "user_group_ids": user_group_ids,
        },
    )


@admin_router.post("/users/{user_id}", response_class=HTMLResponse)
async def update_user(
    request: Request,
    user_id: str,
    email: str = Form(...),
    first_name: str = Form(""),
    last_name: str = Form(""),
    is_active: bool = Form(False),
    is_verified: bool = Form(False),
    is_superuser: bool = Form(False),
    groups: List[str] = Form([]),
    current_user: User = Depends(get_admin_user),
):
    user_to_update = await User.get(user_id)
    if not user_to_update:
        raise HTTPException(status_code=404, detail="User not found")

    # Update user fields
    user_to_update.email = email
    user_to_update.first_name = first_name
    user_to_update.last_name = last_name
    user_to_update.is_active = bool(is_active)
    user_to_update.is_verified = bool(is_verified)
    user_to_update.is_superuser = bool(is_superuser)

    # Update groups
    if groups:
        group_objs = []
        for group_id in groups:
            group = await Group.get(group_id)
            if group:
                group_objs.append(group)

        user_to_update.groups = group_objs
    else:
        user_to_update.groups = []

    await user_to_update.save()
    return RedirectResponse(url="/admin/users", status_code=status.HTTP_302_FOUND)


@admin_router.post("/users/{user_id}/toggle-active")
async def toggle_user_active(user_id: str, current_user: User = Depends(get_admin_user)):
    user_to_update = await User.get(user_id)
    if not user_to_update:
        raise HTTPException(status_code=404, detail="User not found")

    user_to_update.is_active = not user_to_update.is_active
    await user_to_update.save()

    return RedirectResponse(url="/admin/users", status_code=status.HTTP_302_FOUND)


# Group management routes
@admin_router.get("/groups", response_class=HTMLResponse)
async def admin_groups(request: Request, user: User = Depends(get_admin_user)):
    groups = await Group.find().to_list()
    return templates.TemplateResponse(
        "admin/groups.html",
        {"request": request, "current_user": user, "groups": groups},
    )


@admin_router.get("/groups/create", response_class=HTMLResponse)
async def create_group_form(request: Request, user: User = Depends(get_admin_user)):
    return templates.TemplateResponse(
        "admin/group_edit.html",
        {"request": request, "current_user": user, "group": None},
    )


@admin_router.post("/groups/create")
async def create_group(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    permissions: str = Form(""),
    user: User = Depends(get_admin_user),
):
    # Parse permissions from comma-separated string
    permission_list = [p.strip() for p in permissions.split(",")] if permissions else []

    # Create new group
    new_group = Group(name=name, description=description, permissions=permission_list)
    await new_group.save()

    return RedirectResponse(url="/admin/groups", status_code=status.HTTP_302_FOUND)


@admin_router.get("/groups/{group_id}", response_class=HTMLResponse)
async def edit_group_form(request: Request, group_id: str, user: User = Depends(get_admin_user)):
    group = await Group.get(group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    return templates.TemplateResponse(
        "admin/group_edit.html",
        {"request": request, "current_user": user, "group": group},
    )


@admin_router.post("/groups/{group_id}")
async def update_group(
    request: Request,
    group_id: str,
    name: str = Form(...),
    description: str = Form(""),
    permissions: str = Form(""),
    user: User = Depends(get_admin_user),
):
    group = await Group.get(group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    # Parse permissions from comma-separated string
    permission_list = [p.strip() for p in permissions.split(",")] if permissions else []

    # Update group
    group.name = name
    group.description = description
    group.permissions = permission_list
    await group.save()

    return RedirectResponse(url="/admin/groups", status_code=status.HTTP_302_FOUND)


@admin_router.post("/groups/{group_id}/delete")
async def delete_group(group_id: str, user: User = Depends(get_admin_user)):
    group = await Group.get(group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    # Delete group
    await group.delete()

    return RedirectResponse(url="/admin/groups", status_code=status.HTTP_302_FOUND)
