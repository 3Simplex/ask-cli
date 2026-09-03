---
when_to_read: "Building, installing, or changing Nix packaging."
related: ["config.md"]
---
# Nix

## Flake Outputs

`flake.nix` pins `nixpkgs` (nixos-unstable) and exposes, for `x86_64-linux` and
`aarch64-linux`:

- `packages.<system>.ask-cli` (and `.default`) — built from `./default.nix`
- `apps.<system>.default` — runs `bin/ask` directly (`nix run .#`)

There is **no** `checks` or `devShells` output, and **no automated test suite**.

```bash
nix build .#ask-cli     # build the package
nix run .#              # run the CLI from the flake
```

## Install Phase (default.nix)

`default.nix` builds with `makeWrapper` and a Python env of
`requests`, `rich`, `cryptography`. The install phase:

1. Creates `$out/bin` and `$out/share/ask`.
2. Copies `ask.py` → `$out/bin/ask`, `oobe.py` → `$out/bin/oobe`.
3. Copies `assets/`, `AGENTS.md`, and `docs/` → `$out/share/ask/`.
4. Patches shebangs, then wraps both binaries with:
   - `ASK_ASSETS_DIR="$out/share/ask/assets"`
   - `PYTHONPATH` prefixed with `$out/share/ask`
   - `PATH` prefixed with `ddgr`, `lynx`, `bubblewrap`, `coreutils`, `gnugrep`

> Note: `ASK_ASSETS_DIR` points at the `assets/` subdir. The shipped docs live
> one level up (`$out/share/ask/`), so consumers resolve the parent
> (`${ASK_ASSETS_DIR%/*}`) to reach `AGENTS.md` / `docs/`.

## Dependencies

- Python 3 with `requests`, `rich`, `cryptography`
- `ddgr` (DuckDuckGo search CLI)
- `lynx` (URL reading)
- `bubblewrap` (sandboxed `run` tool, optional)
- `coreutils`, `gnugrep` (system utilities)
