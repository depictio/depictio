# app.py - EMBL SAML Integration with FastAPI and Beanie
import os
import json
import logging
import urllib.parse
from typing import Optional, AsyncGenerator, Dict, Any
import motor.motor_asyncio
from pydantic import EmailStr
from beanie import Document, init_beanie
from fastapi import FastAPI, Request, Response, Depends
from fastapi.responses import RedirectResponse, HTMLResponse
from onelogin.saml2.auth import OneLogin_Saml2_Auth
from onelogin.saml2.metadata import OneLogin_Saml2_Metadata
from contextlib import asynccontextmanager
from dotenv import load_dotenv
# FastAPI-Users with Beanie
from fastapi_users import FastAPIUsers, schemas, models
from fastapi_users.authentication import (
    AuthenticationBackend,
    BearerTransport,
    JWTStrategy,
)
from fastapi_users.db import BeanieUserDatabase
from fastapi_users.exceptions import UserNotExists
from fastapi_users.manager import BaseUserManager

load_dotenv()

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger("saml_app")

# --- MongoDB / Beanie configuration ---
MONGODB_URL = "mongodb://localhost:27018"
DATABASE_NAME = "fastapiusers_saml_test"

# --- User model with Beanie ---
class UserModel(Document):
    email: EmailStr
    hashed_password: str = ""
    is_active: bool = True
    is_superuser: bool = False
    is_verified: bool = False
    username: Optional[str] = None

    class Settings:
        name = "users"

# FastAPI-Users schemas
class UserRead(schemas.BaseUser[str]):
    username: Optional[str] = None

class UserCreate(schemas.BaseUserCreate):
    username: Optional[str] = None

# --- Load SAML configuration from environment ---
IDP_SSO_URL       = os.getenv("CMD_SAML_IDPSSOURL")
IDP_CERT_PATH     = os.getenv("CMD_SAML_IDPCERT")
SP_ENTITY_ID      = os.getenv("CMD_SAML_ISSUER")
ATTR_ID           = os.getenv("CMD_SAML_ATTRIBUTE_ID")
ATTR_USERNAME     = os.getenv("CMD_SAML_ATTRIBUTE_USERNAME")
ATTR_EMAIL        = os.getenv("CMD_SAML_ATTRIBUTE_EMAIL")
NAMEID_FORMAT     = os.getenv("CMD_SAML_IDENTIFIERFORMAT")

# Read the IdP certificate
with open(IDP_CERT_PATH, "r") as cert_file:
    IDP_CERT = cert_file.read()
    logger.info(f"IDP CERT loaded from {IDP_CERT_PATH}")

# Get the callback URL (with base URL detection)
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")
ACS_URL = f"{BASE_URL}/auth/saml/callback"

# Log all config values to help debug
logger.info(f"SAML Configuration:")
logger.info(f"SP_ENTITY_ID: {SP_ENTITY_ID}")
logger.info(f"IDP_SSO_URL: {IDP_SSO_URL}")
logger.info(f"BASE_URL: {BASE_URL}")
logger.info(f"ACS_URL: {ACS_URL}")
logger.info(f"NAMEID_FORMAT: {NAMEID_FORMAT}")

# --- Build python3-saml settings ---
saml_settings = {
    "strict": True,
    "debug": True,
    "sp": {
        "entityId": SP_ENTITY_ID,
        "assertionConsumerService": {
            "url": ACS_URL,
            "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST",
        },
        "NameIDFormat": NAMEID_FORMAT,
        "x509cert": "",
        "privateKey": ""
    },
    "idp": {
        "entityId": "https://auth.ktest.embl.de/realms/EMBL-HD",
        "singleSignOnService": {
            "url": IDP_SSO_URL, 
            "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect"
        },
        "singleLogoutService": {
            "url": IDP_SSO_URL,
            "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect"
        },
        "x509cert": IDP_CERT,
    },
    "security": {
        "authnRequestsSigned": False,  # Changed to match IdP metadata requirement
        "wantAssertionsSigned": True,
        "wantMessagesSigned": False,   # Changed to match IdP metadata
        "wantAttributeStatement": True,
        "allowSingleLabelDomains": True,
        "nameIdEncrypted": False,
        "requestedAuthnContext": False,
    },
    "contactPerson": {
        "technical": {
            "givenName": "Technical Contact",
            "emailAddress": "technical@example.com"
        },
        "support": {
            "givenName": "Support Contact",
            "emailAddress": "support@example.com"
        }
    },
    "organization": {
        "en-US": {
            "name": "Depictio SAML Test",
            "displayname": "Depictio SAML Test",
            "url": BASE_URL
        }
    }
}

