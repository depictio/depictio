# Simplified Authentication Setup

This document explains the simplified authentication setup using django-allauth and Google OAuth.

## Overview

The authentication system has been simplified to use django-allauth's built-in features without custom implementations. This approach:

1. Uses django-allauth's models directly (SocialAccount, EmailAddress, etc.)
2. Uses django-allauth's default views and URLs
3. Adds a simple success view to handle the redirect after successful authentication

## How It Works

1. The user clicks "Login with Google" in the Dash frontend
2. They are redirected to django-allauth's Google login URL
3. After successful authentication with Google, django-allauth redirects to the success URL
4. The success view generates JWT tokens and redirects to the Dash frontend with the tokens as URL parameters
5. The Dash frontend stores the tokens and uses them for subsequent API requests

## Setup Instructions

1. Make sure you have a Google OAuth client set up in the Google Cloud Console
2. Configure the client ID and secret in `settings.py`
3. Run migrations to create the necessary database tables
4. Create a superuser to access the Django admin
5. Configure the site in the Django admin
6. Configure the social application in the Django admin

## Wiping the Database

If you need to start fresh, you can use the `wipe_db` management command:

```bash
cd django_auth
python manage.py wipe_db
```

This will delete all authentication-related data from the database, including:
- SocialToken objects
- SocialAccount objects
- EmailAddress objects
- User objects (except superusers)

## Testing the Authentication

1. Start both servers:
```bash
# Terminal 1 - Django server
cd django_auth
python manage.py runserver 8000

# Terminal 2 - Dash server
cd dash_frontend
python app.py
```

2. Open your browser and go to `http://localhost:8050/`
3. Click "Login" and then "Login with Google"
4. You should be redirected to Google's authentication page
5. After successful authentication, you should be redirected back to the Dash application and logged in

## Troubleshooting

- If you encounter errors, check the Django server logs for details
- Make sure the redirect URIs are correctly configured in the Google Cloud Console
- Make sure the site and social application are correctly configured in the Django admin
- If you continue to have issues, try wiping the database and starting fresh
