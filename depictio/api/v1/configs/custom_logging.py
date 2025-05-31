import logging
import re
import sys
from io import StringIO
from typing import Any

import pydantic
from colorlog import ColoredFormatter

# Import Rich components
from rich.console import Console
from rich.highlighter import ReprHighlighter
from rich.pretty import Pretty
from rich.theme import Theme

# Define a custom theme similar to Rich's default but with adjustments for Pydantic models
custom_theme = Theme(
    {
        "repr.tag_name": "bold magenta",  # Object name in bold pink/magenta
        "repr.attrib_name": "yellow",  # Keys in yellow
        "repr.attrib_value": "green",  # Values in green
        "repr.attrib_equal": "dim",  # Equal signs dimmed
        "repr.bool_true": "bold bright_green",  # True values in bold green
        "repr.bool_false": "bold bright_red",  # False values in bold red
        "repr.none": "dim",  # None values dimmed
        "repr.number": "cyan",  # Numbers in cyan
        "repr.str": "green",  # Strings in green
        "repr.brace": "bold dim",  # Braces in bold dim
    }
)


def format_pydantic(
    model: pydantic.BaseModel, max_line_length: int = 80, color: bool = True
) -> str:
    """
    Format a Pydantic model with custom styling for use in f-strings.

    Args:
        model: A Pydantic model instance
        max_line_length: Maximum length for single-line representation
        color: Whether to apply ANSI color formatting

    Returns:
        Formatted string representation of the model
    """
    if not isinstance(model, pydantic.BaseModel):
        return str(model)

    # Get model data
    model_dict = model.model_dump() if hasattr(model, "model_dump") else model.dict()
    model_name = model.__class__.__name__

    # First, generate plain text versions for length calculation
    items = []
    formatted_items = []

    for key, value in model_dict.items():
        # Store plain text version for length calculation
        items.append(f"{key}={_plain_format_value(value)}")

        # Store formatted version for display
        if color:
            formatted_value = _color_format_value(value)
            formatted_items.append(f"\033[33m{key}\033[0m={formatted_value}")
        else:
            formatted_items.append(f"{key}={_plain_format_value(value)}")

    # Calculate the plain text length (without ANSI codes)
    plain_text_length = len(f"{model_name}({', '.join(items)})")

    # Create the formatted version
    if color:
        single_line = f"\033[1;95m{model_name}\033[0m({', '.join(formatted_items)})"
    else:
        single_line = f"{model_name}({', '.join(formatted_items)})"

    # If it's short enough, return the single line version
    if plain_text_length <= max_line_length:
        return single_line

    # Otherwise, create a multi-line representation
    if color:
        lines = [f"\033[1;95m{model_name}\033[0m("]
        for key, value in model_dict.items():
            formatted_value = _color_format_value(value)
            lines.append(f"    \033[33m{key}\033[0m={formatted_value},")
    else:
        lines = [f"{model_name}("]
        for key, value in model_dict.items():
            lines.append(f"    {key}={_plain_format_value(value)},")

    lines.append(")")
    return "\n".join(lines)


def _plain_format_value(value: Any) -> str:
    """Format a value without ANSI colors"""
    if value is None:
        return "None"
    elif isinstance(value, bool):
        return str(value)
    elif isinstance(value, int | float):
        return str(value)
    elif isinstance(value, str):
        # For strings, use a shortened version if too long
        if len(value) > 30:
            return f"'{value[:27]}...'"
        return f"'{value}'"
    # Check for MongoDB ObjectId - display in full
    elif str(type(value)).find("ObjectId") != -1:
        return str(value)
    elif isinstance(value, list | tuple):
        # For short collections, show content
        if len(value) <= 3:
            items = [_plain_format_value(item) for item in value]
            return f"[{', '.join(items)}]" if isinstance(value, list) else f"({', '.join(items)})"
        # Otherwise, indicate length
        return f"[{len(value)} items]" if isinstance(value, list) else f"({len(value)} items)"
    elif isinstance(value, dict):
        # For small dicts, show content
        if len(value) <= 2:
            items = [f"{k}: {_plain_format_value(v)}" for k, v in value.items()]
            return f"{{{', '.join(items)}}}"
        # Otherwise, indicate size
        return f"{{{len(value)} items}}"
    else:
        # For other complex types
        repr_val = repr(value)
        # Don't truncate ObjectId strings
        if "ObjectId" in repr_val:
            return repr_val
        # Truncate other long representations
        if len(repr_val) > 30:
            return repr_val[:27] + "..."
        return repr_val


