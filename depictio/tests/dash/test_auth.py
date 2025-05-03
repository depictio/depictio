import os
import pytest
from playwright.sync_api import Page, expect
from depictio.api.v1.configs.config import settings
from depictio.api.v1.endpoints.user_endpoints.utils import delete_user_from_db
from depictio.models.utils import get_config
from depictio import BASE_PATH

# Load initial users configuration
config_path = os.path.join(
    BASE_PATH, "depictio", "api", "v1", "configs", "initial_users.yaml"
)
initial_config = get_config(config_path)

# Get test user credentials from initial_users.yaml
DASH_URL = f"http://{settings.dash.host}:{settings.dash.port}"
# Using the second user (test_user) from the config
TEST_USER = initial_config["users"][1]
TEST_USER_EMAIL = TEST_USER["email"]
TEST_USER_PASSWORD = TEST_USER["password"]


@pytest.mark.playwright
def test_login_auth_page(page: Page):
    """Test logging in to the application via the auth page."""

    # Navigate to the auth page
    page.goto(f"{DASH_URL}/auth", wait_until="networkidle")

    # Check if we're on the auth page
    expect(page).to_have_url(f"{DASH_URL}/auth")

    # Check if the login form is present
    page.wait_for_selector("#auth-modal")

    # NOTE: use get_by_role as elements are present in multiple locations due to the current architecture of the login page (users_management.py)
    page.get_by_role("textbox", name="Enter your email").fill(TEST_USER_EMAIL)
    page.get_by_role("textbox", name="Enter your password").fill(TEST_USER_PASSWORD)
    page.get_by_role("button", name="Login").click()

    # Check if the login was successful
    page.wait_for_url(f"{DASH_URL}/dashboards")


@pytest.mark.playwright
def test_unsuccessful_login_auth_page(page: Page):
    """Test unsuccessful login attempt with invalid credentials."""

    # Navigate to the auth page
    page.goto(f"{DASH_URL}/auth", wait_until="networkidle")

    # Check if we're on the auth page
    expect(page).to_have_url(f"{DASH_URL}/auth")

    # Check if the login form is present
    page.wait_for_selector("#auth-modal")

    # Use invalid credentials
    invalid_email = "invalid_user@example.com"
    invalid_password = "wrong_password"

    # Fill in invalid credentials
    page.get_by_role("textbox", name="Enter your email").fill(invalid_email)
    page.get_by_role("textbox", name="Enter your password").fill(invalid_password)
    page.get_by_role("button", name="Login").click()

    # Wait for error message to appear
    # Note: You'll need to modify this selector to match your application's error message element
    page.wait_for_selector("#user-feedback-message-login")

    # Verify error message content (modify to match your actual error message)
    error_element = page.locator("#user-feedback-message-login").first
    error_message = error_element.text_content() or ""
    assert "User not found. Please register first." in error_message, (
        f"Unexpected error message: {error_message}"
    )

    # Verify we're still on the auth page (not redirected)
    expect(page).to_have_url(f"{DASH_URL}/auth")

    # Verify the login form is still available
    assert page.locator("#auth-modal").is_visible(), (
        "Login form should still be visible after failed login"
    )

    print("Successfully verified unsuccessful login scenario")


