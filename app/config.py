import os
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

_ENV_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)\}")


@dataclass
class APIConfig:
    base_url: str
    api_key: str
    model: str


@dataclass
class OllamaConfig:
    base_url: str
    model: str
    api_key: str


@dataclass
class LLMConfig:
    mode: str
    api: APIConfig
    ollama: OllamaConfig
    polish_chunk_minutes: int
    temperature: float
    max_retries: int


@dataclass
class ASRConfig:
    cache_dir: str
    hub: str
    batch_size_s: int
    batch_size_threshold_s: int
    hotword: str
    idle_unload_minutes: int = 30


@dataclass
class ServerConfig:
    host: str
    port: int


@dataclass
class StorageConfig:
    data_dir: str = "./data"


@dataclass
class Config:
    asr: ASRConfig
    llm: LLMConfig
    server: ServerConfig
    storage: StorageConfig


def _expand_env(value):
    if isinstance(value, str):
        return _ENV_PATTERN.sub(lambda m: os.environ.get(m.group(1), ""), value)
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    return value


def load_config(path: str) -> Config:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"config not found: {path}")
    raw = yaml.safe_load(p.read_text())
    raw = _expand_env(raw)
    return Config(
        asr=ASRConfig(**raw["asr"]),
        llm=LLMConfig(
            mode=raw["llm"]["mode"],
            api=APIConfig(**raw["llm"]["api"]),
            ollama=OllamaConfig(**raw["llm"]["ollama"]),
            polish_chunk_minutes=raw["llm"]["polish_chunk_minutes"],
            temperature=raw["llm"]["temperature"],
            max_retries=raw["llm"]["max_retries"],
        ),
        server=ServerConfig(**raw["server"]),
        storage=StorageConfig(**(raw.get("storage") or {})),
    )
