
import uvicorn
from main import app

if __name__ == "__main__":
    uvicorn.run("main:app", host="localhost", port=8058, reload=True)