@pytest.mark.playwright
def test_user_registration(page: Page):
    """Test user registration functionality."""

    # Navigate to the auth page
    page.goto(f"{DASH_URL}/auth", wait_until="networkidle")

    # Check if we're on the auth page
    expect(page).to_have_url(f"{DASH_URL}/auth")

    # Check if the auth modal is present
    page.wait_for_selector("#auth-modal")

    # Click on the Switch to Register button
    page.get_by_role("button", name="Register").click()

    test_email = "test_user_playwright@example.com"
    test_password = "SecurePassword123!"

    # Fill in registration details using the get_by_role approach consistently

    # Fill in email field
    page.get_by_role("textbox", name="Enter your email").fill(test_email)

    # Fill in password field
    page.get_by_role("textbox", name="Enter your password").fill(test_password)

    # Fill in confirm password field
    page.get_by_role("textbox", name="Confirm your password").fill(test_password)

    # Wait for the register button to be enabled
    page.wait_for_selector("#register-button:not([disabled])", timeout=5000)

    # Click the register button
    page.get_by_role("button", name="Register").click()

    # Wait for the success message
    page.wait_for_selector("#user-feedback-message-register", state="visible")

    # Verify success message content
    feedback_element = page.locator("#user-feedback-message-register").first
    feedback_message = feedback_element.text_content() or ""
    assert "Registration successful! Please login." in feedback_message, (
        f"Unexpected message: {feedback_message}"
    )

    # Back to login button
    page.get_by_role("button", name="Back to Login").click()

    # Take a screenshot of the success message
    page.screenshot(path="depictio/tests/dash/screenshots/registration_success.png")

    # Verify we're still on the auth page since we need to log in
    expect(page).to_have_url(f"{DASH_URL}/auth")

    # Log in with the new credentials using the get_by_role approach
    page.get_by_role("textbox", name="Enter your email").fill(test_email)
    page.get_by_role("textbox", name="Enter your password").fill(test_password)
    page.get_by_role("button", name="Login").click()

    # Check if the login was successful
    page.wait_for_url(f"{DASH_URL}/dashboards")

    print(f"Successfully registered and logged in with user: {test_email}")

    # Delete the test user from the database
    delete_user_from_db(
        email=test_email,
    )


@pytest.mark.playwright
def test_unsuccessful_registration_already_registered(page: Page):
    """Test unsuccessful registration with various error scenarios."""

    # Navigate to the auth page
    page.goto(f"{DASH_URL}/auth", wait_until="networkidle")

    # Check if we're on the auth page
    expect(page).to_have_url(f"{DASH_URL}/auth")

    # Check if the auth modal is present
    page.wait_for_selector("#auth-modal")

    # Click on the Switch to Register button
    page.get_by_role("button", name="Register").click()

    # Check for Already registered email
    print("Testing already registered email...")

    # Use a known registered email (from initial_users.yaml)
    page.get_by_role("textbox", name="Enter your email").fill(TEST_USER_EMAIL)
    page.get_by_role("textbox", name="Enter your password").fill("SecurePassword123!")
    page.get_by_role("textbox", name="Confirm your password").fill("SecurePassword123!")

    # Wait for the register button to be enabled
    page.wait_for_selector("#register-button:not([disabled])", timeout=5000)

    # Click the register button
    page.get_by_role("button", name="Register").click()

    # Wait for the error message
    page.wait_for_selector("#user-feedback-message-register", state="visible")

    # Verify error message about existing user
    feedback_element = page.locator("#user-feedback-message-register").first
    feedback_message = feedback_element.text_content() or ""
    assert "already registered" in feedback_message.lower(), (
        f"Unexpected message: {feedback_message}"
    )

    # Take a screenshot
    page.screenshot(
        path="depictio/tests/dash/screenshots/registration_duplicate_error.png"
    )

    print("Successfully tested all unsuccessful registration scenarios")


