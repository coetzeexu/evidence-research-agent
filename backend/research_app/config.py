import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    model: str
    api_key: str
    base_url: str
    host: str = "127.0.0.1"
    port: int = 8000
    platform: str = ""
    vllm_thinking: bool | None = None

    @property
    def model_ready(self) -> bool:
        return bool(self.model and self.api_key)


def settings() -> Settings:
    thinking = os.getenv("LLM_VLLM_THINKING", "").strip().lower()
    if thinking not in {"", "true", "false"}:
        raise ValueError("LLM_VLLM_THINKING 必须为空、true 或 false")
    data = Path(os.getenv("RESEARCH_DATA_DIR", str(PROJECT_ROOT / ".research-data")))
    if not data.is_absolute():
        data = PROJECT_ROOT / data
    return Settings(
        data_dir=data,
        model=os.getenv("LLM_MODEL", ""),
        api_key=os.getenv("LLM_API_KEY", os.getenv("OPENAI_API_KEY", "")),
        base_url=os.getenv("LLM_BASE_URL", "https://api.openai.com/v1"),
        host=os.getenv("RESEARCH_HOST", "127.0.0.1"),
        port=int(os.getenv("RESEARCH_PORT", "8000")),
        platform=os.getenv("LLM_PLATFORM", ""),
        vllm_thinking=None if not thinking else thinking == "true",
    )
