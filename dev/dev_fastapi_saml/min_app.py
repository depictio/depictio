import os
import base64
import json
import logging
import traceback
import xml.etree.ElementTree as ET
import html
from datetime import datetime, timedelta
from typing import Optional

import jwt
import uvicorn
from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from onelogin.saml2.auth import OneLogin_Saml2_Auth
from onelogin.saml2.settings import OneLogin_Saml2_Settings

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("saml_debug")

# Load environment variables
load_dotenv()

app = FastAPI(title="SAML Authentication Service")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===============================================================
# Configuration and Helpers
# ===============================================================

async def get_current_user(request: Request):
    """Validate JWT token and return user data"""
    # Get token from cookie
    auth_token = request.cookies.get("auth_token")
    
    if not auth_token:
        return None
    
    try:
        # Decode and validate token
        payload = jwt.decode(auth_token, os.getenv("JWT_SECRET"), algorithms=["HS256"])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None

def get_saml_settings(custom_acs_url=None):
    """Create SAML settings from environment variables"""
    try:
        with open(os.getenv("CMD_SAML_IDPCERT"), "r") as cert_file:
            cert_content = cert_file.read()
    except Exception as e:
        logger.error(f"Error reading cert: {e}")
        cert_content = ""
    
    base_url = os.getenv("BASE_URL", "http://localhost:8000")
    entity_id = os.getenv("CMD_SAML_SP_ENTITY_ID", "depictio-dev-datasci")
    
    settings = {
        "strict": False,
        "debug": True,
        "sp": {
            "entityId": entity_id,
            "assertionConsumerService": {
                "url": custom_acs_url or os.getenv("CMD_REDIRECT_URL"),
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST",
            },
            "NameIDFormat": os.getenv("CMD_SAML_IDENTIFIERFORMAT"),
        },
        "idp": {
            "entityId": entity_id,
            "singleSignOnService": {
                "url": os.getenv("CMD_SAML_IDPSSOURL"),
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect",
            },
            "x509cert": cert_content,
        },
        "security": {
            "authnRequestsSigned": False,
            "wantAssertionsSigned": False,
            "wantNameId": True,
            "requestedAuthnContext": False,
        }
    }
    
    return settings

async def prepare_request(request: Request):
    """Prepare request for python-saml"""
    host_header = request.headers.get("host", "localhost:8000")
    if ":" in host_header:
        http_host, server_port = host_header.split(":")
    else:
        http_host = host_header
        server_port = "443" if request.url.scheme == "https" else "80"
    
    return {
        "https": "on" if request.url.scheme == "https" else "off",
        "http_host": http_host,
        "script_name": request.url.path,
        "server_port": server_port,
        "get_data": dict(request.query_params),
        "post_data": {},
        "query_string": request.url.query,
        "headers": dict(request.headers),
    }

def init_saml_auth(req, custom_acs_url=None):
    """Initialize SAML authentication"""
    settings = get_saml_settings(custom_acs_url)
    logger.debug(f"SAML Settings: {json.dumps(settings, default=str, indent=2)}")
    
    try:
        auth = OneLogin_Saml2_Auth(req, settings)
        return auth
    except Exception as e:
        logger.error(f"Error initializing SAML auth: {e}")
        raise

def create_jwt_token(user_data):
    """Create a JWT token from user data"""
    token_data = {
        **user_data,
        "exp": datetime.utcnow() + timedelta(hours=1)
    }
    return jwt.encode(token_data, os.getenv("JWT_SECRET"), algorithm="HS256")