@pytest.mark.playwright
def test_unsuccessful_registration_password_mismatch(page: Page):
    """Test unsuccessful registration with various error scenarios."""

    # Navigate to the auth page
    page.goto(f"{DASH_URL}/auth", wait_until="networkidle")

    # Check if we're on the auth page
    expect(page).to_have_url(f"{DASH_URL}/auth")

    # Check if the auth modal is present
    page.wait_for_selector("#auth-modal")

    # Click on the Switch to Register button
    page.get_by_role("button", name="Register").click()

    # Check for Already registered email
    print("Testing already registered email...")

    # Generate a unique test email to avoid conflicts with existing users
    import time

    test_email = f"test_user_{int(time.time())}@example.com"
    password1 = "SecurePassword123!"
    password2 = "SecurePassword124!"

    assert password1 != password2, "Passwords should not match"

    # Use a known registered email (from initial_users.yaml)
    page.get_by_role("textbox", name="Enter your email").fill(test_email)
    page.get_by_role("textbox", name="Enter your password").fill(password1)
    page.get_by_role("textbox", name="Confirm your password").fill(password2)

    # Wait for the register button to be enabled
    page.wait_for_selector("#register-button:not([disabled])", timeout=5000)

    # Click the register button
    page.get_by_role("button", name="Register").click()

    # Wait for the error message
    page.wait_for_selector("#user-feedback-message-register", state="visible")

    # Verify error message about existing user
    feedback_element = page.locator("#user-feedback-message-register").first
    feedback_message = feedback_element.text_content() or ""
    assert "passwords do not match." in feedback_message.lower(), (
        f"Unexpected message: {feedback_message}"
    )

    # Take a screenshot
    page.screenshot(
        path="depictio/tests/dash/screenshots/registration_duplicate_error.png"
    )

    print("Successfully tested all unsuccessful registration scenarios")


@pytest.mark.playwright
def test_logout(page: Page):
    """Test logging out of the application."""

    # Navigate to the auth page
    page.goto(f"{DASH_URL}/auth", wait_until="networkidle")

    # Check if we're on the auth page
    expect(page).to_have_url(f"{DASH_URL}/auth")

    # Check if the login form is present
    page.wait_for_selector("#auth-modal")

    # Log in with valid credentials
    page.get_by_role("textbox", name="Enter your email").fill(TEST_USER_EMAIL)
    page.get_by_role("textbox", name="Enter your password").fill(TEST_USER_PASSWORD)
    page.get_by_role("button", name="Login").click()

    # Check if the login was successful
    page.wait_for_url(f"{DASH_URL}/dashboards")

    # Go to profile/ page
    page.goto(f"{DASH_URL}/profile", wait_until="networkidle")

    # Click on the logout button (modify selector as needed)
    page.get_by_role("button", name="Logout").click()

    # Wait for the auth modal to reappear
    page.wait_for_selector("#auth-modal")

    # Verify we're back on the auth page
    expect(page).to_have_url(f"{DASH_URL}/auth")


@pytest.mark.playwright
def test_edit_password(page: Page):
    """Test editing the password of the user."""

    # Navigate to the auth page
    page.goto(f"{DASH_URL}/auth", wait_until="networkidle")

    # Check if we're on the auth page
    expect(page).to_have_url(f"{DASH_URL}/auth")

    # Check if the login form is present
    page.wait_for_selector("#auth-modal")

    # Log in with valid credentials
    page.get_by_role("textbox", name="Enter your email").fill(TEST_USER_EMAIL)
    page.get_by_role("textbox", name="Enter your password").fill(TEST_USER_PASSWORD)
    page.get_by_role("button", name="Login").click()

    # Check if the login was successful
    page.wait_for_url(f"{DASH_URL}/dashboards")

    # Go to profile/ page
    page.goto(f"{DASH_URL}/profile", wait_until="networkidle")

    # Click on the edit password button (modify selector as needed)
    page.get_by_role("button", name="Edit Password").click()

    # Fill in new password fields
    new_password = "NewSecurePassword123!"
    confirm_new_password = "NewSecurePassword123!"

    # Fill in current password field
    page.get_by_role("textbox", name="Old password").fill(TEST_USER_PASSWORD)

    # Fill in new password field
    page.get_by_role("textbox", name="New password").fill(new_password)

    # Fill in confirm new password field
    page.get_by_role("textbox", name="Confirm Password").fill(confirm_new_password)

    # Wait for the save button to be enabled
    page.wait_for_selector("#save-password:not([disabled])", timeout=5000)

    # Click the save button
    page.get_by_role("button", name="Save").click()

    # Wait for the success message
    page.wait_for_selector("#message-password", state="visible")

    # Verify error message about existing user
    feedback_element = page.locator("#message-password").first

    feedback_message = feedback_element.text_content() or ""
    assert "password updated successfully" in feedback_message.lower(), (
        f"Unexpected message: {feedback_message}"
    )

    # Close the modal using the X button
    page.locator(".mantine-Modal-close").first.click()

    # Log out
    page.get_by_role("button", name="Logout").click()

    # Wait for the auth modal to reappear
    page.wait_for_selector("#auth-modal")

    # Verify we're back on the auth page
    expect(page).to_have_url(f"{DASH_URL}/auth")

    # Log in with the new credentials
    page.get_by_role("textbox", name="Enter your email").fill(TEST_USER_EMAIL)
    page.get_by_role("textbox", name="Enter your password").fill(new_password)
    page.get_by_role("button", name="Login").click()
    # Check if the login was successful
    page.wait_for_url(f"{DASH_URL}/dashboards")


