"""Pluggable model clients. The pipeline only needs `complete(system, user, max_tokens) -> str`.

* AnthropicClient: the real thing. Needs the `anthropic` package and ANTHROPIC_API_KEY; imported lazily, key never printed.
* OracleStub / WrongStub / KeywordStub: deterministic offline stand-ins used to test the evaluation harness itself.
  They are NOT language models and their scores must never be reported as model results.
"""
import os
import re
from pathlib import Path

from nycdistress.env import load_dotenv

DEFAULT_MODEL = "claude-sonnet-5-5"
ROOT = Path(__file__).resolve().parents[3]


def live_key_present():
    """True when a non-empty ANTHROPIC_API_KEY exists in the environment or in <root>/.env. Never returns or prints the key."""
    load_dotenv(ROOT / ".env")
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


class AnthropicClient:
    name = "anthropic"

    def __init__(self, model=None, api_key=None):
        load_dotenv(ROOT / ".env")
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set (environment or .env)")
        try:
            import anthropic
        except ImportError as e:  # pragma: no cover - depends on the environment
            raise RuntimeError("install the optional dependency: uv pip install anthropic") from e
        self._client = anthropic.Anthropic(api_key=key)
        self.model = model or os.environ.get("NYC_LLM_MODEL", DEFAULT_MODEL)
        self.name = f"anthropic:{self.model}"

    def complete(self, system, user, max_tokens=1024):
        msg = self._client.messages.create(model=self.model, max_tokens=max_tokens, system=system, messages=[{"role": "user", "content": user}])
        return "".join(getattr(b, "text", "") for b in msg.content)


class OracleStub:
    """Returns the reference SQL of the gold question it is asked (harness check: must score 100%)."""
    name = "stub-oracle"

    def __init__(self, gold):
        self.by_question = {g["question"]: g["sql"] for g in gold}

    def complete(self, system, user, max_tokens=1024):
        m = re.search(r"Question:\s*(.+?)\s*(?:\n|$)", user)
        return "```sql\n" + self.by_question.get(m.group(1).strip() if m else "", "SELECT 1") + "\n```"


class WrongStub:
    """Always answers SELECT 1 (harness check: must score about 0%)."""
    name = "stub-wrong"

    def complete(self, system, user, max_tokens=1024):
        return "SELECT 1"


class KeywordStub:
    """A crude keyword baseline with a handful of generic patterns, not tuned to the gold questions. Not a language model."""
    name = "stub-keyword"

    def complete(self, system, user, max_tokens=1024):
        m = re.search(r"Question:\s*(.+?)\s*(?:\n|$)", user)
        q = (m.group(1) if m else "").lower()
        if re.search(r"how many buildings (are|do we have|were)? ?(there )?(in the analysis|in total|are there)?\??$", q) and "each" not in q and "borough" not in q:
            return "SELECT count(*) FROM buildings"
        if "how many" in q and "violations" in q and "class c" not in q and not re.search(r"\b20\d\d\b", q):
            return "SELECT count(*) FROM hpd_violations"
        return "SELECT 1"
