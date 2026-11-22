"""Interface texts and language names, plus system language detection.

Every interface language is one file in lang/, e.g. lang/de.json:
    {"code": "de",
     "name": "Deutsch",                         the language's own name
     ("endonyms": {"pt": "Português", ...}      root file only: every language's own name)
     "languages": {"en": "Englisch", ...},       language names, written in this language
     "texts": {"nav.overview": "Übersicht", ...}} every interface text, by key
English (lang/en.json) is the root: it has every key, and a text missing in another file falls
back to it. A new interface language is a new file, no code changes. Texts can use other texts:
{@name.daily} inserts that key's text, {@name.daily:upper} the same in capitals.
`main.py --check-texts` lists every gap.
"""

import ctypes
import json
import locale
import re
from pathlib import Path

FALLBACK = "en"   # the root language
LANG_DIR = Path(__file__).resolve().parent / "lang"


def _load_files() -> dict:
    files = {}
    for path in sorted(LANG_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        files[data.get("code") or path.stem] = data
    return files


_FILES = _load_files()
UI_LANGUAGES = tuple(sorted(_FILES, key=lambda c: (c != FALLBACK, c)))   # root first
STRINGS = {}                                                             # key -> {language: text}
for _code, _data in _FILES.items():
    for _key, _text in _data.get("texts", {}).items():
        STRINGS.setdefault(_key, {})[_code] = _text
LANGUAGE_NAMES = {code: data.get("languages", {}) for code, data in _FILES.items()}
# Every language's own name ("Português"): the root file lists them, a language's own file wins.
ENDONYMS = {**_FILES.get(FALLBACK, {}).get("endonyms", {}),
            **{code: data["name"] for code, data in _FILES.items() if data.get("name")}}
_current = FALLBACK


def missing_translations() -> list:
    """Gaps in the language files, compared to the root file (English): [(what, language)].
    Every file needs its own name, every key the root has, and a name for every language the root
    names; a key the root doesn't have is a typo. Texts may only refer to keys that exist."""
    root = _FILES.get(FALLBACK, {})
    root_keys, root_names = set(root.get("texts", {})), set(root.get("languages", {}))
    out = []
    for code, data in _FILES.items():
        texts, names = data.get("texts", {}), data.get("languages", {})
        if not data.get("name"):
            out.append(("name", code))
        out += [(key, code) for key in sorted(root_keys) if not texts.get(key)]
        out += [(t("cli.unknown_key", key=key, file=f"{FALLBACK}.json"), code) for key in sorted(set(texts) - root_keys)]
        out += [(f"languages.{n}", code) for n in sorted(root_names) if not names.get(n)]
        out += [(t("cli.bad_ref", key=key, ref=m.group(1)), code)
                for key, text in texts.items() for m in _REF.finditer(text) if m.group(1) not in STRINGS]
    return out


def set_language(code: str) -> None:
    global _current
    _current = code if code in UI_LANGUAGES else FALLBACK


def language() -> str:
    return _current


# A text can use another key's text: {@name.daily} inserts the feature's name, {@name.daily:upper}
# the same in capitals. Names (features, levels, the app) are translated once, under their own key.
_REF = re.compile(r"\{@([\w.]+)(?::(upper))?\}")


def _resolve(text: str) -> str:
    return _REF.sub(lambda m: t(m.group(1)).upper() if m.group(2) else t(m.group(1)), text)


def t(key: str, /, **kw) -> str:   # key is positional-only, so a text may use {key} itself
    entry = STRINGS.get(key)
    if entry is None:
        return key
    text = _resolve(entry.get(_current) or entry.get(FALLBACK) or key)
    return text.format(**kw) if kw else text


def tl(key: str) -> list:
    """A comma-separated list entry (weekdays, months)."""
    return t(key).split(",")


def quote(s: str) -> str:
    return t("quote", s=s)


def loc(value, lang: str | None = None):
    """Pick the current language from a {"de": …, "en": …} dict; plain values pass through."""
    if isinstance(value, dict):
        lang = lang or _current
        return value.get(lang) or value.get(FALLBACK) or next(iter(value.values()), "")
    return value


def language_name(code: str) -> str:
    """A language's name in the app language ("Portugiesisch")."""
    return (LANGUAGE_NAMES.get(_current, {}).get(code) or LANGUAGE_NAMES.get(FALLBACK, {}).get(code)
            or ENDONYMS.get(code, code))


def cefr(code: str) -> str:
    """A course level code ("A1") as shown in the app language."""
    key = f"level.cefr.{code}"
    return t(key) if key in STRINGS else code


def sep(*parts) -> str:
    """Parts joined with the separator of the app language (" · ")."""
    return t("fmt.sep").join(str(p) for p in parts if p not in (None, ""))


def endonym(code: str) -> str:
    """A language's own name ("Deutsch"), from its language file; otherwise its name in English."""
    return ENDONYMS.get(code) or LANGUAGE_NAMES.get(FALLBACK, {}).get(code) or code


def system_language() -> str:
    """Two-letter code of the user's language, e.g. "de".

    The regional format (date/number settings) wins over the display language: plenty of people
    run an English Windows but have their own language as the format, which says more about them."""
    codes = []
    try:
        k32 = ctypes.windll.kernel32
        for langid in (k32.GetUserDefaultLangID(), k32.GetUserDefaultUILanguage()):
            name = locale.windows_locale.get(langid, "")
            if name:
                codes.append(name.split("_")[0].lower())
    except (AttributeError, OSError):
        pass
    codes.append((locale.getlocale()[0] or FALLBACK).split("_")[0][:2].lower())
    return next((c for c in codes if c in UI_LANGUAGES), codes[0])
