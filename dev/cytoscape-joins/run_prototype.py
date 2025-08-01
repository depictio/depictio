#!/usr/bin/env python3
"""
Smart launcher for the cytoscape prototype that handles port conflicts.
"""

import socket
import subprocess
import sys
from pathlib import Path


def is_port_in_use(port):
    """Check if a port is already in use."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', port)) == 0


def find_free_port(start_port=8051, max_attempts=10):
    """Find a free port starting from start_port."""
    for port in range(start_port, start_port + max_attempts):
        if not is_port_in_use(port):
            return port
    return None


def kill_process_on_port(port):
    """Kill any process running on the specified port."""
    try:
        # Find process using the port
        result = subprocess.run(
            ['lsof', '-ti', f':{port}'], 
            capture_output=True, 
            text=True, 
            timeout=5
        )
        
        if result.returncode == 0 and result.stdout.strip():
            pids = result.stdout.strip().split('\n')
            for pid in pids:
                if pid:
                    print(f"🔪 Killing process {pid} on port {port}")
                    subprocess.run(['kill', '-9', pid], timeout=5)
                    return True
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, FileNotFoundError):
        pass
    
    return False


def main():
    """Main launcher function."""
    print("🚀 Cytoscape Joins Prototype Launcher")
    print("=" * 40)
    
    # Get the prototype file path
    prototype_file = Path(__file__).parent / "cytoscape_joins_prototype.py"
    
    if not prototype_file.exists():
        print("❌ Error: cytoscape_joins_prototype.py not found!")
        sys.exit(1)
    
    # Check if port 8052 is free (the current default)
    preferred_port = 8052
    
    if is_port_in_use(preferred_port):
        print(f"⚠️  Port {preferred_port} is already in use")
        
        # Ask user if they want to kill the existing process
        response = input(f"Kill process on port {preferred_port}? (y/n): ").lower().strip()
        
        if response in ['y', 'yes']:
            if kill_process_on_port(preferred_port):
                print(f"✅ Freed port {preferred_port}")
            else:
                print(f"❌ Could not free port {preferred_port}, finding alternative...")
                preferred_port = find_free_port(8053)
        else:
            # Find alternative port
            preferred_port = find_free_port(8053)
    
    if preferred_port is None:
        print("❌ Could not find a free port!")
        sys.exit(1)
    
    # Update the port in the prototype file if needed
    if preferred_port != 8052:
        print(f"📝 Using port {preferred_port}")
        
        # Read the current file
        content = prototype_file.read_text()
        
        # Replace the port
        updated_content = content.replace(
            "app.run(debug=True, port=8052)",
            f"app.run(debug=True, port={preferred_port})"
        )
        
        # Write back if changed
        if updated_content != content:
            prototype_file.write_text(updated_content)
    
    # Launch the prototype
    print(f"🎯 Starting prototype on http://localhost:{preferred_port}")
    print("📊 Features:")
    print("  - Interactive network visualization")
    print("  - Theme switching (light/dark)")
    print("  - Node selection and details")
    print("  - Drag, zoom, and pan")
    print("  - Join relationship visualization")
    print()
    print("Press Ctrl+C to stop the server")
    print("-" * 40)
    
    try:
        # Run the prototype
        subprocess.run([sys.executable, str(prototype_file)], check=True)
    except KeyboardInterrupt:
        print("\n👋 Prototype stopped by user")
    except subprocess.CalledProcessError as e:
        print(f"❌ Error running prototype: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()