"""Shared configuration loader."""
import os
import yaml

_CONFIG_PATH = os.path.expanduser("~/.config/article-pipeline/config.yaml")


def load_config() -> dict:
    try:
        with open(_CONFIG_PATH) as f:
            config = yaml.safe_load(f)
            return config if isinstance(config, dict) else {}
    except (FileNotFoundError, yaml.YAMLError):
        return {}
