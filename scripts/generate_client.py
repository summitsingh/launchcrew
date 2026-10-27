"""Emit the canonical API contract without a database connection."""
import json
from pathlib import Path
from backend.app import app
path = Path(__file__).resolve().parents[1] / 'backend/openapi.json'
path.write_text(json.dumps(app.openapi(), indent=2, sort_keys=True) + '\n')
print('Updated backend/openapi.json; run pnpm --dir web client:generate next.')