# --- JWT Authentication setup ---
JWT_SECRET = os.getenv("JWT_SECRET", "CHANGE_ME")
bearer_transport = BearerTransport(tokenUrl="auth/jwt/login")
jwt_strategy = JWTStrategy(secret=JWT_SECRET, lifetime_seconds=3600)

auth_backend = AuthenticationBackend(
    name="jwt",
    transport=bearer_transport,
    get_strategy=lambda: jwt_strategy,
)

# Get database dependency
async def get_user_db() -> AsyncGenerator[BeanieUserDatabase, None]:
    yield BeanieUserDatabase(UserModel)

# User manager for operations
class UserManager(BaseUserManager[UserModel, str]):
    reset_password_token_secret = JWT_SECRET
    verification_token_secret = JWT_SECRET

    async def get_or_create_saml_user(
        self, email: str, username: Optional[str] = None
    ) -> UserModel:
        try:
            user = await self.get_by_email(email)
            logger.info(f"Found existing user: email={email}, id={user.id}, username={user.username}")
            return user
        except UserNotExists:
            logger.info(f"Creating new user: email={email}, username={username}")
            
            # Create password hash for a random password
            import secrets
            password = secrets.token_urlsafe(32)
            hashed_password = self.password_helper.hash(password)
            
            # Create user
            user_dict = {
                "email": email,
                "hashed_password": hashed_password,
                "is_active": True,
                "is_verified": True,  # SAML authenticated users are verified
                "is_superuser": False,
                "username": username,
            }
            created_user = await self.create(user_dict)
            logger.info(f"Created new user: id={created_user.id}, email={email}, username={username}")
            return created_user
            
    async def on_after_register(self, user: UserModel, request: Optional[Request] = None):
        logger.info(f"User registered: id={user.id}, email={user.email}, username={user.username}")
        
    async def on_after_login(
        self, user: UserModel, request: Optional[Request] = None
    ):
        logger.info(f"User logged in: id={user.id}, email={user.email}, username={user.username}")
        
    async def on_before_request(
        self, user: Optional[UserModel], request: Optional[Request] = None
    ):
        if user:
            logger.info(f"Request from authenticated user: id={user.id}, email={user.email}")
        else:
            logger.info("Request from unauthenticated user")

async def get_user_manager(user_db=Depends(get_user_db)):
    yield UserManager(user_db)

# Create MongoDB client
client = motor.motor_asyncio.AsyncIOMotorClient(MONGODB_URL)
db = client[DATABASE_NAME]

# Lifespan for FastAPI
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting application - initializing database connection")
    await init_beanie(
        database=db,
        document_models=[UserModel],
    )
    logger.info("Database connection initialized successfully")
    
    # Log the SAML settings
    logger.info(f"SAML SP Entity ID: {SP_ENTITY_ID}")
    logger.info(f"SAML ACS URL: {ACS_URL}")
    logger.info(f"SAML IdP URL: {IDP_SSO_URL}")
    
    yield
    logger.info("Shutting down application")

# Create app with lifespan context manager
app = FastAPI(lifespan=lifespan)

# Initialize FastAPI Users
fastapi_users = FastAPIUsers[UserModel, str](
    get_user_manager,
    [auth_backend],
)

# Include FastAPI Users routers
app.include_router(
    fastapi_users.get_auth_router(auth_backend),
    prefix="/auth/jwt",
    tags=["auth"],
)