def _color_format_value(value: Any) -> str:
    """Format a value with ANSI color codes"""
    if value is None:
        return "\033[2mNone\033[0m"  # Dimmed for None
    elif isinstance(value, bool):
        return "\033[1;92mTrue\033[0m" if value else "\033[1;91mFalse\033[0m"  # Green/red for bool
    elif isinstance(value, int | float):
        return f"\033[36m{value}\033[0m"  # Cyan for numbers
    elif isinstance(value, str):
        # For strings, use shortened version if too long
        if len(value) > 30:
            return f"\033[32m'{value[:27]}...'\033[0m"  # Green for strings
        return f"\033[32m'{value}'\033[0m"  # Green for strings
    # Check for MongoDB ObjectId
    elif str(type(value)).find("ObjectId") != -1:
        return f"\033[36m{value}\033[0m"  # Cyan for ObjectId
    elif isinstance(value, list):
        # For lists, show items if short
        if len(value) <= 3:
            items = [_color_format_value(item) for item in value]
            return f"\033[1;37m[\033[0m{', '.join(items)}\033[1;37m]\033[0m"
        # Otherwise, indicate length
        return f"\033[1;37m[\033[0m{len(value)} items\033[1;37m]\033[0m"
    elif isinstance(value, tuple):
        # For tuples, show items if short
        if len(value) <= 3:
            items = [_color_format_value(item) for item in value]
            return f"\033[1;37m(\033[0m{', '.join(items)}\033[1;37m)\033[0m"
        # Otherwise, indicate length
        return f"\033[1;37m(\033[0m{len(value)} items\033[1;37m)\033[0m"
    elif isinstance(value, dict):
        # For small dicts, show content
        if len(value) <= 2:
            items = [f"\033[33m{k}\033[0m: {_color_format_value(v)}" for k, v in value.items()]
            return f"\033[1;37m{{\033[0m{', '.join(items)}\033[1;37m}}\033[0m"
        # Otherwise, indicate size
        return f"\033[1;37m{{\033[0m{len(value)} items\033[1;37m}}\033[0m"
    else:
        # For other complex types
        repr_val = repr(value)
        # Don't truncate ObjectId strings
        if "ObjectId" in repr_val:
            return f"\033[36m{repr_val}\033[0m"  # Cyan for ObjectId
        # Truncate other long representations
        if len(repr_val) > 30:
            return f"{repr_val[:27]}..."
        return repr_val


