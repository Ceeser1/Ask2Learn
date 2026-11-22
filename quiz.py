"""Course, lessons, exercises, answer checking and progress (Leitner boxes with due dates)."""

import datetime as dt
import json
import os
import random
import re
import threading
import time
import unicodedata
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import i18n
from appconfig import FILES, LEARNING
from i18n import loc, quote, t

# The learning rules live in app.json ("learning"), so they can be tuned without touching code.
MAX_BOX = LEARNING["max_box"]
MASTERED_BOX = LEARNING["mastered_box"]
# Lower box = weaker word = asked more often by the notification quiz.
BOX_WEIGHT = dict(enumerate(LEARNING["box_weight"]))
# Hours until a word is due for review after reaching a box (a bit under whole days,
# so practising at roughly the same time every day works).
INTERVAL_HOURS = dict(enumerate(LEARNING["review_hours"]))
RECENT_MEMORY = LEARNING["recent_memory"]
HISTORY_DAYS = LEARNING["history_days"]
DAILY_SIZE = LEARNING["daily_size"]

# Language rules of the active course (its course file: "articles", "equivalents"). Typed vocabulary
# may leave out a leading article; "equivalents" are letters that count as the same when typing
# loosely (e.g. {"ß": "ss"}). Set by Trainer when a course loads.
ARTICLES: set = set()
EQUIVALENTS: dict = {}


def level_name(level: int) -> str:
    return t(f"level.{level}")


def level_of(p: dict | None) -> int:
    """0 = new, 1 = learning, 2 = familiar, 3 = mastered."""
    if p is None:
        return 0
    if p["box"] >= MASTERED_BOX:
        return 3
    if p["box"] >= 2:
        return 2
    return 1


def _due(p: dict) -> float:
    return p.get("due", p["last"] + INTERVAL_HOURS[p["box"]] * 3600)


# ---------- typed answers ----------
def _normalize(s: str, keep_accents: bool) -> str:
    s = re.sub(r"\(.*?\)", " ", s.lower())
    if not keep_accents:
        s = unicodedata.normalize("NFKD", s)
        s = "".join(c for c in s if not unicodedata.combining(c))
        for letter, same in EQUIVALENTS.items():
            s = s.replace(letter, same)
    s = re.sub(r"[^\w\s]", " ", s)
    return " ".join(s.split())


def _variants(expected: str, keep_accents: bool, drop_articles: bool) -> set:
    out = set()
    for part in [expected, *expected.split("/")]:
        n = _normalize(part, keep_accents)
        if not n:
            continue
        out.add(n)
        words = n.split()
        if drop_articles and len(words) > 1 and words[0] in ARTICLES:
            out.add(" ".join(words[1:]))  # article is optional for vocabulary
    return out


def _distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def check_typed(answer: str, expected: str, strict: bool = False) -> str:
    """'exact', 'accent' (only the accents are wrong), 'close' (a small typo; never for strict
    answers) or 'wrong'. The caller decides whether 'accent' and 'close' count as right."""
    if _normalize(answer, True) in _variants(expected, True, not strict):
        return "exact"
    loose = _normalize(answer, False)
    if not loose:
        return "wrong"
    loose_variants = _variants(expected, False, not strict)
    if loose in loose_variants:
        return "accent"
    if strict:
        return "wrong"
    for v in loose_variants:
        allowed = 2 if len(v) >= 14 else 1 if len(v) >= 5 else 0
        if allowed and _distance(loose, v) <= allowed:
            return "close"
    return "wrong"


def _without_hints(s: str) -> str:
    return " ".join(re.sub(r"\([^)]*\)", " ", s).split())


# ---------- course data ----------
@dataclass
class Question:
    """A multiple-choice question for the notification quiz."""
    id: str
    word: str          # foreign word (progress key)
    translation: str
    reverse: bool      # True = German shown, pick the foreign word
    prompt: str
    options: list
    correct: int

    @property
    def correct_text(self) -> str:
        return self.options[self.correct]


@dataclass(eq=False)
class Unit:
    id: str
    number: int
    title: str
    subtitle: str
    lessons: list = field(default_factory=list)


