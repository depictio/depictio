import logging
from rich.logging import RichHandler
from rich import print
from pydantic import BaseModel


FORMAT = "%(message)s"
logging.basicConfig(level="NOTSET", format=FORMAT, datefmt="[%X]", handlers=[RichHandler()])


class User(BaseModel):
    email: str
    hashed_password: str
    full_name: str
    disabled: bool = False
    prop1: str = "default_value"
    prop2: int = 0
    prop3: bool = False
    prop4: float = 0.0
    prop5: str = "default_value"
    prop6: str = "default_value"
    prop7: str = "default_value"
    prop8: str = "default_value"
    prop9: str = "default_value"
    prop10: str = "default_value"
    prop11: str = "default_value"
    prop12: str = "default_value"
    prop13: str = "default_value"
    prop14: str = "default_value"
    prop15: str = "default_value"


user = User(
    email="test@test.com", hashed_password="hashed_password", full_name="Test User", disabled=False
)

log = logging.getLogger("rich")
log.info("Hello, World!")
log.info(f"User : {user}")
print(f"User : {user}")
print(user)