# Helper to initialize OneLogin SAML
async def init_saml_auth(request: Request) -> OneLogin_Saml2_Auth:
    url = request.url
    logger.info(f"Initializing SAML auth for request: {request.method} {url}")
    
    # Handle form data for POST requests
    form_data = []
    if request.method == "POST":
        form = await request.form()
        form_data = [(k, v) for k, v in form.items()]
        logger.info(f"POST data keys: {[k for k, _ in form_data]}")
    
    # Build the request data for python3-saml
    data = {
        "https": "on" if url.scheme == "https" else "off",
        "http_host": url.hostname,
        "server_port": str(url.port or (443 if url.scheme == "https" else 80)),
        "script_name": request.url.path,
        "get_data": [(k, v) for k, v in request.query_params.items()],
        "post_data": form_data,
        # Add base path 
        "base_url": str(request.base_url).rstrip("/"),
    }
    logger.info(f"SAML auth request data: {json.dumps(data, default=str)}")
    return OneLogin_Saml2_Auth(data, saml_settings)

# Generate SP metadata
@app.get("/auth/saml/metadata")
async def saml_metadata():
    """Generate SP metadata for IdP configuration"""
    try:
        # Use custom approach to build metadata as a workaround
        entity_id = saml_settings["sp"]["entityId"]
        acs_url = saml_settings["sp"]["assertionConsumerService"]["url"]
        binding = saml_settings["sp"]["assertionConsumerService"]["binding"]
        nameid_format = saml_settings["sp"]["NameIDFormat"]
        
        metadata_xml = f"""<?xml version="1.0"?>
<md:EntityDescriptor xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata" entityID="{entity_id}">
  <md:SPSSODescriptor AuthnRequestsSigned="false" WantAssertionsSigned="true" protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">
    <md:NameIDFormat>{nameid_format}</md:NameIDFormat>
    <md:AssertionConsumerService Binding="{binding}" Location="{acs_url}" index="1"/>
  </md:SPSSODescriptor>
  <md:Organization>
    <md:OrganizationName xml:lang="en-US">Depictio SAML Test</md:OrganizationName>
    <md:OrganizationDisplayName xml:lang="en-US">Depictio SAML Test</md:OrganizationDisplayName>
    <md:OrganizationURL xml:lang="en-US">{BASE_URL}</md:OrganizationURL>
  </md:Organization>
  <md:ContactPerson contactType="technical">
    <md:GivenName>Technical Contact</md:GivenName>
    <md:EmailAddress>technical@example.com</md:EmailAddress>
  </md:ContactPerson>
  <md:ContactPerson contactType="support">
    <md:GivenName>Support Contact</md:GivenName>
    <md:EmailAddress>support@example.com</md:EmailAddress>
  </md:ContactPerson>
</md:EntityDescriptor>
"""
        logger.info(f"Generated SAML metadata for SP: {entity_id}")
        return Response(content=metadata_xml, media_type="text/xml")
    except Exception as e:
        logger.error(f"Error generating metadata: {e}")
        return {"error": str(e)}

# 1) AuthnRequest endpoint - Redirect to IdP
@app.get("/auth/saml/login")
async def saml_login(request: Request, RelayState: Optional[str] = None):
    logger.info(f"SAML login initiated from: {request.client.host if request.client else 'unknown'}")
    
    # Use frontend URL as RelayState instead of callback URL
    if not RelayState:
        RelayState = f"{BASE_URL}/auth-success"
    
    logger.info(f"Using RelayState: {RelayState}")
    
    auth = await init_saml_auth(request)
    
    # Try to log the SAML request but don't error if not available
    try:
        if hasattr(auth, 'get_last_request_xml'):
            saml_request = auth.get_last_request_xml()
            logger.info(f"SAML AuthnRequest XML: {saml_request}")
    except Exception as e:
        logger.warning(f"Could not get SAML request XML: {e}")
    
    # Pass explicit parameters to control the SAML request
    try:
        login_url = auth.login(return_to=RelayState)
        logger.info(f"Redirecting to IdP: {login_url}")
        
        # For debugging, you can directly print the URL in browser:
        html_content = f"""
        <!DOCTYPE html>
        <html>
            <head>
                <title>Redirecting to EMBL Login</title>
                <meta http-equiv="refresh" content="0;url={login_url}">
            </head>
            <body>
                <h1>Redirecting to EMBL Login</h1>
                <p>If you are not redirected automatically, click <a href="{login_url}">here</a>.</p>
                <p>Debug info: <pre>{login_url}</pre></p>
            </body>
        </html>
        """
        return HTMLResponse(content=html_content)
    except Exception as e:
        logger.error(f"Error during SAML login: {e}")
        return {"error": str(e)}