def extract_saml_data(saml_xml):
    """Extract important data from SAML response XML"""
    root = ET.fromstring(saml_xml)
    
    namespaces = {
        'samlp': 'urn:oasis:names:tc:SAML:2.0:protocol',
        'saml': 'urn:oasis:names:tc:SAML:2.0:assertion',
        'ds': 'http://www.w3.org/2000/09/xmldsig#'
    }
    
    # Extract data
    result = {
        "status": {
            "code": None,
            "message": None
        },
        "user": {
            "nameid": None,
            "attributes": {}
        }
    }
    
    # Get status
    status_code_elem = root.find('.//samlp:StatusCode', namespaces)
    if status_code_elem is not None:
        result["status"]["code"] = status_code_elem.get('Value')
    
    status_message_elem = root.find('.//samlp:StatusMessage', namespaces)
    if status_message_elem is not None and status_message_elem.text:
        result["status"]["message"] = status_message_elem.text
    
    # Get NameID
    nameid_elem = root.find('.//saml:NameID', namespaces)
    if nameid_elem is not None and nameid_elem.text:
        result["user"]["nameid"] = nameid_elem.text
    
    # Get attributes
    for attr in root.findall('.//saml:Attribute', namespaces):
        name = attr.get('Name')
        friendly_name = attr.get('FriendlyName')  # Also check for FriendlyName
        
        if name:
            values = []
            for value_elem in attr.findall('.//saml:AttributeValue', namespaces):
                if value_elem.text:
                    values.append(value_elem.text)
            
            # Use both the original name and friendly name if available
            attr_key = friendly_name if friendly_name else name
            
            if values:
                result["user"]["attributes"][attr_key] = values[0] if len(values) == 1 else values

    # Log the extracted attributes for debugging
    logger.debug(f"Extracted SAML attributes: {json.dumps(result['user']['attributes'], default=str)}")
    
    return result

# ===============================================================
# Main Routes
# ===============================================================

