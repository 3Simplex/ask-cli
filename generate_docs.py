#!/usr/bin/env python3
"""Derive documentation inventory tables from source into marked blocks.

AST-only by design: this must run under a bare interpreter with no third-party
packages (no venv; deps live in the Nix store). It never imports ask.py or
assets.* -- importing them would pull requests/rich and defeat the point.

Usage:
  generate_docs.py                  regenerate in place
  generate_docs.py --check          exit 1 with a per-file diff if any block is stale
  generate_docs.py --stdout --section NAME   print one block without writing
"""
import argparse
import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DOCS = ROOT / "docs"

BEGIN = "<!-- BEGIN GENERATED: {name} — do not edit, produced by generate_docs.py -->"
END = "<!-- END GENERATED -->"


# --------------------------------------------------------------------------
# extraction helpers (never raise on an unexpected shape)
# --------------------------------------------------------------------------
def _lit(node):
    try:
        return ast.literal_eval(node)
    except Exception:
        return None


def _src(node):
    """Canonical source text for a node, for non-literal args (ast.unparse)."""
    try:
        return ast.unparse(node).strip()
    except Exception:
        return "<unavailable>"


def _parse(path):
    try:
        return ast.parse(path.read_text(), filename=str(path))
    except Exception as exc:                      # degrade, never crash
        print(f"  ! could not parse {path.relative_to(ROOT)}: {exc}", file=sys.stderr)
        return None


def _decorator_call(node, deco_name):
    for dec in getattr(node, "decorator_list", []):
        target = dec.func if isinstance(dec, ast.Call) else dec
        name = getattr(target, "id", None) or getattr(target, "attr", None)
        if name == deco_name and isinstance(dec, ast.Call):
            return dec
    return None


def _kw(call, key):
    for kw in call.keywords:
        if kw.arg == key:
            return kw.value
    return None


def _text(node):
    """Literal string, else raw source, else placeholder."""
    if node is None:
        return "(unspecified)"
    val = _lit(node)
    if isinstance(val, str):
        return val
    return _src(node)


def _iter_files(sub, pattern="*.py"):
    base = ROOT / sub
    if not base.exists():
        return
    for path in sorted(base.rglob(pattern)):
        if path.name != "__init__.py" and path.name != "base.py":
            yield path


def _walk_defs(tree):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            yield node


def _cell(value):
    """Make a string safe for a GFM table cell."""
    return re.sub(r"\s+", " ", str(value)).replace("|", "\\|").strip()


def _dict_keys(node):
    """Keys of a dict literal, in source order."""
    keys = []
    if isinstance(node, ast.Dict):
        for k in node.keys:
            keys.append(_cell(_lit(k) if _lit(k) is not None else _src(k)))
    return keys


# --------------------------------------------------------------------------
# extractors -- each returns a list of table rows (list of str)
# --------------------------------------------------------------------------
def extract_tools():
    rows = []
    for path in _iter_files("assets/tools"):
        tree = _parse(path)
        if tree is None:
            continue
        for fn in _walk_defs(tree):
            call = _decorator_call(fn, "ask_tool")
            if not call:
                continue
            args = ", ".join(_dict_keys(_kw(call, "schema_properties"))) or "(none)"
            rows.append((_text(_kw(call, "name")),
                         _text(_kw(call, "description")),
                         args))
    return sorted(rows)


def extract_evaluators():
    rows = []
    for path in _iter_files("assets/evaluators"):
        tree = _parse(path)
        if tree is None:
            continue
        for fn in _walk_defs(tree):
            call = _decorator_call(fn, "ask_evaluator")
            if not call:
                continue
            mode = _text(_kw(call, "mode"))
            stateful = _kw(call, "stateful")
            val = _lit(stateful)
            stateful = str(val) if val is not None else (_src(stateful) if stateful else "(unspecified)")
            rows.append((_text(_kw(call, "name")), _cell(mode), _cell(stateful),
                         _text(_kw(call, "description"))))
    return sorted(rows)


def extract_hooks():
    rows = []
    for path in _iter_files("assets/hooks"):
        tree = _parse(path)
        if tree is None:
            continue
        for fn in _walk_defs(tree):
            call = _decorator_call(fn, "ask_hook")
            if not call:
                continue
            rows.append((_text(_kw(call, "name")), _text(_kw(call, "description"))))
    return sorted(rows)


def extract_api_drivers():
    rows = []
    for path in _iter_files("assets/apis"):
        tree = _parse(path)
        if tree is None:
            continue
        for cls in _walk_defs(tree):
            call = _decorator_call(cls, "ask_api")
            if not call:
                continue
            rows.append((_text(_kw(call, "name")), _text(_kw(call, "description"))))
    return sorted(rows)


SYNOPSIS_RE = re.compile(r"^\s*ask\s+-ap\s+<provider>\s+(-[a-z]+)\s+(.*)$", re.S)