# 2) ACS endpoint - Process SAML Response
@app.post("/auth/saml/callback")
async def saml_callback(
    request: Request,
    user_manager: UserManager = Depends(get_user_manager),
):
    logger.info("Received SAML callback")
    
    try:
        auth = await init_saml_auth(request)
        
        auth.process_response()
        errors = auth.get_errors()
        
        if errors:
            error_reason = auth.get_last_error_reason()
            logger.error(f"SAML authentication errors: {errors}, reason: {error_reason}")
            return {"errors": errors, "reason": error_reason}

        # Extract attributes
        attrs = auth.get_attributes()
        nameid = auth.get_nameid()
        
        # Log all SAML data for debugging
        logger.info(f"SAML NameID: {nameid}")
        logger.info(f"SAML Attributes: {json.dumps(attrs, default=str)}")
        
        # Get user information from SAML attributes
        email = attrs.get(ATTR_EMAIL, [None])[0] if attrs else nameid
        username = attrs.get(ATTR_USERNAME, [None])[0] if attrs else None
        
        # Log all attribute mappings
        for attr_name, attr_key in [
            ("Email", ATTR_EMAIL), 
            ("Username", ATTR_USERNAME), 
            ("ID", ATTR_ID)
        ]:
            attr_value = attrs.get(attr_key, ["NOT_FOUND"])[0] if attrs else "NOT_FOUND"
            logger.info(f"SAML {attr_name} ({attr_key}): {attr_value}")
        
        if not email:
            # Try with nameid if email attribute not found
            logger.warning("Email not found in attributes, using NameID instead")
            email = nameid
            
        if not email:
            logger.error("Email not provided by IdP")
            return {"error": "Email not provided by IdP"}

        logger.info(f"Processing authentication for email: {email}, username: {username}")
        
        # Get or create user in our system
        user = await user_manager.get_or_create_saml_user(email, username)
        
        # Generate JWT token
        token_data = {
            "sub": str(user.id),
            "aud": "fastapi-users:auth",
        }
        logger.info(f"Generating token with data: {token_data}")
        token = jwt_strategy.write_token(token_data)
        
        logger.info(f"Authentication successful for user: {user.email}")
        
        # Get the RelayState from the request
        form_data = await request.form()
        relay_state = form_data.get("RelayState", "/auth-success")
        
        # Append token to the relay state URL
        if "?" in relay_state:
            redirect_url = f"{relay_state}&token={token}"
        else:
            redirect_url = f"{relay_state}?token={token}"
            
        logger.info(f"Redirecting to: {redirect_url}")
        
        # Return HTML response with auto-redirect to frontend
        html_content = f"""
        <!DOCTYPE html>
        <html>
            <head>
                <title>Authentication Successful</title>
                <meta http-equiv="refresh" content="0;url={redirect_url}">
            </head>
            <body>
                <h1>Authentication Successful</h1>
                <p>Redirecting to application...</p>
                <p>If you are not redirected, <a href="{redirect_url}">click here</a></p>
                <script>
                    window.location.href = "{redirect_url}";
                </script>
            </body>
        </html>
        """
        
        return HTMLResponse(content=html_content)
    except Exception as e:
        logger.error(f"Error in SAML callback: {str(e)}")
        return {"error": str(e)}

# Success page after SAML authentication
@app.get("/auth-success")
async def auth_success(token: Optional[str] = None):
    """Success page after SAML authentication"""
    if token:
        return {
            "status": "success",
            "message": "Authentication successful",
            "access_token": token,
            "token_type": "bearer",
        }
    else:
        return {
            "status": "waiting",
            "message": "Waiting for authentication token",
        }

