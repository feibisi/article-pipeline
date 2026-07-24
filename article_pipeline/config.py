"""Shared configuration loader.

Config lives at ~/.config/article-pipeline/config.yaml and holds endpoints
only. Credentials are read from the environment (never from this file) — see
REQUIRED_ENV / OPTIONAL_ENV below.
"""
import os
import sys
import yaml

_CONFIG_PATH = os.path.expanduser("~/.config/article-pipeline/config.yaml")

# Top-level sections the code actually reads. Anything else in the file is
# dead config: it looks configured but changes nothing.
KNOWN_SECTIONS = {
    "ollama", "deepseek", "wordpress", "pipeline",
    "cocobook", "pinchtab", "review", "mcp", "anyscale", "schedule",
}

# Keys present in the shipped config that nothing reads. Listed explicitly so
# `ap doctor` can warn instead of letting an operator think they took effect.
UNUSED_KEYS = {
    "pipeline.db_path": "TaskDB() hardcodes ~/docs/ai-context/article-pipeline-v1.db",
    "pipeline.max_parallel": "the pipeline is strictly sequential",
    "pipeline.research_note_max_words": "research.py does not read it",
    "cocobook.search_cmd": "research.py uses the MCP HTTP API instead",
    "cocobook.annotations_db": "research.py uses its own ANNOTATIONS_DB constant",
    "review.ai_patterns": "review/ ships its own pattern list",
    "review.min_paragraphs": "review/ uses hardcoded thresholds",
    "review.max_paragraphs": "review/ uses hardcoded thresholds",
    "anyscale": "no code path uses anyscale",
}

# Env vars whose absence breaks a stage. (Names only — never log values.)
REQUIRED_ENV = {
    "AP_DS_API_KEY": "writer/outline LLM calls (or DEEPSEEK_API_KEY)",
}
OPTIONAL_ENV = {
    "AP_WP_USERNAME": "publishing to WordPress",
    "AP_WP_APP_PASSWORD": "publishing to WordPress",
    "ANTHROPIC_API_KEY": "book-knowledge writer path",
    "AP_REVIEW_TOKEN": "POST auth on the review web UI",
}

_warned = False


def load_config() -> dict:
    """Load the YAML config. Returns {} if absent.

    A malformed config used to be swallowed silently, so every endpoint fell
    back to a hardcoded default and the operator had no idea why. Now a parse
    error is reported on stderr once per process.
    """
    global _warned
    try:
        with open(_CONFIG_PATH) as f:
            config = yaml.safe_load(f)
    except FileNotFoundError:
        return {}
    except (yaml.YAMLError, OSError) as e:
        if not _warned:
            _warned = True
            print(f"[config] WARNING: {_CONFIG_PATH} unusable, falling back to "
                  f"built-in defaults: {type(e).__name__}: {e}", file=sys.stderr)
        return {}
    if not isinstance(config, dict):
        if not _warned:
            _warned = True
            print(f"[config] WARNING: {_CONFIG_PATH} is not a mapping — ignored",
                  file=sys.stderr)
        return {}
    return config


def validate_config(config: dict | None = None) -> list[tuple[str, str]]:
    """Check config + credential environment. Returns [(level, message)].

    level is "error" (a stage will fail) or "warn" (works but misleading).
    Never returns or logs credential values — only variable names.
    """
    problems: list[tuple[str, str]] = []

    if not os.path.exists(_CONFIG_PATH):
        problems.append(("warn", f"no config at {_CONFIG_PATH}; all endpoints "
                                 f"use built-in defaults"))
        config = config if config is not None else {}
    else:
        if config is None:
            try:
                with open(_CONFIG_PATH) as f:
                    raw = yaml.safe_load(f)
            except (yaml.YAMLError, OSError) as e:
                problems.append(("error", f"config unparseable: "
                                          f"{type(e).__name__}: {e}"))
                raw = None
            config = raw if isinstance(raw, dict) else {}
            if raw is not None and not isinstance(raw, dict):
                problems.append(("error", "config root is not a mapping"))

    for section in config:
        if section not in KNOWN_SECTIONS:
            problems.append(("warn", f"unknown config section '{section}' — "
                                     f"nothing reads it"))

    for dotted, why in sorted(UNUSED_KEYS.items()):
        parts = dotted.split(".")
        node = config
        for p in parts:
            if not isinstance(node, dict) or p not in node:
                node = None
                break
            node = node[p]
        if node is not None:
            problems.append(("warn", f"'{dotted}' is set but ignored ({why})"))

    # Endpoint sanity: a URL typo silently degrades to "no results".
    for section, key in (("mcp", "base_url"), ("pinchtab", "base_url"),
                         ("ollama", "base_url"), ("deepseek", "base_url")):
        val = (config.get(section) or {}).get(key) if isinstance(
            config.get(section), dict) else None
        if val is not None and not str(val).startswith(("http://", "https://")):
            problems.append(("error", f"{section}.{key} is not an http(s) URL"))

    for var, why in REQUIRED_ENV.items():
        alt = {"AP_DS_API_KEY": "DEEPSEEK_API_KEY"}.get(var)
        if not os.environ.get(var) and not (alt and os.environ.get(alt)):
            problems.append(("error", f"env {var} not set — needed for {why}"))
    for var, why in OPTIONAL_ENV.items():
        if not os.environ.get(var):
            problems.append(("warn", f"env {var} not set — {why} unavailable"))

    return problems
