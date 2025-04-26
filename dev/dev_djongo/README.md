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
└── requirements.txt            # Project dependencies
```

## Technologies Used

- **Django**: Authentication backend with Django REST Framework
- **MongoDB**: Database for storing user data and application data
- **Djongo**: MongoDB adapter for Django
- **Dash**: Frontend UI framework
- **JWT**: Token-based authentication

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

## Authentication Flow

1. User opens the Dash application
2. User clicks "Login" or "Register" in the header
3. Authentication modal appears
4. User submits credentials
5. Dash sends credentials to Django auth service via API
6. Django validates credentials and returns JWT tokens
7. Dash stores tokens in browser local storage
8. Protected routes check for valid tokens
9. On logout, tokens are removed from browser storage (client-side logout)

## API Endpoints

- `/api/auth/register/` - Register a new user
- `/api/auth/token/` - Obtain JWT tokens
- `/api/auth/token/refresh/` - Refresh JWT token
- `/api/auth/user/` - Get current user details
- `/api/auth/logout/` - Logout (client-side token removal)

## Development Notes

- Django is used solely for authentication and does not serve any UI
- Dash handles all UI rendering, including authentication forms
- Communication between Dash and Django happens via REST API
- Both services connect to the same MongoDB instance
- Token blacklisting is not used due to compatibility issues with Djongo
- Logout is handled client-side by removing tokens from storage