@dataclass(eq=False)
class Section:
    """A sub-lesson. Every lesson has at least one; a lesson without "sections" in the
    course file is a single untitled section. Long lessons (hard languages) can have many."""
    number: int
    title: str
    words: list = field(default_factory=list)        # entries, as in Lesson.words
    explanation: list = field(default_factory=list)  # this section's blocks
    exercises: list = field(default_factory=list)    # indices into Lesson.exercises

    @property
    def key(self) -> str:
        return str(self.number)


@dataclass(eq=False)
class Lesson:
    id: str
    number: int
    title: str
    kind: str          # "vocab" or "grammar"
    unit: Unit
    words: list = field(default_factory=list)        # [{"word", "translation", "group", "section"}]
    notes: list = field(default_factory=list)
    explanation: list = field(default_factory=list)  # [{"p": …} | {"table": …} | …]
    exercises: list = field(default_factory=list)    # [{"q", "a", "de", "opts", "ask"}]
    sections: list = field(default_factory=list)     # [Section], at least one

    @property
    def multi(self) -> bool:
        """More than one section: each can be practised on its own."""
        return len(self.sections) > 1

    @property
    def is_vocab(self) -> bool:
        return self.kind == "vocab"

    @property
    def size(self) -> int:
        return len(self.words) if self.is_vocab else len(self.exercises)

    @property
    def kind_label(self) -> str:
        return t("kind.vocab") if self.is_vocab else t("kind.grammar")


