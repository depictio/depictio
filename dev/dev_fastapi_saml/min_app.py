import os
import base64
import json
import logging
from datetime import datetime, timedelta

import base64
import xml.etree.ElementTree as ET
import html
import traceback
from urllib.parse import parse_qs
import jwt
import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse
from dotenv import load_dotenv

from onelogin.saml2.auth import OneLogin_Saml2_Auth
from onelogin.saml2.settings import OneLogin_Saml2_Settings

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("saml_debug")


## .env
# CMD_SAML_IDPSSOURL=http://localhost:8080/realms/master/protocol/saml
# CMD_SAML_IDPCERT=keycloak_local.pem
# CMD_REDIRECT_URL=http://localhost:8000/auth/saml/callback
# CMD_SAML_IDENTIFIERFORMAT=urn:oasis:names:tc:SAML:2.0:nameid-format:persistent
# BASE_URL=http://localhost:8000
# CMD_SAML_SP_ENTITY_ID=depictio-dev-datasci

# Load environment variables
load_dotenv()

app = FastAPI(title="Minimal SAML Debug")

def get_saml_settings():
    """Create minimal SAML settings"""
    try:
        with open(os.getenv("CMD_SAML_IDPCERT"), "r") as cert_file:
            cert_content = cert_file.read()
    except Exception as e:
        logger.error(f"Error reading cert: {e}")
        cert_content = ""
    
    base_url = os.getenv("BASE_URL", "http://localhost:8000")
    
    return {
        "strict": False,
        "debug": True,
        "sp": {
            "entityId": "depictio-dev-datasci",  # CHANGED: Match client ID in Keycloak
            "assertionConsumerService": {
                "url": os.getenv("CMD_REDIRECT_URL"),
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST",
            },
            "NameIDFormat": os.getenv("CMD_SAML_IDENTIFIERFORMAT"),
        },
        "idp": {
            "entityId": "depictio-dev-datasci",
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

@app.get("/")
async def home():
    """Simple home page with login link"""
    html_content = """
    SAML Debug App
    
    <a href='/login'>Login with SAML</a>
    <br><br>
    <a href='/debug/'>View Debug Info</a>
    <br><br>
    <a href='/metadata/'>View SP Metadata</a>
    """
    return PlainTextResponse(html_content)


# Add this function to your application to test different NameID formats

@app.get("/login")
async def login(request: Request):
    """Initiate SAML login"""
    req = await prepare_request(request)
    
    try:
        auth = OneLogin_Saml2_Auth(req, get_saml_settings())
        login_url = auth.login()
        logger.info(f"Login URL: {login_url}")
        return RedirectResponse(login_url)
    except Exception as e:
        logger.error(f"Login error: {e}")
        return PlainTextResponse(f"Error initiating login: {str(e)}")

def init_saml_auth(req):
    """Initialize SAML authentication"""
    settings = get_saml_settings()
    logger.debug(f"SAML Settings: {json.dumps(settings, default=str, indent=2)}")
    
    try:
        auth = OneLogin_Saml2_Auth(req, settings)
        return auth
    except Exception as e:
        logger.error(f"Error initializing SAML auth: {e}")
        raise
@app.post("/auth/saml/callback")
@app.get("/auth/saml/callback")
async def saml_callback(request: Request):
    """Handle SAML response with minimal attribute requirements"""
    logger.info(f"Callback received: {request.method}")
    
    if request.method == "POST":
        try:
            form_data = await request.form()
            saml_response_b64 = form_data.get("SAMLResponse")
            
            if saml_response_b64:
                logger.info("SAMLResponse received")
                
                try:
                    # Decode SAML response
                    saml_xml = base64.b64decode(saml_response_b64).decode('utf-8')
                    
                    # Parse XML to extract NameID
                    root = ET.fromstring(saml_xml)
                    
                    namespaces = {
                        'samlp': 'urn:oasis:names:tc:SAML:2.0:protocol',
                        'saml': 'urn:oasis:names:tc:SAML:2.0:assertion'
                    }
                    
                    # Check status
                    status_code = root.find('.//samlp:StatusCode', namespaces)
                    if status_code is not None and status_code.get('Value') != 'urn:oasis:names:tc:SAML:2.0:status:Success':
                        return PlainTextResponse("Authentication failed")
                    
                    # Extract NameID - this is all we really need
                    nameid_elem = root.find('.//saml:NameID', namespaces)
                    nameid = nameid_elem.text if nameid_elem is not None else None
                    
                    if not nameid:
                        return PlainTextResponse("No user identifier found in SAML response")
                    
                    # Build user data with just the NameID
                    user_data = {
                        "id": nameid,
                        "username": "user",  # Default username
                        "email": nameid,     # Use NameID as email
                        "authenticated_at": datetime.utcnow().isoformat()
                    }
                    
                    # Create JWT token
                    token_data = {
                        **user_data,
                        "exp": datetime.utcnow() + timedelta(hours=1)
                    }
                    token = jwt.encode(token_data, os.getenv("JWT_SECRET"), algorithm="HS256")
                    
                    # Set the JWT cookie and redirect
                    response = RedirectResponse(url="/", status_code=303)
                    response.set_cookie(key="auth_token", value=token, httponly=True)
                    
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

@app.get("/debug/")
async def debug_info():
    """Show debug information"""
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
                        
                        # Parse XML for more detailed analysis
                        try:
                            root = ET.fromstring(saml_xml)
                            
                            # Register namespaces for better xpath queries
                            namespaces = {
                                'samlp': 'urn:oasis:names:tc:SAML:2.0:protocol',
                                'saml': 'urn:oasis:names:tc:SAML:2.0:assertion',
                                'ds': 'http://www.w3.org/2000/09/xmldsig#'
                            }
                            
                            # Extract status
                            status_code_elem = root.find('.//samlp:StatusCode', namespaces)
                            if status_code_elem is not None:
                                raw_debug_info["status_code"] = status_code_elem.get('Value')
                            
                            status_message_elem = root.find('.//samlp:StatusMessage', namespaces)
                            if status_message_elem is not None and status_message_elem.text:
                                raw_debug_info["status_message"] = status_message_elem.text
                            
                            # Extract NameID
                            nameid_elem = root.find('.//saml:NameID', namespaces)
                            if nameid_elem is not None and nameid_elem.text:
                                raw_debug_info["nameid"] = nameid_elem.text
                            
                            # Extract attributes and count duplicates
                            attributes = {}
                            attribute_counts = {}
                            
                            for attr in root.findall('.//saml:Attribute', namespaces):
                                name = attr.get('Name')
                                if name:
                                    if name not in attribute_counts:
                                        attribute_counts[name] = 1
                                    else:
                                        attribute_counts[name] += 1
                                        
                                    values = []
                                    for value_elem in attr.findall('.//saml:AttributeValue', namespaces):
                                        if value_elem.text:
                                            values.append(value_elem.text)
                                    
                                    if name in attributes:
                                        # Append to existing attribute values
                                        attributes[name].extend(values)
                                    else:
                                        attributes[name] = values
                            
                            raw_debug_info["attributes"] = attributes
                            raw_debug_info["attribute_counts"] = attribute_counts
                            raw_debug_info["duplicate_attributes"] = [name for name, count in attribute_counts.items() if count > 1]
                            
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
            
            <h2>Query Parameters</h2>
            <pre>{html.escape(json.dumps(raw_debug_info.get("query_params", {}), indent=2))}</pre>
            
            <h2>Form Data</h2>
            <pre>{html.escape(json.dumps(raw_debug_info.get("form_data_keys", []), indent=2))}</pre>
            
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

# Add a form to manually submit SAML responses for debugging
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

# Modify your login route to use the debug endpoint for testing
@app.get("/debug-login")
async def debug_login(request: Request):
    """Login with SAML that redirects to the debug endpoint"""
    req = await prepare_request(request)
    
    # Create a modified settings dictionary that uses the debug endpoint
    settings = get_saml_settings()
    settings["sp"]["assertionConsumerService"]["url"] = str(request.base_url) + "debug-saml"
    
    try:
        auth = OneLogin_Saml2_Auth(req, settings)
        login_url = auth.login()
        logger.info(f"Debug Login URL: {login_url}")
        return RedirectResponse(login_url)
    except Exception as e:
        logger.error(f"Login error: {e}")
        return PlainTextResponse(f"Error initiating login: {str(e)}")

if __name__ == "__main__":
    logger.info("Starting minimal SAML debug application")
    uvicorn.run("minimal_saml:app", host="0.0.0.0", port=8000, reload=True)