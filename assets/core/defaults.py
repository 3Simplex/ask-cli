"""Single source of truth for global config defaults.

Every global config key the harness reads gets its fallback here. Call sites
must not hardcode their own fallback literals for these keys.

Per-provider dicts (a provider's own api_base/api_key/models_dir) and
per-evaluator override dicts are NOT governed here: those carry
backend-specific defaults that must not be collapsed onto the global values.

Values are the OOBE-stamped ones, so any config created by oobe already holds
them and sees no behavior change.
"""

DEFAULTS = {
    "timeout": 120000,
    "max_turns": 100,
    "max_result_chars": 10000,
    "search_rate_limit": 5,
    "search_rate_delay": 5.0,
    "search_max_concurrent": 1,
    "search_retry_count": 3,
    "search_retry_base_delay": 10.0,
    "search_timeout": 30,
    "auto_approve_default": False,
    "use_sandbox_default": False,
    "api_key": "",
    "api_base": "http://localhost:9931/v1",
    "active_provider": "",
    "default_evaluator": "security_watcher",
    "webhook_url": "",
}

# Deliberately absent: "providers" is a container, not a scalar default.
# Returning a shared mutable from get() would let one caller poison the module.


def get(config, key, override=None):
    """Return config[key], falling back to DEFAULTS[key] (or `override`)."""
    if key in config:
        return config[key]
    if override is not None:
        return override
    return DEFAULTS[key]
