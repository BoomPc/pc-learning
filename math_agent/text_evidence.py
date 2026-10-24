"""Typography-only comparison for verbatim evidence; retain original text for audit."""
import re

# Fullwidth ASCII has the same textual symbols. Do not use NFKC: it changes x² into x2.
_WIDTH = {code: code-0xFEE0 for code in range(0xFF01, 0xFF5F)}

def normalized_quote(text):
    text=''.join(text.translate(_WIDTH).split())
    # Named-line parallel notation in school geometry: serialization aliases only.
    # Preserve the point names, primes, numbers and order. Never normalize general
    # division, inequalities, negative signs, powers or unknown symbols.
    point=r"[A-Z](?:[′']|[0-9])*"
    line=point+point
    text=re.sub(r'('+line+r')(?:\\parallel|//|‖)('+line+r')',r'\1∥\2',text)
    # A full stop directly before Chinese prose is punctuation, not a decimal.
    return re.sub(r'\.(?=[\u4e00-\u9fff])', '。', text)


def quote_in_text(quote, text):
    """Exact evidence must survive normalization at a substring boundary.

    A quoted final full stop lacks the following Chinese character that the
    full source contains. Check exact raw inclusion first; typography fallback
    retains all existing mathematical-symbol restrictions.
    """
    return bool(normalized_quote(quote)) and (quote in text or normalized_quote(quote) in normalized_quote(text))
