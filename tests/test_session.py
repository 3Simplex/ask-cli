import json
from pathlib import Path
from ask.session import gen_id, sync_thread_file

def test_gen_id():
    msg_id = gen_id("test")
    assert msg_id.startswith("test_")
    assert len(msg_id) == len("test_") + 6

def test_sync_thread_file_new_file(tmp_path):
    filepath = tmp_path / "test_session.json"
    msgs = [{"id": "msg_1", "role": "user", "content": "hello"}]
    sync_thread_file(filepath, msgs)

    assert filepath.exists()
    with open(filepath, 'r') as f:
        data = json.load(f)
    assert data == msgs

def test_sync_thread_file_merge(tmp_path):
    filepath = tmp_path / "test_session.json"
    initial_msgs = [{"id": "msg_1", "role": "user", "content": "hello"}]
    with open(filepath, 'w') as f:
        json.dump(initial_msgs, f)

    current_msgs = [{"id": "msg_2", "role": "assistant", "content": "hi"}]
    sync_thread_file(filepath, current_msgs)

    with open(filepath, 'r') as f:
        data = json.load(f)
    # The order might be a bit weird because of how sync_thread_file works (it appends disk msgs to current msgs if IDs don't match)
    assert any(m["id"] == "msg_1" for m in data)
    assert any(m["id"] == "msg_2" for m in data)
    assert len(data) == 2
