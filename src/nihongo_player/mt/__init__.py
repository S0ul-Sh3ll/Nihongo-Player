"""Machine translation package (offline Opus-MT / CTranslate2)."""

from nihongo_player.mt.translator import NLLBTranslator, Translator, resolve_model_dir

__all__ = ["Translator", "NLLBTranslator", "resolve_model_dir"]