@app.get("/")
async def home(request: Request):
    """Home page with login links or user status"""
    user = await get_current_user(request)
    
    # User status section if logged in
    user_section = """
    <div style="background-color: #e8f4f8; padding: 15px; border-radius: 5px; margin-bottom: 20px;">
        <h3>Welcome!</h3>
        <p>You are currently not logged in.</p>
        <a href="/login" style="display: inline-block; background-color: #3498db; color: white; 
                              padding: 10px 15px; text-decoration: none; border-radius: 4px;">
            Login with SAML
        </a>
    </div>
    """
    
    if user:
        user_section = f"""
        <div style="background-color: #e8f4f8; padding: 15px; border-radius: 5px; margin-bottom: 20px;">
            <h3>Welcome, {html.escape(user.get('username', 'User'))}!</h3>
            <p>You are logged in as: {html.escape(user.get('email', 'Unknown'))}</p>
            <a href="/profile" style="display: inline-block; background-color: #2ecc71; color: white; 
                                  padding: 10px 15px; text-decoration: none; border-radius: 4px; margin-right: 10px;">
                View Profile
            </a>
            <form action="/logout" method="post" style="display: inline-block;">
                <button type="submit" style="background-color: #e74c3c; color: white; padding: 10px 15px; 
                                          border-radius: 4px; border: none; cursor: pointer;">
                    Logout
                </button>
            </form>
        </div>
        """
    
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>SAML Authentication Service</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 0; padding: 0; }}
            .container {{ max-width: 800px; margin: 0 auto; padding: 20px; }}
            h1, h2 {{ color: #2c3e50; }}
            .nav {{ margin-bottom: 20px; }}
            .nav a {{ margin-right: 10px; }}
            .card {{ background-color: #f9f9f9; border-radius: 8px; padding: 20px; 
                   margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1); }}
            ul {{ padding-left: 20px; }}
            li {{ margin-bottom: 10px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="nav">
                <a href="/">Home</a>
                <a href="/profile">Profile</a>
                <a href="/debug/">Debug Info</a>
            </div>
            
            <h1>SAML Authentication Service</h1>
            
            {user_section}
            
            <div class="card">
                <h2>Authentication Options</h2>
                <ul>
                    <li><a href='/login'>Standard Login with SAML</a></li>
                    <li><a href='/debug-login'>Debug Login (with detailed SAML analysis)</a></li>
                </ul>
            </div>
            
            <div class="card">
                <h2>Utilities</h2>
                <ul>
                    <li><a href='/debug/'>View SAML Configuration</a></li>
                    <li><a href='/metadata/'>View SP Metadata</a></li>
                    <li><a href='/debug-form'>Manual SAML Response Analysis Form</a></li>
                </ul>
            </div>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

# ===============================================================
# Authentication Routes
# ===============================================================

@app.get("/login")
async def login(request: Request):
    """Initiate standard SAML login"""
    req = await prepare_request(request)
    
    try:
        auth = init_saml_auth(req)
        login_url = auth.login()
        logger.info(f"Login URL: {login_url}")
        return RedirectResponse(login_url)
    except Exception as e:
        logger.error(f"Login error: {e}")
        return PlainTextResponse(f"Error initiating login: {str(e)}")

@app.post("/auth/saml/callback")
@app.get("/auth/saml/callback")
async def saml_callback(request: Request):
    """Handle SAML response and process authentication"""
    logger.info(f"SAML callback received: {request.method}")
    
    if request.method == "POST":
        try:
            form_data = await request.form()
            saml_response_b64 = form_data.get("SAMLResponse")
            
            if saml_response_b64:
                logger.info("SAMLResponse received")
                
                try:
                    # Decode SAML response
                    saml_xml = base64.b64decode(saml_response_b64).decode('utf-8')
                    
                    # Extract user data
                    saml_data = extract_saml_data(saml_xml)
                    
                    # Check authentication status
                    if saml_data["status"]["code"] != 'urn:oasis:names:tc:SAML:2.0:status:Success':
                        return PlainTextResponse(
                            f"Authentication failed: {saml_data['status']['message'] or 'Unknown error'}"
                        )
                    
                    # Get user identifier
                    nameid = saml_data["user"]["nameid"]
                    if not nameid:
                        return PlainTextResponse("No user identifier found in SAML response")
                    
                    # Get email from attributes with fallback to nameid
                    attributes = saml_data["user"]["attributes"]
                    email = None
                    
                    # Check for email in various possible attribute names
                    email_attribute_names = ["email", "Email", "mail", "Mail", "emailAddress", "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress"]
                    
                    for attr_name in email_attribute_names:
                        if attr_name in attributes:
                            email = attributes[attr_name]
                            if isinstance(email, list):
                                email = email[0]
                            break
                    
                    # Fallback to nameid if no email found
                    if not email:
                        email = nameid
                    
                    # Get username from attributes or default
                    username = None
                    username_attribute_names = ["username", "Username", "preferred_username", "login", "uid", "userId"]
                    
                    for attr_name in username_attribute_names:
                        if attr_name in attributes:
                            username = attributes[attr_name]
                            if isinstance(username, list):
                                username = username[0]
                            break
                    
                    # Fallback username
                    if not username:
                        # Extract username from email or use default
                        username = email.split('@')[0] if '@' in email else "user"
                    
                    # Build user data
                    user_data = {
                        "id": nameid,
                        "email": email,
                        "username": username,
                        "attributes": attributes,
                        "authenticated_at": datetime.utcnow().isoformat()
                    }
                    
                    # Create JWT token
                    token = create_jwt_token(user_data)
                    
                    # Set the JWT cookie and redirect to profile page
                    response = RedirectResponse(url="/profile", status_code=303)
                    response.set_cookie(
                        key="auth_token", 
                        value=token, 
                        httponly=True
                    )
                    
                    return response
                    
                except Exception as e:
                    logger.error(f"Error processing SAML: {e}")
                    logger.error(traceback.format_exc())
                    return PlainTextResponse(f"Error processing SAML: {str(e)}")
                    
        except Exception as e:
            logger.error(f"Form processing error: {e}")
            return PlainTextResponse(f"Error processing form: {str(e)}")
    
    # For GET or errors
    return RedirectResponse(url="/")

# ===============================================================
# Debug Routes
# ===============================================================

@app.get("/debug/")
async def debug_info():
    """Show configuration and debug information"""
    env_vars = {k: v for k, v in os.environ.items() if k.startswith("CMD_") or k in ["BASE_URL", "JWT_SECRET"]}
    
    try:
        with open(os.getenv("CMD_SAML_IDPCERT"), "r") as f:
            cert_content = f.read()
            cert_excerpt = cert_content[:100] + "..." if len(cert_content) > 100 else cert_content
    except Exception as e:
        cert_excerpt = f"Error reading cert: {e}"
    
    debug_data = {
        "environment": env_vars,
        "certificate_excerpt": cert_excerpt,
        "saml_settings": get_saml_settings()
    }
    
    return debug_data

@app.get("/metadata/")
async def metadata():
    """Generate SAML metadata for SP"""
    try:
        settings = get_saml_settings()
        sp_metadata = OneLogin_Saml2_Settings(settings).get_sp_metadata()
        errors = OneLogin_Saml2_Settings(settings).validate_metadata(sp_metadata)
        
        if errors:
            return PlainTextResponse(f"Error generating metadata: {', '.join(errors)}")
        
        logger.info("Metadata generated successfully")
        return Response(content=sp_metadata, media_type="text/xml")
    except Exception as e:
        logger.error(f"Error generating metadata: {e}")
        return PlainTextResponse(f"Error generating metadata: {str(e)}")

@app.get("/debug-login")
async def debug_login(request: Request):
    """Login with SAML that redirects to the debug endpoint"""
    req = await prepare_request(request)
    debug_callback_url = f"{request.base_url}debug-saml"
    
    try:
        auth = init_saml_auth(req, debug_callback_url)
        login_url = auth.login()
        logger.info(f"Debug Login URL: {login_url}")
        return RedirectResponse(login_url)
    except Exception as e:
        logger.error(f"Debug login error: {e}")
        return PlainTextResponse(f"Error initiating debug login: {str(e)}")

@app.post("/debug-saml")
@app.get("/debug-saml")
async def debug_saml(request: Request):
    """Debug endpoint to examine SAML responses in detail"""
    try:
        raw_debug_info = {
            "method": request.method,
            "url": str(request.url),
            "headers": dict(request.headers),
            "query_params": dict(request.query_params),
        }
        
        # Extract POST data if available
        form_data = {}
        xml_content = None
        
        if request.method == "POST":
            try:
                form_data = await request.form()
                raw_debug_info["form_data_keys"] = list(form_data.keys())
                
                if "SAMLResponse" in form_data:
                    saml_response_b64 = form_data["SAMLResponse"]
                    raw_debug_info["saml_response_length"] = len(saml_response_b64)
                    
                    # Decode SAML response
                    try:
                        saml_xml = base64.b64decode(saml_response_b64).decode('utf-8')
                        xml_content = saml_xml
                        raw_debug_info["saml_xml_excerpt"] = saml_xml[:500] + "..." if len(saml_xml) > 500 else saml_xml
                        
                        # Parse XML for detailed analysis
                        try:
                            saml_data = extract_saml_data(saml_xml)
                            raw_debug_info.update({
                                "status_code": saml_data["status"]["code"],
                                "status_message": saml_data["status"]["message"],
                                "nameid": saml_data["user"]["nameid"],
                                "attributes": saml_data["user"]["attributes"]
                            })
                            
                            # Additional analysis for debugging purposes
                            root = ET.fromstring(saml_xml)
                            namespaces = {
                                'samlp': 'urn:oasis:names:tc:SAML:2.0:protocol',
                                'saml': 'urn:oasis:names:tc:SAML:2.0:assertion',
                                'ds': 'http://www.w3.org/2000/09/xmldsig#'
                            }
                            
                            # Count duplicates
                            attribute_counts = {}
                            for attr in root.findall('.//saml:Attribute', namespaces):
                                name = attr.get('Name')
                                if name:
                                    attribute_counts[name] = attribute_counts.get(name, 0) + 1
                            
                            raw_debug_info["attribute_counts"] = attribute_counts
                            raw_debug_info["duplicate_attributes"] = [
                                name for name, count in attribute_counts.items() if count > 1
                            ]
                            
                        except Exception as xml_parse_error:
                            raw_debug_info["xml_parse_error"] = str(xml_parse_error)
                            raw_debug_info["xml_parse_traceback"] = traceback.format_exc()
                    
                    except Exception as decode_error:
                        raw_debug_info["decode_error"] = str(decode_error)
                        raw_debug_info["decode_traceback"] = traceback.format_exc()
            
            except Exception as form_error:
                raw_debug_info["form_error"] = str(form_error)
                raw_debug_info["form_traceback"] = traceback.format_exc()
        
        # Generate HTML response with debug info
        html_response = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>SAML Debug Information</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; }}
                pre {{ background-color: #f4f4f4; padding: 10px; overflow: auto; }}
                .xml {{ white-space: pre-wrap; }}
                h2 {{ margin-top: 20px; color: #2c3e50; }}
                .error {{ color: red; }}
                table {{ border-collapse: collapse; width: 100%; }}
                th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
                th {{ background-color: #f2f2f2; }}
            </style>
        </head>
        <body>
            <h1>SAML Debug Information</h1>
            
            <h2>Request Information</h2>
            <table>
                <tr><th>Method</th><td>{raw_debug_info.get("method", "N/A")}</td></tr>
                <tr><th>URL</th><td>{raw_debug_info.get("url", "N/A")}</td></tr>
            </table>
            
            <h2>Headers</h2>
            <pre>{html.escape(json.dumps(raw_debug_info.get("headers", {}), indent=2))}</pre>
            
            <h2>SAML Response Status</h2>
            <table>
                <tr><th>Status Code</th><td>{raw_debug_info.get("status_code", "N/A")}</td></tr>
                <tr><th>Status Message</th><td>{raw_debug_info.get("status_message", "N/A")}</td></tr>
                <tr><th>NameID</th><td>{raw_debug_info.get("nameid", "N/A")}</td></tr>
            </table>
            
            <h2>SAML Attributes</h2>
            <pre>{html.escape(json.dumps(raw_debug_info.get("attributes", {}), indent=2))}</pre>
            
            <h2>Duplicate Attributes</h2>
            <pre>{html.escape(json.dumps(raw_debug_info.get("duplicate_attributes", []), indent=2))}</pre>
            
            <h2>SAML XML</h2>
            <pre class="xml">{html.escape(xml_content or "No XML content available")}</pre>
            
            <h2>Errors</h2>
            {f'<div class="error"><h3>XML Parse Error</h3><pre>{html.escape(raw_debug_info.get("xml_parse_error", ""))}</pre><h3>Traceback</h3><pre>{html.escape(raw_debug_info.get("xml_parse_traceback", ""))}</pre></div>' if "xml_parse_error" in raw_debug_info else ''}
            {f'<div class="error"><h3>Decode Error</h3><pre>{html.escape(raw_debug_info.get("decode_error", ""))}</pre><h3>Traceback</h3><pre>{html.escape(raw_debug_info.get("decode_traceback", ""))}</pre></div>' if "decode_error" in raw_debug_info else ''}
            {f'<div class="error"><h3>Form Error</h3><pre>{html.escape(raw_debug_info.get("form_error", ""))}</pre><h3>Traceback</h3><pre>{html.escape(raw_debug_info.get("form_traceback", ""))}</pre></div>' if "form_error" in raw_debug_info else ''}
            
            <h2>Raw Debug Info</h2>
            <pre>{html.escape(json.dumps(raw_debug_info, indent=2))}</pre>
        </body>
        </html>
        """
        
        return HTMLResponse(content=html_response)
        
    except Exception as e:
        return HTMLResponse(f"""
        <!DOCTYPE html>
        <html>
        <head><title>Debug Error</title></head>
        <body>
            <h1>Error in Debug Handler</h1>
            <pre>{html.escape(str(e))}</pre>
            <pre>{html.escape(traceback.format_exc())}</pre>
        </body>
        </html>
        """)

@app.get("/debug-form")
async def debug_form():
    """Form for manually submitting a SAML response for debugging"""
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>SAML Debug Form</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 20px; }
            textarea { width: 100%; height: 300px; }
            button { padding: 10px; margin-top: 10px; }
        </style>
    </head>
    <body>
        <h1>SAML Debug Form</h1>
        <p>Paste a base64-encoded SAML response below to analyze it:</p>
        
        <form action="/debug-saml" method="post">
            <textarea name="SAMLResponse" placeholder="Paste base64-encoded SAML response here"></textarea>
            <br>
            <button type="submit">Analyze SAML Response</button>
        </form>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

# ===============================================================
# User Profile & Logout Routes
# ===============================================================

@app.get("/profile")
async def profile_page(request: Request):
    """Display user profile with SAML attributes"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    # Prepare user info for display
    authenticated_at = user.get("authenticated_at", "Unknown")
    try:
        # Try to format the timestamp in a more readable way
        auth_datetime = datetime.fromisoformat(authenticated_at)
        authenticated_at = auth_datetime.strftime("%Y-%m-%d %H:%M:%S UTC")
    except:
        pass
    
    # Prepare attributes for display
    attributes = user.get("attributes", {})
    attribute_rows = ""
    # Sort attributes alphabetically for better display
    for key in sorted(attributes.keys()):
        value = attributes[key]
        # Format multi-value attributes as lists
        if isinstance(value, list):
            formatted_value = "<ul>"
            for item in value:
                formatted_value += f"<li>{html.escape(str(item))}</li>"
            formatted_value += "</ul>"
        else:
            formatted_value = html.escape(str(value))
            
        attribute_rows += f"""
        <tr>
            <td>{html.escape(key)}</td>
            <td>{formatted_value}</td>
        </tr>
        """
    
    if not attribute_rows:
        attribute_rows = "<tr><td colspan='2'>No additional attributes found</td></tr>"
    
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>User Profile</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 20px; max-width: 800px; margin: 0 auto; padding: 20px; }}
            h1, h2 {{ color: #2c3e50; }}
            .profile-card {{ background-color: #f9f9f9; border-radius: 8px; padding: 20px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1); }}
            .button {{ display: inline-block; background-color: #3498db; color: white; padding: 10px 15px; 
                      text-decoration: none; border-radius: 4px; margin-top: 10px; border: none; cursor: pointer; }}
            .button.danger {{ background-color: #e74c3c; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 15px; }}
            th, td {{ text-align: left; padding: 12px; border-bottom: 1px solid #ddd; vertical-align: top; }}
            th {{ background-color: #f2f2f2; }}
            .nav {{ margin-bottom: 20px; }}
            .nav a {{ margin-right: 10px; }}
            ul {{ margin: 0; padding-left: 20px; }}
        </style>
    </head>
    <body>
        <div class="nav">
            <a href="/">Home</a>
            <a href="/profile">Profile</a>
            <a href="/debug/">Debug Info</a>
        </div>
        
        <h1>User Profile</h1>
        
        <div class="profile-card">
            <h2>Basic Information</h2>
            <table>
                <tr>
                    <th>ID</th>
                    <td>{html.escape(user.get("id", "Unknown"))}</td>
                </tr>
                <tr>
                    <th>Email</th>
                    <td>{html.escape(user.get("email", "Unknown"))}</td>
                </tr>
                <tr>
                    <th>Username</th>
                    <td>{html.escape(user.get("username", "Unknown"))}</td>
                </tr>
                <tr>
                    <th>Authenticated At</th>
                    <td>{html.escape(authenticated_at)}</td>
                </tr>
            </table>
        </div>
        
        <div class="profile-card">
            <h2>SAML Attributes</h2>
            <table>
                <tr>
                    <th>Attribute</th>
                    <th>Value</th>
                </tr>
                {attribute_rows}
            </table>
        </div>
        
        <form action="/logout" method="post">
            <button type="submit" class="button danger">Logout</button>
        </form>
    </body>
    </html>
    """
    
    return HTMLResponse(content=html_content)

@app.post("/logout")
async def logout():
    """Handle user logout by clearing the auth cookie"""
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie(key="auth_token")
    return response

# ===============================================================
# Protected API Route Example
# ===============================================================

@app.get("/api/user")
async def user_info(request: Request):
    """Example API endpoint that returns the authenticated user's data"""
    user = await get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user

# ===============================================================
# Main Entry Point
# ===============================================================

if __name__ == "__main__":
    logger.info("Starting SAML authentication service")
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)