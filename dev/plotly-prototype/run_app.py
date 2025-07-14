#!/usr/bin/env python3
"""
Simple launcher script for the Plotly Code Prototype

Usage:
    python run_app.py [--debug] [--port PORT] [--host HOST]
"""

import argparse
import sys

from plotly_prototype_app import main


def parse_args():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description="Plotly Code Prototype - Secure Python/Plotly execution environment"
    )
    parser.add_argument(
        "--debug", 
        action="store_true", 
        default=True,
        help="Run in debug mode (default: True)"
    )
    parser.add_argument(
        "--port", 
        type=int, 
        default=8050,
        help="Port to run the app on (default: 8050)"
    )
    parser.add_argument(
        "--host", 
        type=str, 
        default="127.0.0.1",
        help="Host to run the app on (default: 127.0.0.1)"
    )
    return parser.parse_args()


def run_app():
    """Run the Plotly Code Prototype app"""
    args = parse_args()
    
    print("🚀 Starting Plotly Code Prototype")
    print("=" * 50)
    print(f"Host: {args.host}")
    print(f"Port: {args.port}")
    print(f"Debug: {args.debug}")
    print(f"URL: http://{args.host}:{args.port}")
    print("=" * 50)
    
    try:
        # Create and run the app
        app = main()
        app.run(
            debug=args.debug,
            host=args.host,
            port=args.port
        )
    except KeyboardInterrupt:
        print("\n👋 Shutting down Plotly Code Prototype")
    except Exception as e:
        print(f"❌ Error running app: {e}")
        sys.exit(1)


if __name__ == "__main__":
    run_app()