def course_info(path: Path) -> dict | None:
    """The header of a course file (everything but the lessons), or None if it's unreadable."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    info = {k: v for k, v in data.items() if k != "units"}
    info["path"] = Path(path)
    return info


def course_gaps(data: dict) -> list:
    """Every place in a course file that lacks one of its native languages: [(path, language)].
    A translated text is a {"de": …, "en": …} dict; a word row needs one translation per native."""
    natives = data.get("natives", [])
    out = []

    def walk(o, path):
        if isinstance(o, dict):
            if o and set(o) <= set(natives) | set(i18n.UI_LANGUAGES):   # a translated text
                out.extend((path, n) for n in natives if not o.get(n))
                return
            for k, v in o.items():
                walk(v, f"{path}.{k}")
        elif isinstance(o, list):
            for i, v in enumerate(o):
                walk(v, f"{path}[{i}]")

    walk(data, data.get("id", "course"))
    for u in data.get("units", []):
        for l in u.get("lessons", []):
            for s in l.get("sections") or [l]:
                for row in s.get("words", []):
                    if len(row) != 1 + len(natives) or not all(row):
                        out.append((f"{l.get('id')}: {row[0] if row else '?'}", t("cli.word_row")))
    return out


def list_courses(folder: Path) -> list:
    return [c for c in (course_info(p) for p in sorted(Path(folder).glob("*.json"))) if c and c.get("id")]


def _load_course(data: dict, native: str):
    """Units and lessons. Labels (unit, lesson and section titles, exercise instructions) are in the
    app language; what teaches or translates (explanations, notes, translations) is in the learner's
    native language, because it compares with that language. A label the course doesn't have in the
    app language falls back to the native language."""
    col = data["natives"].index(native) + 1 if native in data["natives"] else 1
    ui_lang = i18n.language()

    def label(value):
        if isinstance(value, dict) and value.get(ui_lang):
            return value[ui_lang]
        return loc(value, native)

    units, lessons, number = [], [], 0
    for ui, u in enumerate(data["units"], start=1):
        unit = Unit(u["id"], ui, label(u["title"]), label(u.get("subtitle", "")))
        for l in u["lessons"]:
            number += 1
            lesson = Lesson(l["id"], number, label(l["title"]), l["type"], unit,
                            notes=[loc(n, native) for n in l.get("notes", [])])
            parts = l.get("sections") or [l]   # no "sections": the lesson itself is the one section
            for si, s in enumerate(parts, start=1):
                sec = Section(si, label(s.get("title", "")) if s is not l else "")
                for row in s.get("words", []):
                    e = {"word": row[0], "translation": row[col], "group": l["id"], "section": si}
                    sec.words.append(e)
                    lesson.words.append(e)
                sec.explanation = loc(s.get("explanation", []), native)
                if len(parts) > 1 and sec.title and sec.explanation:
                    lesson.explanation.append({"h": t("fmt.section", n=si, title=sec.title)})
                lesson.explanation.extend(sec.explanation)
                for ex in s.get("exercises", []):
                    sec.exercises.append(len(lesson.exercises))
                    lesson.exercises.append({"q": loc(ex[0], native), "a": ex[1], "de": loc(ex[2], native),
                                             "opts": ex[3], "ask": label(ex[4]) if len(ex) > 4 and ex[4] else None})
                lesson.sections.append(sec)
            unit.lessons.append(lesson)
            lessons.append(lesson)
        units.append(unit)
    return units, lessons


@dataclass
class Card:
    """One question as the window shows it."""
    kind: str            # "choice" or "type"
    ask: str             # instruction line
    shown: str           # the big text
    hint: str            # small text under it (e.g. the German translation)
    options: list
    correct: int
    expected: str        # for typing; may hold alternatives "a / b"
    strict: bool         # grammar: accents must be right, no optional article
    solution: str        # shown after answering
    word: str | None     # vocabulary word to record for spaced repetition
    accents: bool        # show the accent buttons
    item: tuple = None
    retry: bool = False


def item_key(item: tuple) -> str:
    if item[0] == "w":
        return f"w:{item[1]['word']}"
    return f"x:{item[1].id}:{item[2]}"


class Trainer:
    def __init__(self, course_path: Path, data_dir: Path, cfg: dict, native: str):
        data = json.loads(Path(course_path).read_text(encoding="utf-8"))
        self.course_id = data["id"]
        self.native_code = native
        # Course and language names are interface texts: they follow the app language (read live). Lesson
        # labels follow the app language too, set at load: the app reloads the course when it changes.
        # Lesson content follows the native language.
        self._names = {"short": data["short"], "name": data["name"],
                       "variant": data.get("variant", data["name"]), "coverage": data.get("coverage", "")}
        self.tag = data.get("tag", data["language"].upper())
        self.accents = data.get("accents", "")
        self._level = data.get("level", "")
        ARTICLES.clear()
        ARTICLES.update(a.lower() for a in data.get("articles", []))
        EQUIVALENTS.clear()
        EQUIVALENTS.update(data.get("equivalents", {}))
        self.units, self.lessons = _load_course(data, native)
        self.entries = [e for l in self.lessons for e in l.words]
        self.by_word = {e["word"]: e for e in self.entries}
        self._lesson_of = {e["word"]: l for l in self.lessons for e in l.words}
        self.cfg = cfg
        self.lock = threading.RLock()
        self.recent: list = []

        folder = Path(data_dir)
        folder.mkdir(parents=True, exist_ok=True)
        self.progress_path = folder / FILES["progress"]
        self.history_path = folder / FILES["history"]
        self.lessons_path = folder / FILES["lessons"]
        self.daily_path = folder / FILES["daily"]
        self.progress = self._load(self.progress_path)
        self.history = self._load(self.history_path)
        self.lesson_records = self._load(self.lessons_path)
        self.daily = self._load(self.daily_path)

    # ---------- names (in the app language) ----------
    @property
    def language(self) -> str:       # e.g. "Portuguese"
        return loc(self._names["short"])

    @property
    def course_name(self) -> str:    # e.g. "Portuguese (Portugal)"
        return loc(self._names["name"])

    @property
    def variant(self) -> str:
        return loc(self._names["variant"])

    @property
    def coverage(self) -> str:
        return loc(self._names["coverage"])

    @property
    def level_name(self) -> str:     # the course level, e.g. "A1"
        return i18n.cefr(self._level) if self._level else ""

    @property
    def native(self) -> str:         # the native language's name, e.g. "German"
        return i18n.language_name(self.native_code)

    # ---------- persistence ----------
    @staticmethod
    def _load(path: Path) -> dict:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    @staticmethod
    def _write(path: Path, data: dict) -> None:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, path)

    def _save(self) -> None:
        self._write(self.progress_path, self.progress)
        self._write(self.history_path, self.history)

    def reset(self) -> None:
        with self.lock:
            self.progress, self.history, self.lesson_records, self.daily, self.recent = {}, {}, {}, {}, []
            self._save()
            self._write(self.lessons_path, self.lesson_records)
            self._write(self.daily_path, self.daily)

    # ---------- words ----------
    def progress_of(self, word: str) -> dict | None:
        with self.lock:
            p = self.progress.get(word)
            return dict(p) if p else None

    def level(self, word: str) -> int:
        with self.lock:
            return level_of(self.progress.get(word))

    def lesson_of(self, word: str) -> Lesson | None:
        return self._lesson_of.get(word)

    def lesson_levels(self, lesson: Lesson) -> list:
        counts = [0, 0, 0, 0]
        with self.lock:
            for e in lesson.words:
                counts[level_of(self.progress.get(e["word"]))] += 1
        return counts

    def due_entries(self, limit: int | None = None) -> list:
        now = time.time()
        with self.lock:
            due = [(_due(p), w) for w, p in self.progress.items()
                   if w in self.by_word and now >= _due(p)]
        due.sort()
        return [self.by_word[w] for _, w in due[:limit]]

    def next_due_at(self) -> float | None:
        with self.lock:
            times = [_due(p) for w, p in self.progress.items() if w in self.by_word]
        return min(times) if times else None

    def hard_entries(self, limit: int = 10) -> list:
        with self.lock:
            scored = [((p["wrong"] / (p["right"] + p["wrong"]), p["wrong"]), w)
                      for w, p in self.progress.items() if w in self.by_word and p["wrong"]]
        scored.sort(reverse=True)
        return [self.by_word[w] for _, w in scored[:limit]]

    def seen_entries(self) -> list:
        with self.lock:
            return [e for e in self.entries if e["word"] in self.progress]

    def known_entries(self) -> list:
        """Words answered right at least once."""
        with self.lock:
            return [e for e in self.entries if self.progress.get(e["word"], {}).get("right", 0) >= 1]

    # ---------- lessons ----------
    def lesson_record(self, lesson: Lesson) -> dict | None:
        with self.lock:
            r = self.lesson_records.get(lesson.id)
            return dict(r) if r else None

    def is_done(self, lesson: Lesson) -> bool:
        return lesson.id in self.lesson_records

    @staticmethod
    def _section_id(lesson: Lesson, section: Section) -> str:
        return f"{lesson.id}/{section.key}"

    def section_record(self, lesson: Lesson, section: Section) -> dict | None:
        with self.lock:
            r = self.lesson_records.get(self._section_id(lesson, section))
            return dict(r) if r else None

    def complete_section(self, lesson: Lesson, section: Section, score: int) -> None:
        """A section done on its own. Once every section is done, the lesson counts as done too."""
        with self.lock:
            self._record(self._section_id(lesson, section), score)
            recs = [self.lesson_records.get(self._section_id(lesson, s)) for s in lesson.sections]
            if lesson.id not in self.lesson_records and all(recs):
                self._record(lesson.id, round(sum(r["best"] for r in recs) / len(recs)))
            self._write(self.lessons_path, self.lesson_records)

    def _record(self, key: str, score: int) -> None:
        r = self.lesson_records.setdefault(key, {"best": 0, "runs": 0})
        r["best"] = max(r["best"], score)
        r["runs"] += 1
        r["last"] = int(time.time())

    def next_lesson(self) -> Lesson | None:
        """The first lesson in course order that hasn't been completed yet."""
        for lesson in self.lessons:
            if not self.is_done(lesson):
                return lesson
        return None

    def lesson_after(self, lesson: Lesson) -> Lesson | None:
        i = self.lessons.index(lesson)
        return self.lessons[i + 1] if i + 1 < len(self.lessons) else None

    def complete_lesson(self, lesson: Lesson, score: int) -> None:
        with self.lock:
            self._record(lesson.id, score)
            self._write(self.lessons_path, self.lesson_records)

    # ---------- daily challenge ----------
    def _draw_daily(self, exclude: set) -> None:
        known = [e["word"] for e in self.known_entries()]
        fresh = [w for w in known if w not in exclude]
        random.shuffle(fresh)
        words = fresh[:DAILY_SIZE]
        if len(words) < DAILY_SIZE:  # not enough other words: top up with the old ones
            rest = [w for w in known if w not in words]
            random.shuffle(rest)
            words += rest[:DAILY_SIZE - len(words)]
        self.daily = {"date": dt.date.today().isoformat(), "words": words, "best": None, "runs": 0}
        self._write(self.daily_path, self.daily)

    def daily_state(self) -> dict:
        """Today's challenge: {"date", "words", "best", "runs"}. Drawn fresh each day."""
        with self.lock:
            known = len(self.known_entries())
            d = self.daily
            words = [w for w in d.get("words", []) if w in self.by_word]
            stale = d.get("date") != dt.date.today().isoformat()
            # Topped up while nothing was played yet, e.g. after learning more words today.
            too_small = not d.get("runs") and len(words) < min(DAILY_SIZE, known)
            if stale or too_small:
                self._draw_daily(set())
            return dict(self.daily)

    def redraw_daily(self) -> None:
        with self.lock:
            self._draw_daily(set(self.daily.get("words", [])))

    def complete_daily(self, score: int) -> None:
        with self.lock:
            d = self.daily
            d["best"] = max(d.get("best") or 0, score)
            d["runs"] = d.get("runs", 0) + 1
            self._write(self.daily_path, d)

    # ---------- cards ----------
    def _distractors(self, entry: dict, field: str, n: int) -> list:
        right = entry[field]
        same_group = [e[field] for e in self.entries
                      if e["group"] == entry["group"] and e[field] != right]
        pool = list(dict.fromkeys(same_group))
        if len(pool) < n:
            pool += [e[field] for e in self.entries if e[field] != right and e[field] not in pool]
        return random.sample(pool, n)

    def make_question(self, entry: dict, reverse: bool, n_options: int = 3) -> Question:
        field = "word" if reverse else "translation"
        options = [entry[field]] + self._distractors(entry, field, n_options - 1)
        random.shuffle(options)
        if reverse:
            prompt = t("notif.how_say", w=quote(entry["translation"]), lang=self.language)
        else:
            prompt = t("notif.what_means", w=quote(entry["word"]))
        return Question(uuid.uuid4().hex[:8], entry["word"], entry["translation"], reverse,
                        prompt, options, options.index(entry[field]))

    def word_card(self, entry: dict, mode: str) -> Card:
        """mode: recognize (pick German), recall (pick foreign), write (type foreign),
        read (type German), auto (by how well it's known) or test (anything)."""
        if mode == "auto":
            p = self.progress_of(entry["word"])
            weak = p is None or p["box"] < 1
            mode = random.choice(["recognize", "recall"] if weak else ["recognize", "recall", "write", "read"])
        elif mode == "test":
            mode = random.choice(["recognize", "recall", "write", "read"])

        pt, de = entry["word"], entry["translation"]
        solution = t("fmt.pair", a=pt, b=de)
        if mode in ("recognize", "recall"):
            reverse = mode == "recall"
            q = self.make_question(entry, reverse, 4)
            ask = t("ask.recall", lang=self.language) if reverse else t("ask.recognize")
            return Card("choice", ask, de if reverse else pt, "", q.options, q.correct, q.correct_text,
                        False, solution, pt, False)
        if mode == "write":
            return Card("type", t("ask.write", lang=self.language), de, "", [], 0, pt, False, solution, pt, True)
        return Card("type", t("ask.read", native=self.native), pt, "", [], 0, de, False, solution, pt, False)

    def exercise_card(self, lesson: Lesson, idx: int) -> Card:
        ex = lesson.exercises[idx]
        first_answer = ex["a"].split(" / ")[0]
        if "___" in ex["q"]:
            filled = _without_hints(ex["q"].replace("___", first_answer))
            solution = f"{filled}\n{ex['de']}" if ex["de"] else filled
            hint = ex["de"]
        else:  # a German sentence; pick the Portuguese one
            solution, hint = first_answer, ""
        if ex["opts"]:
            options = list(ex["opts"])
            random.shuffle(options)
            return Card("choice", ex["ask"] or t("ask.choose"), ex["q"], hint, options,
                        options.index(ex["a"]), ex["a"], True, solution, None, False)
        return Card("type", ex["ask"] or t("ask.fill"), ex["q"], hint, [], 0, ex["a"], True,
                    solution, None, True)

    def card_for(self, item: tuple) -> Card:
        if item[0] == "w":
            return self.word_card(item[1], item[2])
        return self.exercise_card(item[1], item[2])

    # ---------- sessions ----------
    def lesson_session(self, lesson: Lesson, section: Section | None = None) -> "Session":
        """The whole lesson, or just one of its sections."""
        if lesson.is_vocab:
            words = section.words if section else lesson.words
            rounds = [(name, [("w", e, mode) for e in words], True)
                      for name, mode in ((t("round.recognize"), "recognize"), (t("round.recall"), "recall"),
                                         (t("round.write"), "write"))]
        else:
            ex = lesson.exercises
            idx = section.exercises if section else range(len(ex))
            rounds = [(t("round.choose"), [("x", lesson, i) for i in idx if ex[i]["opts"]], False),
                      (t("round.typing"), [("x", lesson, i) for i in idx if not ex[i]["opts"]], False)]
            rounds = [r for r in rounds if r[1]]
        title = i18n.sep(lesson.title, section.title) if section and section.title else lesson.title
        return Session(self, title, rounds, lesson=lesson, section=section)

    def practice_session(self, entries: list, title: str) -> "Session":
        return Session(self, title, [("", [("w", e, "auto") for e in entries], True)])

    def daily_session(self) -> "Session":
        words = [self.by_word[w] for w in self.daily_state()["words"] if w in self.by_word]
        return Session(self, t("daily.title"), [("", [("w", e, "test") for e in words], True)],
                       retry=False, daily=True)

    # ---------- notification quiz selection ----------
    def _pick_word(self) -> dict:
        seen = {w for w in self.progress if w in self.by_word}
        learning = sum(1 for w in seen if self.progress[w]["box"] <= 1)
        new_pool: set = set()
        if learning < self.cfg.get("new_words_at_once", 10):
            # New words come from the next lesson in the course, not from anywhere.
            for lesson in self.lessons:
                unseen = {e["word"] for e in lesson.words if e["word"] not in seen}
                if unseen:
                    new_pool = unseen
                    break

        candidates, weights = [], []
        for e in self.entries:
            w = e["word"]
            if w in self.recent:
                continue
            if w in seen:
                candidates.append(e)
                weights.append(BOX_WEIGHT[self.progress[w]["box"]])
            elif w in new_pool:
                candidates.append(e)
                weights.append(BOX_WEIGHT[0])

        if not candidates:  # tiny list or everything recent
            candidates, weights = self.entries, [1] * len(self.entries)
        return random.choices(candidates, weights=weights, k=1)[0]

    def next_question(self, word: str | None = None) -> Question:
        with self.lock:
            entry = self.by_word.get(word) if word else None
            if entry is None:
                entry = self._pick_word()
            self.recent = (self.recent + [entry["word"]])[-RECENT_MEMORY:]
            reverse = random.random() < self.cfg.get("reverse_chance", 0.0)
            return self.make_question(entry, reverse, 3)

    # ---------- answering ----------
    def record(self, q: Question, chosen: int) -> bool:
        return self.record_result(q.word, chosen == q.correct)

    def record_result(self, word: str, ok: bool) -> bool:
        """Right answers only move a word up a box once it is due, so cramming
        doesn't fake progress. A wrong answer sends it back to the start."""
        now = time.time()
        with self.lock:
            p = self.progress.setdefault(word, {"box": 0, "right": 0, "wrong": 0, "last": 0})
            if ok:
                p["right"] += 1
                if p["box"] == 0 or now >= _due(p):
                    p["box"] = min(MAX_BOX, p["box"] + 1)
                    p["due"] = int(now + INTERVAL_HOURS[p["box"]] * 3600)
            else:
                p["wrong"] += 1
                p["box"] = 0
                p["due"] = int(now)
            p["last"] = int(now)
            day = self.history.setdefault(dt.date.today().isoformat(), {"right": 0, "wrong": 0})
            day["right" if ok else "wrong"] += 1
            self._save()
        return ok

    def record_exercise(self, ok: bool) -> None:
        """Grammar answers count toward the daily streak and the chart too."""
        with self.lock:
            day = self.history.setdefault(dt.date.today().isoformat(), {"right": 0, "wrong": 0})
            day["right" if ok else "wrong"] += 1
            self._write(self.history_path, self.history)

    # ---------- stats ----------
    def _streak(self) -> int:
        day = dt.date.today()
        if day.isoformat() not in self.history:
            day -= dt.timedelta(days=1)  # today isn't over yet
        streak = 0
        while day.isoformat() in self.history:
            streak += 1
            day -= dt.timedelta(days=1)
        return streak

    def stats(self) -> dict:
        now = time.time()
        today = dt.date.today()
        with self.lock:
            seen = [p for w, p in self.progress.items() if w in self.by_word]
            right = sum(p["right"] for p in seen)
            wrong = sum(p["wrong"] for p in seen)
            levels = [0, 0, 0, 0]
            for e in self.entries:
                levels[level_of(self.progress.get(e["word"]))] += 1
            days = []
            for i in range(HISTORY_DAYS - 1, -1, -1):
                d = (today - dt.timedelta(days=i)).isoformat()
                h = self.history.get(d, {})
                days.append((d, h.get("right", 0), h.get("wrong", 0)))
            return {
                "total": len(self.entries),
                "seen": len(seen),
                "mastered": levels[3],
                "levels": levels,
                "right": right,
                "wrong": wrong,
                "accuracy": round(100 * right / (right + wrong)) if right + wrong else 0,
                "due": sum(1 for p in seen if now >= _due(p)),
                "streak": self._streak(),
                "today": days[-1][1] + days[-1][2],
                "days": days,
                "lessons_done": sum(1 for l in self.lessons if l.id in self.lesson_records),
                "lessons_total": len(self.lessons),
            }


