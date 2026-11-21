#!/usr/bin/env python3
import sys
import webbrowser
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import uvicorn
from api.main import app

def main():
    print("=" * 66)
    print("🚀 EsMagico Enterprise AP Telemetry & Extraction Dashboard")
    print("   Grafana-Themed Dark Operations Suite (JavaScript / Tailwind / Chart.js)")
    print("=" * 66)
    print("   • Live Dashboard URL : http://localhost:8000")
    print("   • REST API / Docs    : http://localhost:8000/docs")
    print("=" * 66)
    print("Starting server on port 8000... Press Ctrl+C to terminate.")

    # Automatically attempt opening in browser
    try:
        webbrowser.open("http://localhost:8000")
    except Exception:
        pass

    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")

if __name__ == "__main__":
    main()
