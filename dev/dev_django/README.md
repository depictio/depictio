# Django Plotly Dash Example

This is a minimal example application that combines Django and Plotly Dash, showcasing user authentication and a simple dashboard.

## Features

- User authentication (login/logout)
- Admin interface for user management
- Interactive Plotly Dash visualization
- Simple dashboard UI

## Installation

1. Create a virtual environment:
   ```
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

2. Install the required packages:
   ```
   pip install -r requirements.txt
   ```

## Running the Application

Run the application with:

```
python app.py
```

The application will start two servers:
- Django server at http://localhost:8000
- Dash server at http://localhost:8050

The Django server handles user authentication and the main application, while the Dash server provides the interactive visualization that is embedded in the Django dashboard.

## Default Admin User

A default admin user is created automatically:
- Username: `admin`
- Password: `adminpassword`

## Accessing the Django Admin Interface

1. Log in with the admin credentials at http://localhost:8000/login/
2. Once logged in, you can access the admin interface at http://localhost:8000/admin/
3. In the admin interface, you can:
   - View all users by clicking on "Users" under the "Authentication and Authorization" section
   - Create new users by clicking the "Add" button
   - Edit existing users by clicking on their username
   - Delete users by selecting them and choosing "Delete selected users" from the action dropdown

## User Management via Admin Interface

### Listing Users
- Go to http://localhost:8000/admin/
- Click on "Users" under "Authentication and Authorization"
- You'll see a list of all users in the system

### Creating a New User
- From the Users list, click "Add user" in the top right
- Enter a username and password, then click "Save"
- On the next page, you can add additional details like email, first name, last name
- You can also set permissions, including making the user a superuser or staff member
- Click "Save" to create the user

### Editing a User
- From the Users list, click on the username you want to edit
- You can modify any user details, including:
  - Personal info (first name, last name, email)
  - Permissions (superuser status, staff status, active status)
  - Group memberships
  - User permissions
- Click "Save" to apply your changes

### Deleting Users
- From the Users list, select the checkbox next to the user(s) you want to delete
- From the "Action" dropdown at the top, select "Delete selected users"
- Click "Go" to confirm
- On the confirmation page, click "Yes, I'm sure" to permanently delete the user(s)

## Application Structure

- `app.py`: Main application file that configures Django settings, defines views, and sets up the Dash application
- `templates/`: Contains HTML templates for the application
  - `login.html`: Login page template
  - `dashboard.html`: Dashboard page template with Dash integration via iframe
- `static/`: Directory for static files (CSS, JavaScript, images)
- `requirements.txt`: List of Python dependencies

## How It Works

1. The application uses Django's authentication system for user management
2. Plotly Dash runs in a separate thread and is embedded in the Django dashboard via an iframe
3. The dashboard page displays an interactive Plotly visualization
4. Admin users can access the Django admin interface to manage users
