---
name: batch-process
description: Batch process a folder of invoice documents and save structured JSON files into outputs/.
---

# Batch Processing Skill

Scans any directory for PDF and image documents, extracts fields, performs Pydantic validation, and writes individual JSON outputs.

## Command
```bash
python scripts/batch.py <folder_path> [--mode no_ai|groq|local|gemini|openai] [--output-dir outputs]
```

## Example
```bash
# Process all unlabelled documents
python scripts/batch.py "Es Magico - AI Intern Assignment - Sample Pack/unlabelled" --mode groq
```
