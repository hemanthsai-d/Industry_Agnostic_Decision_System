from __future__ import annotations

import re

_URL_RE = re.compile(r'https?://\S+|www\.\S+', re.IGNORECASE)
_HANDLE_RE = re.compile(r'@\w+')
_HASHTAG_RE = re.compile(r'#(\w+)')
_APOSTROPHE_RE = re.compile("['\\u2018\\u2019\\u201C\\u201D`]")
_TOKEN_RE = re.compile(r"[a-z0-9']+")
_EMOJI_RE = re.compile(
    '[\\U0001F600-\\U0001F64F\\U0001F300-\\U0001F5FF\\U0001F680-\\U0001F6FF'
    '\\U0001F1E0-\\U0001F1FF\\U00002702-\\U000027B0\\U0001F900-\\U0001F9FF'
    '\\U0001FA00-\\U0001FA6F\\U0001FA70-\\U0001FAFF\\U00002600-\\U000026FF]+',
    re.UNICODE,
)
_REPEATED_CHARS_RE = re.compile(r'(.)\1{3,}')
_MASK_PLACEHOLDERS_RE = re.compile(r'__[a-z_]+__', re.IGNORECASE)

_COLLOQUIAL_MAP: dict[str, str] = {
    'u': 'you',
    'ur': 'your',
    'r': 'are',
    'pls': 'please',
    'plz': 'please',
    'thx': 'thanks',
    'thanx': 'thanks',
    'ty': 'thank you',
    'bc': 'because',
    'rn': 'right now',
    'asap': 'as soon as possible',
    'dm': 'direct message',
    'msg': 'message',
    'acct': 'account',
    'pw': 'password',
    'pwd': 'password',
    'info': 'information',
    'cust': 'customer',
    'svc': 'service',
    'mgr': 'manager',
    'dept': 'department',
    'amt': 'amount',
    'qty': 'quantity',
    'dlvry': 'delivery',
    'addr': 'address',
    'smth': 'something',
    'smthing': 'something',
}


def normalize_support_text(value: str) -> str:
    """Normalize support text from social media, chat, and formal channels."""
    text = value or ''
    text = _URL_RE.sub(' ', text)
    text = _HANDLE_RE.sub(' ', text)
    text = _HASHTAG_RE.sub(r' \1 ', text)
    text = _EMOJI_RE.sub(' ', text)
    text = _MASK_PLACEHOLDERS_RE.sub(' ', text)
    text = _APOSTROPHE_RE.sub("'", text.lower())
    text = text.replace('&amp;', ' and ')
    text = _REPEATED_CHARS_RE.sub(r'\1\1', text)
    text = re.sub(r"[^a-z0-9'\s]", ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def expand_colloquial(value: str) -> str:
    """Expand common SMS/social abbreviations in text."""
    tokens = value.split()
    expanded = []
    for token in tokens:
        lower = token.lower().strip("'\".,!?")
        if lower in _COLLOQUIAL_MAP:
            expanded.append(_COLLOQUIAL_MAP[lower])
        else:
            expanded.append(token)
    return ' '.join(expanded)


def tokenize_support_text(value: str) -> list[str]:
    normalized = normalize_support_text(value)
    return _TOKEN_RE.findall(normalized)


def unique_terms(value: str) -> set[str]:
    return set(tokenize_support_text(value))
