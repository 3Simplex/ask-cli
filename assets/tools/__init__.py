"""
Dynamic state management tools.

These modules are auto-discovered by ask.py's _load_tool_modules()
which imports all submodules from assets/tools/.
"""
from importlib import import_module
from pkgutil import iter_modules
from pathlib import Path as _P

# Registration is an import side effect of each @ask_tool module. Relying on an
# external entry point to import them left the registry silently incomplete for
# any other importer (a state then listed tools whose schemas were never emitted).
# Discover our own submodules so importing this package always yields the full set.
for _m in iter_modules([str(_P(__file__).parent)]):
    if _m.name and not _m.name.startswith("_"):
        import_module(f"{__name__}.{_m.name}")
