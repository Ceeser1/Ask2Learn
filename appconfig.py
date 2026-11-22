"""Everything about the app that can be adjusted without touching code.

    app.json     identity (folder and Windows names), file names, sounds, timings, learning
                 rules (spaced repetition, batch sizes) and the annoyance levels
    themes.json  colors and fonts of the window
    config.json  defaults for the user's settings (the user's own choices: settings.json)
    lang/*.json  every interface text, one file per language (see i18n.py)
    courses/     the courses, including their language rules (articles, letter equivalents)
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _load(name: str) -> dict:
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


APP = _load("app.json")
THEMES = _load("themes.json")

IDENTITY = APP["identity"]
FILES = APP["files"]
SOUNDS = APP["sounds"]
TIMING = APP["timing"]
LEARNING = APP["learning"]
ANNOY_LEVELS = APP["annoyance_levels"]   # in slider order, quiet to unbearable
