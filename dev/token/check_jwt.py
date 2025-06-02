from jose import jwt, JWTError

# Read your generated public key
with open("dev/token/public_key.pem", "rb") as f:
    public_key = f.read()

with open("dev/token/token.txt", "r") as f:
    token = f.read()

# Verify and decode the JWT
try:
    decoded = jwt.decode(token, public_key, algorithms=["RS256"])
    print(decoded)
except JWTError as e:
    print("Token verification failed:", e)