def extract_ap_commands():
    """AP_DISPATCH: flag -> (handler_name, usage_string).

    Values are (Name, Constant) tuples, so literal_eval on the whole dict
    fails on the Name element -- walk it by hand instead.
    """
    tree = _parse(ROOT / "ask.py")
    if tree is None:
        return []
    table = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "AP_DISPATCH" for t in node.targets):
            table = node.value
    if not isinstance(table, ast.Dict):
        print("  ! AP_DISPATCH not found as a module-level dict literal", file=sys.stderr)
        return []
    rows = []
    for key, value in zip(table.keys, table.values):
        flag = _lit(key)
        usage = "(unspecified)"
        if isinstance(value, ast.Tuple) and len(value.elts) >= 2:
            usage = _text(value.elts[1])
        elif isinstance(value, ast.Constant):
            usage = _cell(value.value)
        match = SYNOPSIS_RE.match(usage)
        synopsis = match.group(2).strip() if match else _cell(usage)
        rows.append((_cell(flag), _cell(synopsis)))
    return rows                      # source order preserved (it is meaningful)


def extract_config_keys():
    tree = _parse(ROOT / "assets/core/defaults.py")
    if tree is None:
        return []
    table = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "DEFAULTS" for t in node.targets):
            table = node.value
    if not isinstance(table, ast.Dict):
        print("  ! DEFAULTS not found as a module-level dict literal", file=sys.stderr)
        return []
    def show(node):
        val = _lit(node)
        if val is None:
            return _src(node)
        if val == "":                  # keep empty strings visible, not blank cells
            return '""'
        return val
    rows = []
    for key, value in zip(table.keys, table.values):
        rows.append((_cell(_lit(key) if _lit(key) is not None else _src(key)),
                     _cell(show(value))))
    return rows                      # source order preserved (it is meaningful)


def extract_agents():
    agents, states = [], []
    for path in sorted((ROOT / "assets/agents").glob("*.json")):
        try:
            data = json.loads(path.read_text())
        except Exception as exc:
            print(f"  ! could not read {path.relative_to(ROOT)}: {exc}", file=sys.stderr)
            continue
        name = data.get("name", path.stem)
        st = data.get("states", []) or []
        tools = data.get("tools", []) or []
        agents.append((_cell(name), _cell(", ".join(st)) or "(none)",
                       _cell(", ".join(tools)) or "(none)"))
        for state in st:
            states.append((_cell(name), _cell(state)))
    return sorted(agents), sorted(states)


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------
def render(header, rows):
    out = ["| " + " | ".join(header) + " |",
           "| " + " | ".join("---" for _ in header) + " |"]
    if not rows:
        out.append("| " + " | ".join(["_(none found)_"] + [""] * (len(header) - 1)) + " |")
    else:
        for row in rows:
            out.append("| " + " | ".join(row) + " |")
    return "\n".join(out) + "\n"


def build_sections():
    agents_rows, states_rows = extract_agents()
    return {
        "tools":          ("tools.md",        ("Tool", "Purpose", "Args"), extract_tools()),
        "evaluators":     ("evaluators.md",   ("Evaluator", "Mode", "Stateful", "Purpose"), extract_evaluators()),
        "hooks":          ("evaluators.md",   ("Hook", "Purpose"), extract_hooks()),
        "api-drivers":    ("providers.md",    ("Driver", "Purpose"), extract_api_drivers()),
        "ap-commands":    ("providers.md",    ("Command", "Synopsis"), extract_ap_commands()),
        "config-keys":    ("config.md",       ("Key", "Default"), extract_config_keys()),
        "agents":         ("agents.md",       ("Agent", "States", "Tools"), agents_rows),
        "states":         ("agents.md",       ("Agent", "State"), states_rows),
    }


def block_text(name, header, rows):
    return BEGIN.format(name=name) + "\n\n" + render(header, rows) + END + "\n"


def splice(text, name, new_block):
    """Replace the named block in place, or append it at end-of-file."""
    begin = BEGIN.format(name=name)
    start = text.find(begin)
    if start != -1:
        end = text.find(END, start)
        if end != -1:
            end += len(END)
            if text[end:end + 1] == "\n":
                end += 1
            return text[:start] + new_block + text[end:], False
    tail = text if text.endswith("\n") else text + "\n"
    return tail + "\n" + new_block, True


def main():
    parser = argparse.ArgumentParser(description="Regenerate docs inventory blocks.")
    parser.add_argument("--check", action="store_true",
                        help="write nothing; exit 1 if any generated block is stale")
    parser.add_argument("--stdout", action="store_true",
                        help="print a block instead of writing (requires --section)")
    parser.add_argument("--section", help="section name for --stdout")
    opts = parser.parse_args()

    sections = build_sections()

    if opts.stdout:
        if not opts.section:
            parser.error("--stdout requires --section")
        if opts.section not in sections:
            print(f"unknown section '{opts.section}'; known: {', '.join(sorted(sections))}",
                  file=sys.stderr)
            return 2
        doc, header, rows = sections[opts.section]
        sys.stdout.write(block_text(opts.section, header, rows))
        return 0

    stale, touched = [], []
    for name in sections:
        doc, header, rows = sections[name]
        path = DOCS / doc
        current = path.read_text() if path.exists() else ""
        new_block = block_text(name, header, rows)
        updated, _ = splice(current, name, new_block)
        if updated != current:
            stale.append((doc, name))
        if not opts.check and updated != current:
            path.write_text(updated)
            if doc not in touched:
                touched.append(doc)

    if opts.check:
        if stale:
            print("generated blocks are stale (run: python3 generate_docs.py):")
            for doc, name in stale:
                print(f"  docs/{doc}: [{name}]")
            return 1
        print("all generated blocks are up to date")
        return 0

    for doc in touched:
        print(f"updated docs/{doc}")
    if not touched:
        print("no changes (already up to date)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
