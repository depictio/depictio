from jose import jwt

# Example payload
payload = {"username": "jdoe", "name": "John Doe", "email": "john.doe@embl.de"}

# Read your generated private key
with open("dev/token/private_key.pem", "rb") as f:
    private_key = f.read()

# Create the JWT
token = jwt.encode(payload, private_key, algorithm="RS256")

with open("dev/token/token.txt", "w") as f:
    f.write(token)
print(token)