@pytest.mark.playwright
def test_edit_create_cli_config(page: Page):
    """Test editing the email of the user."""

    # Navigate to the auth page
    page.goto(f"{DASH_URL}/auth", wait_until="networkidle")

    # Check if we're on the auth page
    expect(page).to_have_url(f"{DASH_URL}/auth")

    # Check if the login form is present
    page.wait_for_selector("#auth-modal")

    # Log in with valid credentials
    page.get_by_role("textbox", name="Enter your email").fill(TEST_USER_EMAIL)
    page.get_by_role("textbox", name="Enter your password").fill(TEST_USER_PASSWORD)
    page.get_by_role("button", name="Login").click()

    # Check if the login was successful
    page.wait_for_url(f"{DASH_URL}/dashboards")

    # Go to profile/ page
    page.goto(f"{DASH_URL}/profile", wait_until="networkidle")

    # Click on CLI-Agents button
    page.get_by_role("button", name="CLI Agents").click()

    # Wait for the page to load
    page.wait_for_url(f"{DASH_URL}/cli_configs")

    # Click on CLI-Agents button
    page.get_by_role("button", name="Add New Configuration").click()

    # Fill in CLI config fields
    page.get_by_placeholder("Enter a name for your CLI configuration").fill("Test_CLI")

    # Save the configuration
    page.get_by_role("button", name="Save").click()

    # Check if present in the list
    page.wait_for_selector("#config-created-success")

    # Retrieve content of agent-config-md
    agent_config_md = page.locator("#agent-config-md").first
    agent_config_md_content = agent_config_md.text_content() or ""
    print(f"Agent Config MD Content: {agent_config_md_content}")
    assert "base_url" in agent_config_md_content, (
        f"Unexpected content in agent-config-md: {agent_config_md_content}"
    )


@pytest.mark.playwright
def test_about_page(page: Page):
    """Test the About page."""

    # Navigate to the auth page
    page.goto(f"{DASH_URL}/auth", wait_until="networkidle")

    # Check if we're on the auth page
    expect(page).to_have_url(f"{DASH_URL}/auth")

    # Check if the login form is present
    page.wait_for_selector("#auth-modal")

    # Log in with valid credentials
    page.get_by_role("textbox", name="Enter your email").fill(TEST_USER_EMAIL)
    page.get_by_role("textbox", name="Enter your password").fill(TEST_USER_PASSWORD)
    page.get_by_role("button", name="Login").click()

    # Check if the login was successful
    page.wait_for_url(f"{DASH_URL}/dashboards")

    # Go to profile/ page
    page.goto(f"{DASH_URL}/about", wait_until="networkidle")

    # Check dash errors content - check if class="dash-debug-error-count" is present - if not, test success - else fail
    # Check if the element is not visible
    if page.locator(".dash-debug-error-count").is_visible():
        # Take a screenshot of the error message
        # page.screenshot(path="depictio/tests/dash/screenshots/dash_debug_alert.png")
        print("Dash debug alert is visible, indicating an error.")
        assert False, "Dash debug alert is visible, indicating an error."
    else:
        # Take a screenshot of the success message
        # page.screenshot(path="depictio/tests/dash/screenshots/dash_debug_alert.png")
        print("Dash debug alert is not visible, indicating success.")
        assert True, "Dash debug alert is not visible, indicating success."
