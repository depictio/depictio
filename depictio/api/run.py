
import uvicorn
from main import app
from depictio.api.v1.configs.config import settings

if __name__ == "__main__":
    uvicorn.run("main:app", host=settings.fastapi.host, port=settings.fastapi.port, reload=True)
