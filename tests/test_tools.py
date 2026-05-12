import json
from ask.tools import parse_tool_call

def test_parse_tool_call_legacy():
    content = "Some text before\nTOOL: {\"name\": \"run\", \"command\": \"ls\"}\nSome text after"
    result = parse_tool_call(content)
    assert result == {"name": "run", "command": "ls"}

def test_parse_tool_call_native():
    content = "Call this tool: call:run{command: \"ls -la\"}"
    result = parse_tool_call(content)
    assert result == {"name": "run", "command": "ls -la"}

def test_parse_tool_call_invalid():
    content = "No tool call here"
    result = parse_tool_call(content)
    assert result is None

def test_parse_tool_call_malformed_json():
    content = "TOOL: {invalid json}"
    result = parse_tool_call(content)
    # It should fall through to native check, and if that also fails, return None
    assert result is None
