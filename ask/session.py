import json
import uuid
from pathlib import Path
from typing import List, Dict, Any

def gen_id(prefix: str = "msg") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:6]}"

def sync_thread_file(filepath: Path, msgs: List[Dict[str, Any]]):
    if not filepath:
        return
    try:
        if filepath.exists():
            try:
                with open(filepath, 'r') as f:
                    disk_msgs = json.load(f)
            except (json.JSONDecodeError, IOError):
                disk_msgs = []

            existing_ids = {m.get('id') for m in msgs if m.get('id')}
            for m in disk_msgs:
                if m.get('id') and m.get('id') not in existing_ids:
                    msgs.append(m)

        temp_file = filepath.with_suffix(".tmp")
        with open(temp_file, 'w') as f:
            json.dump(msgs, f)
        temp_file.replace(filepath)
    except Exception:
        # Silently fail as in original code, but could be improved
        pass
