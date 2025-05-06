# Flask-Dash Authentication Example

This is a sample application that demonstrates how to integrate Flask authentication with Plotly Dash. It provides a complete user management system with login, registration, and admin functionality, all built using Dash components for the UI.

## Features

- User authentication (login/logout)
- User registration
- Admin panel for user management
- Interactive Dash analytics dashboard
- SQLite database for user storage
- RESTful API endpoints for authentication and user management

## Installation

1. Clone the repository or download the source code
2. Create a virtual environment and activate it:
   ```
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```
3. Install the required packages:
   ```
   pip install -r requirements.txt
   ```

## Running the Application

To run the application, execute:

```
python app.py
```

The application will be available at http://127.0.0.1:8050/

## Default Admin Account

The application automatically creates an admin user on first run:

- Username: `admin`
- Password: `admin`

## User Management

### Accessing the Admin Panel

1. Log in with the admin account
2. Click on the "Admin" link in the navigation bar
3. The admin panel displays a list of all users in the system
4. You can delete users from this panel (except your own account)

### User Database

The application uses SQLite for data storage. The database file is created automatically at `users.db` in the application directory.

## API Endpoints

The application provides several RESTful API endpoints for authentication and user management:

- `/login` (POST): Authenticate a user
- `/register` (POST): Register a new user
- `/logout` (GET): Log out the current user
- `/check-auth` (GET): Check if a user is authenticated
- `/users` (GET): Get a list of all users (admin only)
- `/users/<user_id>` (DELETE): Delete a user (admin only)

## Application Structure

- `app.py`: Main application file containing both Flask and Dash components
- `requirements.txt`: List of required packages
- `users.db`: SQLite database file (created automatically)

## How It Works

This application demonstrates how to:

1. Use Flask-Login for authentication
2. Integrate Flask-Login with Dash
3. Create a multi-page Dash application
4. Protect routes based on authentication status
5. Implement user management functionality
6. Use Dash callbacks for dynamic UI updates
7. Communicate between Flask and Dash components

## Customization

You can customize this application by:

- Modifying the UI components in the Dash layouts
- Adding more data visualizations to the analytics dashboard
- Extending the user model with additional fields
- Implementing additional user management features
- Connecting to a different database backend

## Security Notes

This is a demonstration application and includes some simplifications:

- The secret key is hardcoded (in a production app, use environment variables)
- Password hashing is basic (consider using more secure methods in production)
- No CSRF protection is implemented
- No rate limiting on login attempts
