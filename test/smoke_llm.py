"""手工冒烟：读取 raw.json，跑 polish + summarize，打印结果。

用法：
    LLM_API_KEY=xxx uv run python test/smoke_llm.py data/smoke_raw.json
"""
import json
import sys
from pathlib import Path

from app.config import load_config
from app.llm import polish, summarize


def main():
    if len(sys.argv) < 2:
        print("usage: python test/smoke_llm.py <raw.json>")
        sys.exit(1)
    raw = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    cfg = load_config("config.yaml")
    print("polishing...")
    processed = polish(raw["sentences"], cfg.llm)
    Path("data/smoke_processed.md").write_text(processed, encoding="utf-8")
    print(f"  -> {len(processed)} chars, saved data/smoke_processed.md")
    print("summarizing...")
    summary = summarize(processed, cfg.llm)
    if isinstance(summary, dict):
        from app.llm import summary_to_md
        summary = summary_to_md(summary)
        print("  -> dict (4 段), rendered to markdown")
    Path("data/smoke_summary.md").write_text(summary, encoding="utf-8")
    print(f"  -> {len(summary)} chars, saved data/smoke_summary.md")
    print("\n=== summary ===")
    print(summary)


if __name__ == "__main__":
    main()
