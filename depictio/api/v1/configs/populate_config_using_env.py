import os
from dotenv import load_dotenv
import yaml

# Load environment variables
load_dotenv()

# Function to replace placeholders with .env values
def replace_placeholders(template, env_vars):
    for key, value in env_vars.items():
        placeholder = f"${key}"
        if placeholder in template:
            template = template.replace(placeholder, value)
    return template

# Load the template
template_path = 'config_backend_template.yaml'
with open(template_path, 'r') as file:
    template_content = file.read()

# Replace placeholders in the template with actual values from .env
env_vars = os.environ
final_content = replace_placeholders(template_content, env_vars)

# Output the final YAML
final_path = 'config_backend.yaml'
with open(final_path, 'w') as file:
    yaml.safe_load(final_content)  # Validate YAML syntax
    file.write(final_content)

print("config_backend.yaml has been updated.")
