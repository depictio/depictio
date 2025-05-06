# Setting Up Google OAuth for Django/Dash Application

This guide explains how to set up Google OAuth authentication for the Django/Dash application.

## 1. Create a Google OAuth Client

1. Go to the [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select an existing one
3. Navigate to "APIs & Services" > "OAuth consent screen"
4. Configure the OAuth consent screen:
   - User Type: External (or Internal if you're using Google Workspace)
   - App name: Your application name
   - User support email: Your email
   - Developer contact information: Your email
   - Authorized domains: Add your domain (for development, you can use localhost)
   - Add scopes: email and profile
5. Save and continue through all steps
6. Navigate to "Credentials" and click "Create Credentials" > "OAuth client ID"
7. Create OAuth client ID:
   - Application type: Web application
   - Name: Your application name
   - Authorized JavaScript origins: `http://localhost:8000` (Django server)
   - Authorized redirect URIs: `http://localhost:8000/api/auth/google/callback/`
8. Click "Create"
9. Note your Client ID and Client Secret

## 2. Configure Django Settings

1. Open `django_auth/auth_service/settings.py`
2. Update the `SOCIALACCOUNT_PROVIDERS` section with your Google OAuth credentials:

```python
SOCIALACCOUNT_PROVIDERS = {
    'google': {
        'APP': {
            'client_id': 'YOUR_CLIENT_ID',  # Replace with your client ID
            'secret': 'YOUR_CLIENT_SECRET',  # Replace with your client secret
            'key': ''
        },
        'SCOPE': [
            'profile',
            'email',
        ],
        'AUTH_PARAMS': {
            'access_type': 'online',
        }
    }
}
```

## 3. Run Migrations and Create a Django Superuser

1. Run the following commands to apply migrations with the `--fake` flag to skip problematic migrations:
```bash
cd django_auth
python manage.py migrate auth
python manage.py migrate contenttypes
python manage.py migrate admin
python manage.py migrate sessions
python manage.py migrate sites --fake
python manage.py migrate account --fake
python manage.py migrate socialaccount --fake
python manage.py migrate authentication
```

2. Create a superuser:
```bash
python manage.py createsuperuser
```

3. Follow the prompts to create a superuser account

## 4. Configure Site in Django Admin

1. Start the Django server:
```bash
python manage.py runserver 8000
```

2. Go to `http://localhost:8000/admin/` and log in with your superuser credentials
3. Navigate to "Sites" and edit the default site:
   - Domain name: `localhost:8000`
   - Display name: `localhost`
4. Save the changes

## 5. Configure Social Application

1. In the Django admin, navigate to "Social Applications"
2. Click "Add Social Application"
3. Fill in the following details:
   - Provider: Google
   - Name: Google OAuth
   - Client ID: Your Google OAuth client ID
   - Secret key: Your Google OAuth client secret
   - Sites: Add `localhost:8000` to the chosen sites
4. Save the social application

## 6. Testing the Integration

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

- If you encounter CSRF errors, make sure your domain is correctly set up in the Django admin site
- If the redirect fails, check that your redirect URI is correctly configured in the Google Cloud Console
- Check the Django server logs for any error messages
- Ensure that the Google OAuth client is properly configured with the correct redirect URIs
