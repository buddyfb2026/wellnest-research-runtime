import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = REPO_ROOT / "work" / "research.sqlite"
DEFAULT_ALLOWLIST = REPO_ROOT / "sources" / "allowlist.json"
DEFAULT_REPORT = REPO_ROOT / "work" / "report.md"

USER_AGENT = "WellNestResearch/0.1 (+bounded household research; contact spencer@bizina.ai)"

# Hard demonstration caps (WEL-40/41). CLI may lower them, never raise them.
MAX_URLS_HARD_CAP = 10
MAX_INFERENCE_HARD_CAP = 10            # per run (process)
MAX_INFERENCE_PER_DAY_HARD_CAP = 10    # per UTC day, persisted across runs, restarts and overlaps
MAX_DISCOVERY_ASSESSMENTS_PER_CYCLE = 3
MAX_DISCOVERY_HINTS_PER_ROUTE = 20


@dataclass
class Config:
    db_path: Path = DEFAULT_DB
    allowlist_path: Path = DEFAULT_ALLOWLIST
    report_path: Path = DEFAULT_REPORT
    max_urls: int = MAX_URLS_HARD_CAP
    max_inference: int = MAX_INFERENCE_HARD_CAP
    max_inference_per_day: int = MAX_INFERENCE_PER_DAY_HARD_CAP
    provider: str = "none"            # none | ollama | fixture
    ollama_model: str = "qwen2.5:14b"
    ollama_url: str = "http://127.0.0.1:11434"
    fetch_timeout_s: int = 20
    max_body_bytes: int = 2_000_000
    user_agent: str = USER_AGENT

    @classmethod
    def from_env(cls, **overrides) -> "Config":
        cfg = cls()
        if os.environ.get("WN_RESEARCH_DB"):
            cfg.db_path = Path(os.environ["WN_RESEARCH_DB"])
        if os.environ.get("WN_RESEARCH_MODEL_PROVIDER"):
            cfg.provider = os.environ["WN_RESEARCH_MODEL_PROVIDER"]
        if os.environ.get("WN_RESEARCH_OLLAMA_MODEL"):
            cfg.ollama_model = os.environ["WN_RESEARCH_OLLAMA_MODEL"]
        if os.environ.get("WN_RESEARCH_OLLAMA_URL"):
            cfg.ollama_url = os.environ["WN_RESEARCH_OLLAMA_URL"]
        for k, v in overrides.items():
            if v is not None:
                setattr(cfg, k, v)
        cfg.max_urls = min(int(cfg.max_urls), MAX_URLS_HARD_CAP)
        cfg.max_inference = min(int(cfg.max_inference), MAX_INFERENCE_HARD_CAP)
        cfg.max_inference_per_day = min(int(cfg.max_inference_per_day), MAX_INFERENCE_PER_DAY_HARD_CAP)
        return cfg
