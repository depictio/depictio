#!/usr/bin/env python3
"""
Extract OpenAPI specification from a running Depictio API instance.

This script fetches the openapi.json from a running API server.
Use this for local development or manual documentation updates.

Usage:
    python scripts/extract_openapi.py [output_path] [api_url]

Examples:
    # Fetch from local instance and save to docs
    python scripts/extract_openapi.py ../depictio-docs/docs/api/openapi.json

    # Fetch from specific URL
    python scripts/extract_openapi.py openapi.json http://localhost:8058

    # Print to stdout
    python scripts/extract_openapi.py
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen


def fetch_openapi(api_url: str = "http://localhost:8058") -> dict:
    """
    Fetch OpenAPI specification from a running API instance.

    Args:
        api_url: Base URL of the Depictio API.

    Returns:
        The OpenAPI specification as a dictionary.

    Raises:
        URLError: If the API is not reachable.
    """
    openapi_url = f"{api_url.rstrip('/')}/openapi.json"

    try:
        with urlopen(openapi_url, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except URLError as e:
        print(f"Error: Could not connect to {openapi_url}", file=sys.stderr)
        print("Make sure the Depictio API is running.", file=sys.stderr)
        print(f"Details: {e}", file=sys.stderr)
        raise


def extract_openapi(
    output_path: str | None = None,
    api_url: str = "http://localhost:8058",
) -> dict:
    """
    Extract and optionally save OpenAPI specification.

    Args:
        output_path: Optional path to write the JSON file.
        api_url: Base URL of the Depictio API.

    Returns:
        The OpenAPI specification as a dictionary.
    """
    openapi_schema = fetch_openapi(api_url)

    # Add generation metadata
    openapi_schema["info"]["x-generated-at"] = datetime.now(tz=timezone.utc).isoformat()

    if output_path:
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(openapi_schema, f, indent=2, ensure_ascii=False)
        print(f"OpenAPI specification written to: {output_file}")
        print(f"Endpoints: {len(openapi_schema.get('paths', {}))}")
    else:
        print(json.dumps(openapi_schema, indent=2, ensure_ascii=False))

    return openapi_schema


def main() -> None:
    """Main entry point."""
    output_path = sys.argv[1] if len(sys.argv) > 1 else None
    api_url = sys.argv[2] if len(sys.argv) > 2 else "http://localhost:8058"

    try:
        extract_openapi(output_path, api_url)
    except URLError:
        sys.exit(1)


if __name__ == "__main__":
    main()
