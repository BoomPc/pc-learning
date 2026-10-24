"""Display-name aliases only; never normalize quoted mathematics or coordinates."""
import re
import unicodedata

NAME=r"[A-Z](?:[0-9₀₁₂₃₄₅₆₇₈₉′'″])*"
_WIDTH={c:c-0xFEE0 for c in range(0xFF01,0xFF5F)}
_SUBSCRIPTS=str.maketrans('₀₁₂₃₄₅₆₇₈₉','0123456789')


def normalize(value):
    # NFKC would turn powers into digits, incorrectly equating A² with A2.
    return re.sub(r'\s+','',unicodedata.normalize('NFC',value).translate(_WIDTH).translate(_SUBSCRIPTS)).replace("'",'′').replace('″','′′')
