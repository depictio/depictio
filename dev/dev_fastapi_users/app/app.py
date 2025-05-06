# app/app.py
from contextlib import asynccontextmanager

from beanie import init_beanie
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path

from app.db import User, Group, db
from app.schemas import UserCreate, UserRead, UserUpdate, GroupCreate, GroupRead, GroupUpdate
from app.users import auth_backend, current_active_user, fastapi_users, google_oauth_client, SECRET
from app.admin import admin_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure templates directory exists
    templates_dir = Path(__file__).parent.parent / "templates"
    templates_dir.mkdir(exist_ok=True)
    admin_templates_dir = templates_dir / "admin"
    admin_templates_dir.mkdir(exist_ok=True)
    
    # Initialize database
    await init_beanie(
        database=db,
        document_models=[
            User,
            Group,
        ],
    )
    yield


app = FastAPI(lifespan=lifespan)

# Mount static files directory if needed
static_dir = Path(__file__).parent.parent / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# Include FastAPI Users routes
app.include_router(
    fastapi_users.get_auth_router(auth_backend), prefix="/auth/jwt", tags=["auth"]
)
app.include_router(
    fastapi_users.get_register_router(UserRead, UserCreate),
    prefix="/auth",
    tags=["auth"],
)
app.include_router(
    fastapi_users.get_reset_password_router(),
    prefix="/auth",
    tags=["auth"],
)
app.include_router(
    fastapi_users.get_verify_router(UserRead),
    prefix="/auth",
    tags=["auth"],
)
app.include_router(
    fastapi_users.get_users_router(UserRead, UserUpdate),
    prefix="/users",
    tags=["users"],
)
app.include_router(
    fastapi_users.get_oauth_router(
        google_oauth_client,
        auth_backend,
        "SECRET",
        associate_by_email=True,
    ),
    prefix="/auth/google",
    tags=["auth"],
)
# Include admin routes
app.include_router(admin_router, prefix="/admin", tags=["admin"])

# Define a superuser dependency
async def get_current_superuser(user: User = Depends(current_active_user)):
    if not user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Superuser privileges required",
        )
    return user

# Group API endpoints
@app.get("/groups", response_model=list[GroupRead], tags=["groups"])
async def get_groups(user: User = Depends(current_active_user)):
    """Get all groups (requires authenticated user)"""
    return await Group.find().to_list()

@app.get("/groups/{group_id}", response_model=GroupRead, tags=["groups"])
async def get_group(group_id: str, user: User = Depends(current_active_user)):
    """Get a specific group by ID (requires authenticated user)"""
    group = await Group.get(group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    return group

@app.post("/groups", response_model=GroupRead, tags=["groups"])
async def create_group(
    group: GroupCreate, user: User = Depends(get_current_superuser)
):
    """Create a new group (requires superuser)"""
    new_group = Group(**group.dict())
    await new_group.save()
    return new_group

@app.patch("/groups/{group_id}", response_model=GroupRead, tags=["groups"])
async def update_group(
    group_id: str, 
    group_data: GroupUpdate, 
    user: User = Depends(get_current_superuser)
):
    """Update a group (requires superuser)"""
    group = await Group.get(group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    
    # Update fields
    group_dict = group_data.dict(exclude_unset=True)
    for field, value in group_dict.items():
        setattr(group, field, value)
    
    await group.save()
    return group

@app.delete("/groups/{group_id}", tags=["groups"])
async def delete_group(group_id: str, user: User = Depends(get_current_superuser)):
    """Delete a group (requires superuser)"""
    group = await Group.get(group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    
    await group.delete()
    return {"detail": "Group deleted successfully"}

# API to add/remove user from group
@app.post("/users/{user_id}/groups/{group_id}", tags=["users", "groups"])
async def add_user_to_group(
    user_id: str, 
    group_id: str, 
    current_user: User = Depends(get_current_superuser)
):
    """Add a user to a group (requires superuser)"""
    user = await User.get(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    group = await Group.get(group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    
    # Check if user already in group
    if any(g.id == group.id for g in user.groups):
        return {"detail": "User already in this group"}
    
    # Add group to user's groups
    user.groups.append(group)
    await user.save()
    
    return {"detail": "User added to group successfully"}

@app.delete("/users/{user_id}/groups/{group_id}", tags=["users", "groups"])
async def remove_user_from_group(
    user_id: str, 
    group_id: str, 
    current_user: User = Depends(get_current_superuser)
):
    """Remove a user from a group (requires superuser)"""
    user = await User.get(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    group = await Group.get(group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    
    # Remove group from user's groups
    user.groups = [g for g in user.groups if g.id != group.id]
    await user.save()
    
    return {"detail": "User removed from group successfully"}

@app.get("/", tags=["root"])
async def root():
    """Redirect to API docs"""
    return RedirectResponse(url="/docs")


@app.get("/authenticated-route")
async def authenticated_route(user: User = Depends(current_active_user)):
    return {"message": f"Hello {user.email}!"}