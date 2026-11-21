import json
from pathlib import Path
from typing import Dict, Any, Optional
from config.settings import settings

def write_output(file_stem: str, data: Dict[str, Any], output_dir: Optional[Path] = None) -> Path:
    """Save formatted extraction JSON to outputs directory."""
    target_dir = output_dir or settings.resolve_path(settings.outputs_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    out_file = target_dir / f"{file_stem}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return out_file

def read_output(file_stem: str, output_dir: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """Read an existing output JSON file if available."""
    target_dir = output_dir or settings.resolve_path(settings.outputs_dir)
    out_file = target_dir / f"{file_stem}.json"
    if not out_file.exists():
        return None
    with open(out_file, "r", encoding="utf-8") as f:
        return json.load(f)