class Session:
    """A run through rounds of items. Missed items come back a little later in the same
    round (unless retry is off, as in the Daily Challenge)."""

    def __init__(self, trainer: Trainer, title: str, rounds: list, *, retry: bool = True,
                 lesson: Lesson | None = None, section: Section | None = None, daily: bool = False):
        self.trainer = trainer
        self.title = title
        self.rounds = rounds          # [(name, [item, …], shuffle)]
        self.retry = retry
        self.lesson = lesson
        self.section = section        # set when only one section of the lesson is practised
        self.daily = daily
        self.total = sum(len(items) for _, items, _ in rounds)
        self.done = 0
        self.first_try: dict = {}     # (round, item key) -> right on the first try
        self.solutions: dict = {}     # item key -> solution text
        self.r = -1
        self.queue: list = []
        self.finished = False

    @property
    def round_label(self) -> str:
        if len(self.rounds) <= 1 or self.r < 0:
            return ""
        name = self.rounds[min(self.r, len(self.rounds) - 1)][0]
        return t("round.label", n=min(self.r, len(self.rounds) - 1) + 1, t=len(self.rounds), name=name)

    def next_card(self) -> Card | None:
        while not self.queue:
            self.r += 1
            if self.r >= len(self.rounds):
                self._finish()
                return None
            _, items, shuffle = self.rounds[self.r]
            items = list(items)
            if shuffle:
                random.shuffle(items)
            self.queue = [(it, False) for it in items]
        item, retry = self.queue.pop(0)
        card = self.trainer.card_for(item)
        card.item, card.retry = item, retry
        return card

    def answer(self, card: Card, ok: bool) -> None:
        if card.word:
            self.trainer.record_result(card.word, ok)
        else:
            self.trainer.record_exercise(ok)
        key = item_key(card.item)
        self.first_try.setdefault((self.r, key), ok)
        self.solutions[key] = card.solution
        if ok or not self.retry:
            self.done += 1
        else:
            self.queue.insert(min(2, len(self.queue)), (card.item, True))

    @property
    def score(self) -> int:
        n = len(self.first_try)
        return round(100 * sum(self.first_try.values()) / n) if n else 0

    @property
    def first_try_right(self) -> int:
        return sum(self.first_try.values())

    def mistake_solutions(self) -> list:
        keys = list(dict.fromkeys(k for (_, k), ok in self.first_try.items() if not ok))
        return [self.solutions[k] for k in keys]

    def _finish(self) -> None:
        if self.finished:
            return
        self.finished = True
        if self.lesson and self.section and self.lesson.multi:
            self.trainer.complete_section(self.lesson, self.section, self.score)
        elif self.lesson:
            self.trainer.complete_lesson(self.lesson, self.score)
        if self.daily:
            self.trainer.complete_daily(self.score)

    def again(self, only_mistakes: bool = False) -> "Session":
        if not only_mistakes:
            return Session(self.trainer, self.title, self.rounds, retry=self.retry,
                           lesson=self.lesson, section=self.section, daily=self.daily)
        bad = {k for k, ok in self.first_try.items() if not ok}
        rounds = [(name, [it for it in items if (i, item_key(it)) in bad], shuffle)
                  for i, (name, items, shuffle) in enumerate(self.rounds)]
        return Session(self.trainer, i18n.sep(self.title, t("sum.mistakes_suffix")), [r for r in rounds if r[1]])
