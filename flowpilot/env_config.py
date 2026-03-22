"""Environment-based configuration for dev/staging/prod deployments."""

import json
import os
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional


@dataclass
class EnvironmentConfig:
    """Configuration that varies per deployment environment."""
    name: str = "development"
    debug: bool = False
    host: str = "127.0.0.1"
    port: int = 7860
    webhook_port: int = 8000
    database_url: str = "sqlite:///flowpilot.db"
    auth_enabled: bool = False
    session_ttl_hours: int = 24
    admin_password: str = "admin"
    default_threads: int = 4
    max_retries: int = 3
    retry_delay: float = 1.0
    execution_timeout: int = 300
    rate_limiting_enabled: bool = True
    log_level: str = "INFO"
    log_file: Optional[str] = None
    connector_timeout: int = 30
    secrets_db_path: str = "flowpilot_secrets.db"
    secret_key: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    def save(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load(cls, path: str) -> "EnvironmentConfig":
        with open(path) as f:
            data = json.load(f)
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


ENVIRONMENTS = {
    "development": EnvironmentConfig(
        name="development", debug=True, auth_enabled=False, log_level="DEBUG",
    ),
    "staging": EnvironmentConfig(
        name="staging", debug=False, auth_enabled=True, log_level="INFO", host="0.0.0.0",
    ),
    "production": EnvironmentConfig(
        name="production", debug=False, auth_enabled=True, log_level="WARNING",
        host="0.0.0.0", session_ttl_hours=8, max_retries=5,
    ),
}


def get_config(env_name: Optional[str] = None) -> EnvironmentConfig:
    """Get configuration. Priority: arg > FLOWPILOT_ENV > config file > development."""
    env_name = env_name or os.environ.get("FLOWPILOT_ENV", "development")
    config_path = os.environ.get("FLOWPILOT_CONFIG", f"config/{env_name}.json")

    if Path(config_path).exists():
        config = EnvironmentConfig.load(config_path)
    elif env_name in ENVIRONMENTS:
        config = ENVIRONMENTS[env_name]
    else:
        config = EnvironmentConfig(name=env_name)

    for field_name, field_obj in EnvironmentConfig.__dataclass_fields__.items():
        env_key = f"FLOWPILOT_{field_name.upper()}"
        env_val = os.environ.get(env_key)
        if env_val is not None:
            ftype = field_obj.type
            if ftype == "bool":
                setattr(config, field_name, env_val.lower() in ("true", "1", "yes"))
            elif ftype == "int":
                setattr(config, field_name, int(env_val))
            elif ftype == "float":
                setattr(config, field_name, float(env_val))
            else:
                setattr(config, field_name, env_val)

    return config


def init_environment(env_name: str = "development") -> str:
    """Create a config file for the given environment."""
    config = ENVIRONMENTS.get(env_name, EnvironmentConfig(name=env_name))
    path = f"config/{env_name}.json"
    config.save(path)
    return path
