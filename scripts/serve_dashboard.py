#!/usr/bin/env python3
import sys
import socket
import argparse
import webbrowser
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import uvicorn
from api.main import app

def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((host, port)) == 0

def main():
    parser = argparse.ArgumentParser(description="Serve EsMagico AP Operations Platform")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind server (default: 8000)")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host interface (default: 127.0.0.1)")
    args = parser.parse_args()

    port = args.port
    host = args.host

    if is_port_in_use(port, host):
        print("=" * 66)
        print(f"ℹ️  Notice: EsMagico server is ALREADY running on http://{host}:{port}")
        print("   Opening your browser directly at that address...")
        print("=" * 66)
        try:
            webbrowser.open(f"http://{host}:{port}")
        except Exception:
            pass
        return

    print("=" * 66)
    print("🚀 EsMagico Enterprise AP Operations Platform")
    print(f"   • Live Dashboard URL : http://{host}:{port}")
    print(f"   • REST API / Docs    : http://{host}:{port}/docs")
    print("=" * 66)
    print(f"Starting server on port {port}... Press Ctrl+C to terminate.")

    try:
        webbrowser.open(f"http://{host}:{port}")
    except Exception:
        pass

    uvicorn.run(app, host=host, port=port, log_level="info")

if __name__ == "__main__":
    main()
