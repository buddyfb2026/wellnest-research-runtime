import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = REPO_ROOT / "work" / "research.sqlite"
DEFAULT_ALLOWLIST = REPO_ROOT / "sources" / "allowlist.json"
DEFAULT_REPORT = REPO_ROOT / "work" / "report.md"

USER_AGENT = "WellNestResearch/0.1 (+bounded household research; contact spencer@bizina.ai)"

# Hard demonstration caps (WEL-40/41). CLI may lower them, never raise them.
MAX_URLS_HARD_CAP = 10
MAX_INFERENCE_HARD_CAP = 10            # per run (process)
MAX_INFERENCE_PER_DAY_HARD_CAP = 10    # per UTC day, persisted across runs, restarts and overlaps
# WEL-54: an operator may opt in to a larger per-UTC-day allowance for the LOCAL Ollama provider
# only, or explicitly disable the daily quota for local development. Neither mode changes the
# per-run/page caps or accounting, and neither is read from a source-controlled file.
LOCAL_DAILY_BUDGET_CEILING = 100
MAX_DISCOVERY_ASSESSMENTS_PER_CYCLE = 3
MAX_DISCOVERY_HINTS_PER_ROUTE = 20


@dataclass
class Config:
    db_path: Path = DEFAULT_DB
    allowlist_path: Path = DEFAULT_ALLOWLIST
    report_path: Path = DEFAULT_REPORT
    max_urls: int = MAX_URLS_HARD_CAP
    max_inference: int = MAX_INFERENCE_HARD_CAP
    max_inference_per_day: Optional[int] = MAX_INFERENCE_PER_DAY_HARD_CAP
    provider: str = "none"            # none | ollama | fixture
    ollama_model: str = "qwen2.5:14b"
    ollama_url: str = "http://127.0.0.1:11434"
    fetch_timeout_s: int = 20
    max_body_bytes: int = 2_000_000
    user_agent: str = USER_AGENT
    recipe_extraction_enabled: bool = False
    local_daily_budget: Optional[Union[int, str]] = None  # None keeps default; 'unlimited' disables daily quota
    meals_first: bool = False                  # WEL-54 opt-in; recipe work before generic proposals

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
        if os.environ.get("WN_RESEARCH_RECIPE_EXTRACTION"):
            cfg.recipe_extraction_enabled = _flag(os.environ["WN_RESEARCH_RECIPE_EXTRACTION"])
        if os.environ.get("WN_RESEARCH_MEALS_FIRST"):
            cfg.meals_first = _flag(os.environ["WN_RESEARCH_MEALS_FIRST"])
        # The WEL-54 local daily budget is a run/cycle CLI/override control only, never an
        # environment setting, so auxiliary commands (report/review/reset-source) are unaffected.
        daily_override = overrides.get("max_inference_per_day") is not None
        for k, v in overrides.items():
            if v is not None:
                setattr(cfg, k, v)
        if cfg.local_daily_budget is not None:
            # Opt-in profile: explicitly requested limits must be positive whole numbers.
            # Legacy (no opt-in) handling of these flags is unchanged.
            for name in ("max_urls", "max_inference", "max_inference_per_day"):
                if overrides.get(name) is not None:
                    setattr(cfg, name, _whole_number(overrides[name], name))
        cfg.max_urls = min(int(cfg.max_urls), MAX_URLS_HARD_CAP)
        cfg.max_inference = min(int(cfg.max_inference), MAX_INFERENCE_HARD_CAP)
        if cfg.local_daily_budget is None:
            cfg.max_inference_per_day = min(int(cfg.max_inference_per_day), MAX_INFERENCE_PER_DAY_HARD_CAP)
        else:
            budget = validate_local_daily_budget(cfg.local_daily_budget, cfg.provider)
            cfg.local_daily_budget = budget
            # An explicit per-day flag still imposes its requested finite bound, even when
            # development opts out of the daily quota. None means no daily ceiling, not no ledger.
            if budget == "unlimited":
                cfg.max_inference_per_day = int(cfg.max_inference_per_day) if daily_override else None
            else:
                cfg.max_inference_per_day = (min(int(cfg.max_inference_per_day), budget)
                                             if daily_override else budget)
        return cfg


def _flag(value: str) -> bool:
    return value.strip().lower() in ("1", "true", "yes", "on")


def _whole_number(value, name: str) -> int:
    """A positive whole number (int, or ASCII digits as text). Anything else is refused."""
    if isinstance(value, str):
        text = value.strip()
        if not text.isascii() or not text.isdigit():
            raise ValueError("%s must be a positive whole number: %r" % (name, value))
        value = int(text)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("%s must be a positive whole number: %r" % (name, value))
    return value


def validate_local_daily_budget(value, provider: str) -> Union[int, str]:
    """An explicit 'unlimited' or whole number in [1, ceiling], Ollama only."""
    if provider != "ollama":
        raise ValueError("local daily budget applies only to provider=ollama (got %s)" % provider)
    if isinstance(value, str) and value.strip().lower() == "unlimited":
        return "unlimited"
    value = _whole_number(value, "local daily budget")
    if value > LOCAL_DAILY_BUDGET_CEILING:
        raise ValueError("local daily budget must be between 1 and %d: %d" % (LOCAL_DAILY_BUDGET_CEILING, value))
    return value
