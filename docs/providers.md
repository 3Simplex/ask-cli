---
when_to_read: "Configuring an API backend, using -ap subcommands, presets, or understanding the FreeToken two-plane model."
related: ["config.md", "tools.md"]
---
# API Providers & Routers

Backend selection, the `-ap` subcommand surface, presets/hot-reload, and per-backend config keys.

> FreeToken uses a **two-plane model**: a control plane (`:1900`) owns engine
> lifecycle, while chat/inference goes **directly** to the serve (`:8000`). This
> distinction is the primary thing this file will document.
>
> Content migrates from `developer-guide.md` §"Configuration" (provider parts) plus
> the currently-undocumented `-ap` surface and preset system.
