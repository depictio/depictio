
import requests

# Django auth service base URL
AUTH_API_BASE_URL = "http://localhost:8000/api/auth"


def register_user(username, email, password, password2, first_name, last_name):
    """
    Register a new user by sending a POST request to the Django auth service
    """
    url = f"{AUTH_API_BASE_URL}/register/"
    payload = {
        "username": username,
        "email": email,
        "password": password,
        "password2": password2,
        "first_name": first_name,
        "last_name": last_name,
    }
    headers = {"Content-Type": "application/json"}

    try:
        print(f"Sending registration request with payload: {payload}")
        response = requests.post(url, json=payload, headers=headers)

        if response.status_code == 201:
            return response.status_code, response.json()
        else:
            # Try to parse as JSON first, fall back to text if that fails
            try:
                error_data = response.json()
                print(f"Registration error: {error_data}")
                # Format the error message for better display
                if isinstance(error_data, dict):
                    error_messages = []
                    for field, errors in error_data.items():
                        if isinstance(errors, list):
                            for error in errors:
                                error_messages.append(f"{field}: {error}")
                        else:
                            error_messages.append(f"{field}: {errors}")
                    return response.status_code, " | ".join(error_messages)
                return response.status_code, str(error_data)
            except Exception as parse_error:
                print(f"Error parsing response: {parse_error}")
                return response.status_code, response.text
    except Exception as e:
        print(f"Exception during registration: {e}")
        return 500, str(e)


def login_user(username, password):
    """
    Login a user by sending a POST request to the Django auth service
    Returns JWT tokens on success
    """
    url = f"{AUTH_API_BASE_URL}/token/"
    payload = {"username": username, "password": password}
    headers = {"Content-Type": "application/json"}

    try:
        response = requests.post(url, json=payload, headers=headers)
        if response.status_code == 200:
            return response.status_code, response.json()
        else:
            # Try to parse as JSON first, fall back to text if that fails
            try:
                return response.status_code, response.json()
            except:
                return response.status_code, response.text
    except Exception as e:
        return 500, str(e)


def logout_user(access_token):
    """
    Logout a user by calling the logout endpoint
    The actual token invalidation happens client-side
    """
    url = f"{AUTH_API_BASE_URL}/logout/"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {access_token}"}

    try:
        response = requests.post(url, headers=headers)
        return (
            response.status_code,
            "Logout successful" if response.status_code == 200 else response.text,
        )
    except Exception as e:
        return 500, str(e)


def get_user_details(access_token):
    """
    Get user details using the access token
    """
    url = f"{AUTH_API_BASE_URL}/user/"
    headers = {"Authorization": f"Bearer {access_token}"}

    try:
        response = requests.get(url, headers=headers)
        return (
            response.status_code,
            response.json() if response.status_code == 200 else response.text,
        )
    except Exception as e:
        return 500, str(e)


def refresh_token(refresh_token):
    """
    Refresh the access token using the refresh token
    """
    url = f"{AUTH_API_BASE_URL}/token/refresh/"
    payload = {"refresh": refresh_token}

    try:
        response = requests.post(url, json=payload)
        return (
            response.status_code,
            response.json() if response.status_code == 200 else response.text,
        )
    except Exception as e:
        return 500, str(e)


def google_login():
    """
    Initiate Google OAuth login by redirecting to the Django auth service
    """
    # Use the django-allauth URL directly
    url = "http://localhost:8000/accounts/google/login/"
    return url
