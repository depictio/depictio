import requests
from getpass import getpass
import os

# The CLI client class
class CLI_Client:
    def __init__(self):
        self.api_url = 'http://localhost:8058/'  # Replace with your actual API URL
        self.auth_url = 'http://localhost:8080/realms/DEPICTIO/protocol/openid-connect/token'  # Keycloak token endpoint
        self.client_id = 'depictio-cli'  # The client_id you set up in Keycloak for your CLI
        self.token = None

    def login(self, username, password):
        data = {
            'client_id': self.client_id,
            'username': username,
            'password': password,
            'grant_type': 'password',
        }
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded'  # Required header for Keycloak token endpoint
        }
        response = requests.post(self.auth_url, data=data, headers=headers)
        print(response)
        print(response.json())
        print(data)
        if response.status_code == 200:
            self.token = response.json()['access_token']
            self.save_token()
        else:
            print(f"Login failed: {response.status_code} {response.reason}")

    def save_token(self):
        config_path = os.path.expanduser("~/.depictio/config")
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        with open(config_path, 'w') as config_file:
            config_file.write(self.token)

    def load_token(self):
        config_path = os.path.expanduser("~/.depictio/config")
        if os.path.exists(config_path):
            with open(config_path, 'r') as config_file:
                self.token = config_file.read()

    def call_api(self, endpoint):
        headers = {'Authorization': f'Bearer {self.token}'}
        print(headers)
        response = requests.get(f'{self.api_url}{endpoint}', headers=headers)
        if response.ok:
            return response.json()
        else:
            print(f"Failed to call API: {response.status_code} {response.reason}")

    def logout(self):
        self.token = None
        config_path = os.path.expanduser("~/.depictio/config")
        if os.path.exists(config_path):
            os.remove(config_path)
        print("You have been logged out.")

# The CLI interaction
def main():
    client = CLI_Client()
    client.load_token()

    while True:
        command = input("Enter command (login, call_api, logout, quit): ").strip().lower()
        if command == 'login':
            if client.token:
                print("Already logged in.")
            else:
                username = input("Username: ").strip()
                password = getpass("Password: ").strip()
                client.login(username, password)
        elif command == 'call_api':
            if client.token:
                endpoint = input("API Endpoint to call: ").strip()
                result = client.call_api(endpoint)
                print(result if result else "API call failed.")
            else:
                print("You need to login first.")
        elif command == 'logout':
            client.logout()
        elif command == 'quit':
            break
        else:
            print("Unknown command.")

if __name__ == '__main__':
    main()
