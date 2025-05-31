# Set the IP address to allow access from any IP
c.ServerApp.ip = "0.0.0.0"

# Allow the server to be run as root
c.ServerApp.allow_root = True

# Disable launching a browser on start
c.ServerApp.open_browser = False

# Disable token authentication (not recommended for production)
c.ServerApp.token = ""

# Disable password protection (not recommended for production)
c.ServerApp.password = ""

# Allow connections from any origin
c.ServerApp.allow_origin = "*"

# Disable XSRF protection (only do this in a secure and trusted environment)
c.ServerApp.disable_check_xsrf = True