class RichReprFormatter(ColoredFormatter):
    """
    A formatter that uses Rich-like styling for Pydantic models
    while maintaining the standard colored log format.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Create a Rich console with our custom theme
        self.string_console = Console(
            highlight=True, width=120, theme=custom_theme, file=StringIO()
        )
        self.highlighter = ReprHighlighter()
        self.max_single_line_length = 80  # Adjust this based on your terminal width preference

    def _is_pydantic_model(self, obj):
        """Check if an object is a Pydantic model instance"""
        return hasattr(obj, "__class__") and issubclass(obj.__class__, pydantic.BaseModel)

    def _format_pydantic_model(self, model):
        """Format a Pydantic model with custom styling similar to rich.print"""
        model_dict = model.model_dump() if hasattr(model, "model_dump") else model.dict()
        model_name = model.__class__.__name__

        # First, try to create a compact single-line representation
        items = []
        formatted_items = []
        for key, value in model_dict.items():
            # Store plain text version for length calculation
            items.append(f"{key}={value}")
            # Store formatted version for display
            formatted_value = self._format_value(value)
            formatted_items.append(f"\033[33m{key}\033[0m={formatted_value}")

        # Calculate the plain text length (without ANSI codes)
        plain_text_length = len(f"{model_name}({', '.join(items)})")

        # Create formatted version for display
        single_line = f"\033[1;95m{model_name}\033[0m({', '.join(formatted_items)})"

        # If the plain text is short enough, return the single line version
        if plain_text_length <= self.max_single_line_length:
            return single_line

        # Otherwise, create a multi-line representation
        lines = [f"\033[1;95m{model_name}\033[0m("]
        for key, value in model_dict.items():
            formatted_value = self._format_value(value)
            lines.append(f"    \033[33m{key}\033[0m={formatted_value},")
        lines.append(")")
        return "\n".join(lines)

    def _format_value(self, value):
        """Format a value with appropriate styling to match rich.print"""
        if value is None:
            return "\033[2mNone\033[0m"  # Dimmed for None values
        elif isinstance(value, bool):
            return (
                "\033[1;92mTrue\033[0m" if value else "\033[1;91mFalse\033[0m"
            )  # Bold green/red for booleans
        elif isinstance(value, int | float):
            return f"\033[36m{value}\033[0m"  # Cyan for numbers
        elif isinstance(value, str):
            # For strings, use a shortened version if too long
            if len(value) > 30:  # Adjust this threshold as needed
                shortened = value[:27] + "..."
                return f"\033[32m'{shortened}'\033[0m"  # Green for strings
            return f"\033[32m'{value}'\033[0m"  # Green for strings
        # Check for MongoDB ObjectId
        elif str(type(value)).find("ObjectId") != -1:
            # Display ObjectId in full for better debugging
            return f"\033[36m{value}\033[0m"  # Cyan for ObjectId
        elif isinstance(value, list):
            # For lists, use a compact representation if short
            if len(value) <= 3:
                items = [self._format_value(item) for item in value]
                compact = f"\033[1;37m[\033[0m{', '.join(items)}\033[1;37m]\033[0m"
                if len(compact) <= 40:  # Adjust threshold as needed
                    return compact
            # Otherwise, indicate list length
            return f"\033[1;37m[\033[0m{len(value)} items\033[1;37m]\033[0m"
        elif isinstance(value, tuple):
            # Similar compact handling for tuples
            if len(value) <= 3:
                items = [self._format_value(item) for item in value]
                compact = f"\033[1;37m(\033[0m{', '.join(items)}\033[1;37m)\033[0m"
                if len(compact) <= 40:
                    return compact
            return f"\033[1;37m(\033[0m{len(value)} items\033[1;37m)\033[0m"
        elif isinstance(value, dict):
            # For small dicts, show content, otherwise show size
            if len(value) <= 2:
                items = [f"\033[33m{k}\033[0m: {self._format_value(v)}" for k, v in value.items()]
                compact = f"\033[1;37m{{\033[0m{', '.join(items)}\033[1;37m}}\033[0m"
                if len(compact) <= 40:
                    return compact
            return f"\033[1;37m{{\033[0m{len(value)} items\033[1;37m}}\033[0m"
        else:
            # For other complex types, use repr but limit length
            repr_val = repr(value)
            # Don't truncate ObjectId strings
            if "ObjectId" in repr_val:
                return f"\033[36m{repr_val}\033[0m"  # Cyan for ObjectId
            elif len(repr_val) > 30:  # Adjust threshold as needed
                return repr_val[:27] + "..."
            return repr_val

    def format(self, record):
        # Process the message if it's a Pydantic model
        if hasattr(record, "msg"):
            if self._is_pydantic_model(record.msg):
                try:
                    # Create a string representation of the model for inspection
                    model_str = str(record.msg)

                    # If the model string contains "ObjectId" but has truncated values ("..."),
                    # create a direct string representation that preserves the full IDs
                    if "ObjectId" in model_str and "..." in model_str:
                        # Get the model's dictionary data
                        model_dict = (
                            record.msg.model_dump()
                            if hasattr(record.msg, "model_dump")
                            else record.msg.dict()
                        )
                        model_name = record.msg.__class__.__name__

                        # Manually format with special handling for ObjectId fields
                        parts = []
                        for key, value in model_dict.items():
                            if "ObjectId" in str(value):
                                parts.append(f"{key}={value}")
                            else:
                                parts.append(
                                    f"{key}='{value}'"
                                    if isinstance(value, str)
                                    else f"{key}={value}"
                                )

                        record.msg = f"{model_name}({', '.join(parts)})"
                    else:
                        # Use our custom Pydantic formatter for non-ObjectId cases
                        record.msg = self._format_pydantic_model(record.msg)
                except Exception:
                    # If formatting fails, use the Rich console as fallback
                    try:
                        self.string_console.file = StringIO()
                        self.string_console.print(Pretty(record.msg))
                        record.msg = self.string_console.file.getvalue().strip()
                    except Exception:
                        # Last resort: leave as is
                        pass
            # Handle dictionaries and other complex objects with Rich
            elif not isinstance(record.msg, str | int | float | bool | type(None)):
                try:
                    self.string_console.file = StringIO()
                    self.string_console.print(Pretty(record.msg))
                    record.msg = self.string_console.file.getvalue().strip()
                except Exception:
                    pass

        # Shorten pathname to start from 'depictio/'
        if hasattr(record, "pathname"):
            match = re.search(r"(depictio/.*?)$", record.pathname)
            if match:
                record.pathname = match.group(1)

        # Use the parent formatter
        return super().format(record)


def setup_logging(name=None, level="INFO"):
    """
    Set up logging with:
    - Path from depictio folder only
    - Colored level name
    - Bold line number
    - Bold function name
    - Rich-like representation for Pydantic models with pink object names and yellow keys
    """
    # Get the numeric logging level
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    # Create logger
    logger = logging.getLogger("depictio")
    logger.setLevel(numeric_level)

    # Ensure propagation to root logger
    logger.propagate = True

    # Remove any existing handlers to avoid duplicates
    if logger.handlers:
        logger.handlers = []

    # Create our custom formatter
    formatter = RichReprFormatter(
        "%(asctime)s - %(log_color)s%(levelname)s%(reset)s - %(pathname)s:%(bold)s%(lineno)d%(reset)s - %(bold)s%(funcName)s%(reset)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        reset=True,
        log_colors={
            "DEBUG": "cyan",
            "INFO": "green",
            "WARNING": "yellow",
            "ERROR": "red",
            "CRITICAL": "red,bg_white",
        },
        secondary_log_colors={
            "bold": {
                "DEBUG": "bold",
                "INFO": "bold",
                "WARNING": "bold",
                "ERROR": "bold",
                "CRITICAL": "bold",
            }
        },
        style="%",
    )

    # Create a console handler and set the formatter
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    # Add the handler to the logger
    logger.addHandler(console_handler)

    return logger


# The logger will be initialized by logging_init.py
