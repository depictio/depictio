# create_admin.py
import asyncio
import logging
from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie
from fastapi_users.password import PasswordHelper

from app.db import User, Group, db

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def create_admin_user(
    email: str, password: str, first_name: str = None, last_name: str = None
):
    # Initialize Beanie with our document models
    await init_beanie(
        database=db,
        document_models=[User, Group],
    )

    # Check if user already exists
    existing_user = await User.find_one(User.email == email)

    if existing_user:
        logger.info(f"User with email {email} already exists.")

        # Update superuser status if needed
        if not existing_user.is_superuser:
            existing_user.is_superuser = True
            await existing_user.save()
            logger.info(f"Updated user {email} to have superuser privileges.")

        return existing_user

    # Create password hash
    password_helper = PasswordHelper()
    hashed_password = password_helper.hash(password)

    # Create the admin user
    admin_user = User(
        email=email,
        hashed_password=hashed_password,
        first_name=first_name,
        last_name=last_name,
        is_active=True,
        is_verified=True,
        is_superuser=True,
    )

    await admin_user.save()
    logger.info(f"Created admin user: {email}")

    return admin_user


async def create_default_groups():
    # Check if we have any groups already
    count = await Group.count()
    if count > 0:
        logger.info(f"Found {count} existing groups. Skipping default group creation.")
        return

    # Create some default groups
    default_groups = [
        {
            "name": "Administrators",
            "description": "Full access to all features",
            "permissions": ["admin", "create", "read", "update", "delete"],
        },
        {
            "name": "Editors",
            "description": "Can edit content but not administrative features",
            "permissions": ["create", "read", "update"],
        },
        {"name": "Viewers", "description": "Read-only access", "permissions": ["read"]},
    ]

    for group_data in default_groups:
        group = Group(**group_data)
        await group.save()
        logger.info(f"Created group: {group.name}")


async def main():
    try:
        # You can change these values as needed
        admin_email = "admin@example.com"
        admin_password = "adminpassword"  # Use a secure password in production!

        # Create admin user
        user = await create_admin_user(
            email=admin_email,
            password=admin_password,
            first_name="Admin",
            last_name="User",
        )

        # Create default groups
        await create_default_groups()

        logger.info(f"Admin user created or updated: {user.email}")
        logger.info("You can now log in to the admin interface at /admin/login")

    except Exception as e:
        logger.error(f"Error in setup: {e}")


if __name__ == "__main__":
    asyncio.run(main())
