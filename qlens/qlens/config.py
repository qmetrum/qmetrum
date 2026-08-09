import os

# Gemini flash by default — cheap, fast, good enough for cited reasoning.
DEFAULT_MODEL = os.getenv("QLENS_MODEL", "gemini-2.5-flash")


def get_api_key() -> str | None:
    return os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
