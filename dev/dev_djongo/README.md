# Dash + Django Auth + MongoDB Architecture

This project demonstrates an architecture where:

- Django handles only authentication, storing user data in MongoDB
- Dash provides the UI, including authentication forms in Dash modals
- MongoDB stores everything (auth and app data)

## Project Structure

```
dev_djongo/
├── django_auth/                # Django authentication service
│   ├── auth_service/           # Django project settings
│   └── authentication/         # Django app for authentication
├── dash_frontend/              # Dash frontend application
│   ├── app.py                  # Main Dash application
│   ├── api_calls.py            # API calls to Django auth service
│   ├── auth_modals.py          # Authentication modals (login/register)
│   ├── callbacks.py            # Dash callbacks
│   ├── header.py               # Header component
│   └── layouts.py              # Page layouts
├── requirements.txt            # Project dependencies
├── README.md                   # Main project documentation
└── GOOGLE_AUTH_SETUP.md        # Google OAuth setup instructions
```

## Technologies Used

- **Django**: Authentication backend with Django REST Framework
- **MongoDB**: Database for storing user data and application data
- **Djongo**: MongoDB adapter for Django
- **Dash**: Frontend UI framework
- **JWT**: Token-based authentication
- **django-allauth**: Social authentication (Google OAuth)

## Setup Instructions

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Start MongoDB

Make sure MongoDB is running on localhost:27018.

### 3. Run Django Auth Service

```bash
cd django_auth
python manage.py migrate
python manage.py createsuperuser  # Create an admin user
python manage.py runserver 8000
```

### 4. Run Dash Frontend

```bash
cd dash_frontend
python app.py
```

The Dash application will be available at http://localhost:8050

### 5. Google OAuth Setup (Optional)

For Google OAuth integration, follow the detailed instructions in [GOOGLE_AUTH_SETUP.md](GOOGLE_AUTH_SETUP.md).

This includes:
1. Creating a Google OAuth client in Google Cloud Console
2. Configuring Django settings with your OAuth credentials
3. Setting up the Django admin site for social authentication
4. Testing the Google login flow

## Authentication Flow

### Standard Authentication
1. User opens the Dash application
2. User clicks "Login" or "Register" in the header
3. Authentication modal appears
4. User submits credentials
5. Dash sends credentials to Django auth service via API
6. Django validates credentials and returns JWT tokens
7. Dash stores tokens in browser local storage
8. Protected routes check for valid tokens
9. On logout, tokens are removed from browser storage (client-side logout)

### Google OAuth Authentication
1. User opens the Dash application
2. User clicks "Login" in the header
3. Login modal appears
4. User clicks "Login with Google" button
5. User is redirected to Google's authentication page
6. After successful authentication with Google, user is redirected back to the application
7. Django processes the OAuth callback and generates JWT tokens
8. User is redirected to the Dash frontend with tokens as URL parameters
9. Dash stores the tokens in browser local storage
10. Protected routes check for valid tokens
11. On logout, tokens are removed from browser storage (client-side logout)

## API Endpoints

- `/api/auth/register/` - Register a new user
- `/api/auth/token/` - Obtain JWT tokens
- `/api/auth/token/refresh/` - Refresh JWT token
- `/api/auth/user/` - Get current user details
- `/api/auth/logout/` - Logout (client-side token removal)
- `/api/auth/google/login/` - Initiate Google OAuth login
- `/api/auth/google/callback/` - Google OAuth callback endpoint
- `/accounts/` - Django-allauth URLs for social authentication

## Development Notes

- Django is used solely for authentication and does not serve any UI
- Dash handles all UI rendering, including authentication forms
- Communication between Dash and Django happens via REST API
- Both services connect to the same MongoDB instance
- Token blacklisting is not used due to compatibility issues with Djongo
- Logout is handled client-side by removing tokens from storage