# Protected route example
@app.get("/protected")
async def protected_route(user: UserModel = Depends(fastapi_users.current_user(active=True))):
    logger.info(f"Protected route accessed by user: id={user.id}, email={user.email}")
    
    # Log all user fields for debugging
    user_data = {
        "id": str(user.id),
        "email": user.email,
        "username": user.username,
        "is_active": user.is_active,
        "is_verified": user.is_verified,
        "is_superuser": user.is_superuser
    }
    logger.info(f"User data: {json.dumps(user_data)}")
    
    return {
        "message": f"Hello {user.username or user.email}",
        "email": user.email,
        "user_details": user_data
    }

# Add a user info endpoint
@app.get("/me")
async def read_users_me(user: UserModel = Depends(fastapi_users.current_user())):
    logger.info(f"User info requested: id={user.id}, email={user.email}")
    return {
        "id": str(user.id),
        "email": user.email,
        "username": user.username,
        "is_active": user.is_active,
        "is_verified": user.is_verified,
        "is_superuser": user.is_superuser
    }

# Add a debug endpoint to dump request info
@app.get("/debug/request")
async def debug_request(request: Request):
    """Debug endpoint to log request details"""
    client_host = request.client.host if request.client else "unknown"
    headers = dict(request.headers)
    
    # Sanitize headers for logging (remove sensitive info)
    if "authorization" in headers:
        headers["authorization"] = "REDACTED"
    
    req_info = {
        "method": request.method,
        "url": str(request.url),
        "client_host": client_host,
        "headers": headers,
        "query_params": dict(request.query_params),
    }
    
    logger.info(f"Debug request: {json.dumps(req_info)}")
    return req_info

# Add endpoint to test token verification
@app.get("/debug/token")
async def debug_token(user: UserModel = Depends(fastapi_users.current_user())):
    """Debug endpoint to verify token and show payload"""
    logger.info(f"Token debug for user: {user.email}")
    return {
        "valid": True,
        "user_id": str(user.id),
        "email": user.email,
    }

@app.get("/debug/config")
async def debug_config():
    """Show SAML configuration for debugging"""
    try:
        cert_loaded = "LOADED" if IDP_CERT and IDP_CERT.strip() else "NOT LOADED"
        return {
            "SP_ENTITY_ID": SP_ENTITY_ID,
            "IDP_SSO_URL": IDP_SSO_URL,
            "BASE_URL": BASE_URL,
            "ACS_URL": ACS_URL,
            "ATTR_EMAIL": ATTR_EMAIL,
            "ATTR_USERNAME": ATTR_USERNAME,
            "ATTR_ID": ATTR_ID,
            "NAMEID_FORMAT": NAMEID_FORMAT,
            "IDP_CERT": cert_loaded,
            "IDP_CERT_PATH": IDP_CERT_PATH,
            "IDP_ENTITY_ID": saml_settings["idp"]["entityId"],
            "SP_CONFIG": saml_settings["sp"],
        }
    except Exception as e:
        return {"error": str(e)}

# Add a direct test/debug SSO endpoint
@app.get("/auth/direct-test")
async def direct_test():
    """Direct test link to EMBL SSO (for debugging)"""
    # Build a direct URL to EMBL's SAML endpoint
    entity_id = urllib.parse.quote(SP_ENTITY_ID)
    acs_url = urllib.parse.quote(ACS_URL)
    
    # Direct URL to EMBL's SAML endpoint (using the test domain)
    direct_url = f"https://auth.ktest.embl.de/realms/EMBL-HD/protocol/saml?client_id={entity_id}&redirect_uri={acs_url}"
    
    logger.info(f"Direct test URL: {direct_url}")
    
    html_content = f"""
    <!DOCTYPE html>
    <html>
        <head>
            <title>Direct EMBL SSO Test</title>
        </head>
        <body>
            <h1>Direct EMBL SSO Test</h1>
            <p>This is a direct link to EMBL's SSO service for testing purposes.</p>
            <p><a href="{direct_url}">Click here to test direct SSO access</a></p>
            <p>Debug info: <pre>{direct_url}</pre></p>
        </body>
    </html>
    """
    return HTMLResponse(content=html_content)

if __name__ == "__main__":
    import uvicorn
    logger.info("Starting FastAPI SAML application")
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)