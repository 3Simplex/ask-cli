# Docs Index

Routing table for `ask-cli` documentation. **Read the one file that matches your
task — do not read all of them.** Entry point for coding agents is root `AGENTS.md`.

Tables inside `<!-- BEGIN GENERATED ... -->` markers are derived from source by
`python3 generate_docs.py`; refresh them with that command (check drift with `--check`).


| Task / question | Read |
| --- | --- |
| Define an agent profile (`assets/agents/*.json`) | `docs/agents.md` |
| States, transitions, transition-gating evaluators | `docs/states.md` |
| Add/modify a tool (`@ask_tool`, auto-discovery) | `docs/tools.md` |
| Context providers, refresh modes, `{template}` syntax | `docs/context-providers.md` |
| Evaluators and post-evaluation hooks | `docs/evaluators.md` |
| API backends, `-ap` surface, presets, two-plane model | `docs/providers.md` |
| Session persistence and `-c` resume | `docs/sessions.md` |
| `config.json` keys and defaults | `docs/config.md` |
| Nix build / install / packaging | `docs/nix.md` |
