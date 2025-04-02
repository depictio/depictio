
import logging
from colorlog import ColoredFormatter

# def setup_logging(logging_level: str):
    
# Create a colored formatter
formatter = ColoredFormatter(
    "%(log_color)s%(asctime)s%(reset)s - %(name)s - %(log_color)s%(levelname)s%(reset)s - %(filename)s - %(funcName)s - line %(lineno)d - %(message)s",
    datefmt=None,
    reset=True,
    log_colors={
        'DEBUG':    'cyan',
        'INFO':     'green',
        'WARNING':  'yellow',
        'ERROR':    'red',
        'CRITICAL': 'red,bg_white',
    },
    secondary_log_colors={},
    style='%'
)

# Create a console handler and set the formatter
handler = logging.StreamHandler()
handler.setFormatter(formatter)

# Set the logging level
logging.basicConfig(level=logging.INFO, handlers=[handler])

# Get the logger
logger = logging.getLogger("depictio")
# return logger
