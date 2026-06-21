import os

from app.config import load_config


def test_load_config_basic(tmp_path):
    yaml_text = """
asr:
  cache_dir: "./models"
  hub: "ms"
  batch_size_s: 300
  batch_size_threshold_s: 60
  hotword: ""
llm:
  mode: api
  api:
    base_url: "http://x/v1"
    api_key: "${MY_KEY}"
    model: "gpt-x"
  ollama:
    base_url: "http://localhost:11434/v1"
    model: "qwen2.5:7b"
    api_key: "ollama"
  polish_chunk_minutes: 6
  temperature: 0.3
  max_retries: 2
server:
  host: "127.0.0.1"
  port: 8000
"""
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml_text)
    os.environ["MY_KEY"] = "secret123"
    cfg = load_config(str(cfg_path))
    assert cfg.asr.cache_dir == "./models"
    assert cfg.llm.mode == "api"
    assert cfg.llm.api.api_key == "secret123"
    assert cfg.llm.polish_chunk_minutes == 6
    assert cfg.server.port == 8000


def test_load_config_missing_file():
    import pytest
    with pytest.raises(FileNotFoundError):
        load_config("/nonexistent/path/config.yaml")
