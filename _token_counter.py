"""
token_counter.py — Accurate DeepSeek V3 token counting using official tokenizer.
Falls back to heuristic estimation if tokenizer files are missing or transformers not installed.
"""
import re
from pathlib import Path

_TOKENIZER_DIR = Path(__file__).parent / "tokenizer"
_tokenizer = None


def _load_tokenizer():
    """Lazy-load the DeepSeek tokenizer (first call only)."""
    global _tokenizer
    if _tokenizer is not None:
        return _tokenizer
    if not (_TOKENIZER_DIR / "tokenizer.json").exists():
        return None
    try:
        import transformers
        _tokenizer = transformers.AutoTokenizer.from_pretrained(
            str(_TOKENIZER_DIR), trust_remote_code=True
        )
        return _tokenizer
    except Exception:
        return None


def _heuristic(text: str) -> int:
    """Fallback: rough estimation. Chinese ~1.5 chars/token, English ~4 chars/token."""
    if not text:
        return 0
    cn = len(re.findall(r"[一-鿿　-〿＀-￯]", text))
    other = len(text) - cn
    return max(1, int(cn / 1.5 + other / 4))


def count(text: str) -> int:
    """Count tokens in text using DeepSeek tokenizer. Falls back to heuristic."""
    if not text:
        return 0
    tok = _load_tokenizer()
    if tok is not None:
        try:
            return len(tok.encode(text))
        except Exception:
            pass
    return _heuristic(text)


def has_tokenizer() -> bool:
    """Check if the accurate tokenizer is available."""
    return _load_tokenizer() is not None
