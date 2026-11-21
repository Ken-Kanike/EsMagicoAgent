#!/usr/bin/env python3
import sys
import os
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

def check_environment():
    print("=" * 60)
    print("EsMagico Invoice Pipeline — Environment & Dependency Check")
    print("=" * 60)
    print(f"Python Version: {sys.version.split()[0]}")
    print(f"Working Directory: {Path.cwd()}")

    required_pkgs = [
        ("pymupdf", "PDF text & rendering engine"),
        ("PIL", "Pillow image library"),
        ("pytesseract", "Tesseract OCR interface"),
        ("pydantic", "Schema validation engine"),
        ("pydantic_settings", "Settings and env configuration"),
        ("fastapi", "REST API framework"),
        ("uvicorn", "ASGI server"),
        ("streamlit", "Operational dashboard"),
        ("groq", "Groq Cloud API SDK"),
        ("openai", "OpenAI / Local LLM / Antigravity gateway"),
        ("rich", "Terminal reporting and formatting"),
        ("typer", "CLI argument parser"),
        ("rapidfuzz", "Fuzzy evaluation matching engine"),
    ]

    all_ok = True
    for mod_name, desc in required_pkgs:
        try:
            __import__(mod_name)
            print(f"  [OK]  {mod_name:<18} - {desc}")
        except ImportError:
            print(f"  [FAIL] {mod_name:<18} - MISSING ({desc})")
            all_ok = False

    print("\nChecking Tesseract OCR binary...")
    try:
        import pytesseract
        from config.settings import settings
        from pipeline.ocr_engine import check_tesseract_available
        if check_tesseract_available():
            v = pytesseract.get_tesseract_version()
            print(f"  [OK]  Tesseract binary is active and functional (version {v})")
        else:
            print("  [WARN] Tesseract binary not detected. Scanned documents without digital text will fall back to multimodal Vision models.")
    except Exception as e:
        print(f"  [WARN] OCR check error: {e}")

    print("\nChecking Data Directory...")
    from config.settings import settings
    lab_dir = settings.resolve_path(settings.labelled_dir)
    unlab_dir = settings.resolve_path(settings.unlabelled_dir)

    if lab_dir.exists():
        lab_files = list(lab_dir.glob("L*.*"))
        print(f"  [OK]  Labelled directory found with {len(lab_files)} files: {lab_dir}")
    else:
        print(f"  [FAIL] Labelled directory missing: {lab_dir}")
        all_ok = False

    if unlab_dir.exists():
        unlab_files = list(unlab_dir.glob("U*.*"))
        print(f"  [OK]  Unlabelled directory found with {len(unlab_files)} files: {unlab_dir}")
    else:
        print(f"  [FAIL] Unlabelled directory missing: {unlab_dir}")
        all_ok = False

    print("=" * 60)
    if all_ok:
        print("[SUCCESS] All system prerequisites are satisfied. Ready to run extraction and evaluation.")
    else:
        print("[NOTICE] Some dependencies need attention before running full suite.")
    print("=" * 60)

if __name__ == "__main__":
    check_environment()
