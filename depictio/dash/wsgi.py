# This file serves as the WSGI entry point for Gunicorn
# It imports the Flask server instance from the Dash app


# The 'server' variable is the Flask server instance that Gunicorn will use
# In app.py, it's defined as: server = app.server

if __name__ == "__main__":
    # This block won't be executed when run with Gunicorn
    # It's here for potential direct execution
    pass
