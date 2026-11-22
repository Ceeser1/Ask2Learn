"""Ask 2 Learn (A2L): a language course in a window, plus notification quizzes that won't leave you alone.

Run:  .venv\\Scripts\\pythonw.exe main.py            (opens the window; keeps running in the tray)
      .venv\\Scripts\\pythonw.exe main.py --hidden   (autostart: tray only, open the window from there)
      .venv\\Scripts\\python.exe  main.py --now      (also show a notification quiz right away)
      .venv\\Scripts\\python.exe  main.py --check    (print gaming/idle detection for 30 s)
      .venv\\Scripts\\python.exe  main.py --check-texts  (list texts missing a translation)
"""

import json
import logging
import os
import queue
import random
import shutil
import sys
import threading
import time
from pathlib import Path

import i18n
import presence
from appconfig import ANNOY_LEVELS, FILES, IDENTITY, ROOT, SOUNDS, THEMES, TIMING
from i18n import t

COURSES_DIR = ROOT / FILES["courses"]
DEFAULTS_PATH = ROOT / FILES["defaults"]
LOGO_PATH = ROOT / FILES["logo"]     # optional: your own logo replaces the placeholder
ICON_PATH = ROOT / FILES["icon"]
ICO_PATH = ROOT / FILES["ico"]
# A packaged .exe runs portable: data next to the .exe, so it never touches an installed copy's data.
PORTABLE = getattr(sys, "frozen", False)
DATA_DIR = (Path(sys.executable).parent / IDENTITY["portable_data_folder"] if PORTABLE
            else Path(os.environ.get("APPDATA", Path.home())) / IDENTITY["data_folder"])
SETTINGS_PATH = DATA_DIR / FILES["settings"]
LOG_PATH = DATA_DIR / FILES["log"]
TICK_SECONDS = TIMING["tick_seconds"]
GUI_QUIET_MINUTES = TIMING["gui_quiet_minutes"]  # no notification quiz this soon after practising in the window
PUMP_MS = TIMING["pump_ms"]

# The annoyance slider (app.json "annoyance_levels"), from quiet to unbearable. "schedule" decides
# when the next quiz comes:
#   never    – no quizzes at all
#   once     – one quiz after startup (wrong / ignored ones still come back until answered right)
#   interval – every interval_minutes
#   random   – at a random time between random_gap_hours after the last one
# wait_for_pause_seconds: a quiz waits for a short pause in your typing and clicking.
# escalate_after_ignores: ignored quizzes before the sound loops (0: never).
# interrupt_fullscreen: may pull you out of a fullscreen app or game instead of waiting.
RANDOM_GAP_SECONDS = tuple(h * 3600 for h in TIMING["random_gap_hours"])

log = logging.getLogger(IDENTITY["tray_id"])


# ---------- settings ----------
def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def load_config() -> dict:
    """Defaults from config.json (in the repo), overridden by the user's settings.json."""
    cfg = _read_json(DEFAULTS_PATH)
    cfg.update(_read_json(SETTINGS_PATH))
    return cfg


def save_settings(changes: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    settings = _read_json(SETTINGS_PATH)
    settings.update(changes)
    SETTINGS_PATH.write_text(json.dumps(settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def app_language(cfg: dict) -> str:
    """The interface language: the user's choice in the settings, otherwise the system language."""
    code = cfg.get("app_language") or i18n.system_language()
    return code if code in i18n.UI_LANGUAGES else i18n.FALLBACK


def course_data_dir(course_id: str) -> Path:
    return DATA_DIR / "courses" / course_id


def migrate_legacy() -> None:
    """Older versions kept the Portuguese progress next to the code. Move it to the user's data folder."""
    target = course_data_dir(FILES["legacy_course"])
    for name in (FILES["progress"], FILES["history"], FILES["lessons"], FILES["daily"]):
        old = ROOT / name
        if old.exists() and not (target / name).exists():
            target.mkdir(parents=True, exist_ok=True)
            shutil.move(str(old), target / name)
    for folder in IDENTITY["legacy_data_folders"]:
        renamed = DATA_DIR.parent / folder
        if renamed.is_dir() and not DATA_DIR.exists():
            shutil.move(str(renamed), DATA_DIR)
    old_log = ROOT / FILES["legacy_log"]
    if old_log.exists():
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        shutil.move(str(old_log), DATA_DIR / FILES["legacy_log_moved"])


# ---------- icon ----------
def make_icon_image(size: int = 64, on_dark: bool = False):
    """The logo (app.json files.logo) on a transparent background, otherwise a placeholder: the short
    app name (app.short) on a brand-blue tile, its middle letter in brand red (themes.json brand).
    on_dark: the logo's navy parts turn white, so it stays visible on the navy sidebar."""
    from PIL import Image, ImageDraw, ImageFont

    if LOGO_PATH.exists():
        logo = Image.open(LOGO_PATH).convert("RGBA")
        logo = logo.crop(logo.getchannel("A").getbbox() or (0, 0, *logo.size))  # drop the empty margin
        if on_dark:
            # navy = dark and bluish; teal and red are much brighter, so they stay as they are
            logo.putdata([(255, 255, 255, a) if r + g + b < 330 and b >= r else (r, g, b, a)
                          for r, g, b, a in logo.getdata()])
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        scale = min(size / logo.width, size / logo.height)
        logo = logo.resize((max(1, round(logo.width * scale)), max(1, round(logo.height * scale))), Image.LANCZOS)
        img.alpha_composite(logo, ((size - logo.width) // 2, (size - logo.height) // 2))
        return img
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    k = size / 64
    brand = THEMES["brand"]
    d.rounded_rectangle((2 * k, 2 * k, 62 * k, 62 * k), radius=14 * k, fill=brand["blue"])
    try:
        font = ImageFont.truetype(THEMES["icon_font"], int(22 * k))
    except OSError:
        font = ImageFont.load_default()
    short = t("app.short")
    middle = len(short) // 2
    parts = [(ch, brand["red"] if i == middle else brand["white"]) for i, ch in enumerate(short)]
    x = 32 * k - sum(font.getlength(s) for s, _ in parts) / 2
    for s, color in parts:
        d.text((x, 33 * k), s, fill=color, font=font, anchor="lm")
        x += font.getlength(s)
    return img


def make_icons() -> None:
    ICON_PATH.parent.mkdir(exist_ok=True)
    make_icon_image(64).save(ICON_PATH)
    make_icon_image(256).save(ICO_PATH, sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (256, 256)])


class App:
    def __init__(self, cfg: dict):
        from notifications import Notifier

        self.cfg = cfg
        make_icons()
        self.notifier = Notifier(ICON_PATH)
        self.trainer = None
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.events: queue.Queue = queue.Queue()  # "show" / "refresh" / "quit" for the window
        self.next_due = time.time() + cfg.get("first_quiz_after_minutes", 1) * 60
        self.once_done = False     # "only once after startup": the one quiz has been answered right
        self.retry_word = None     # word to ask again (wrong answer / ignored)
        self.open_since = None     # timestamp a quiz has been on screen since
        self.current_id = None
        self.ignored_in_row = 0
        self.paused_until = 0.0
        self.gui_quiet_until = 0.0
        self.tray = None
        self.root = None
        self.window = None
        i18n.set_language(app_language(cfg))
        self.load_course()

    # ---------- language & course ----------
    def courses(self) -> list:
        from quiz import list_courses
        return list_courses(COURSES_DIR)

    def load_course(self) -> bool:
        from quiz import Trainer

        native, course_id = self.cfg.get("native"), self.cfg.get("course")
        info = next((c for c in self.courses() if c["id"] == course_id), None)
        if not native or info is None or native not in info.get("natives", []):
            self.trainer = None
            return False
        self.trainer = Trainer(info["path"], course_data_dir(course_id), self.cfg, native)
        return True

    def choose_language(self, native: str, course_id: str) -> None:
        first_time = self.trainer is None
        save_settings({"native": native, "course": course_id})
        with self.lock:
            self.cfg.update(native=native, course=course_id)
            self.retry_word, self.current_id, self.open_since, self.ignored_in_row = None, None, None, 0
            self.next_due = time.time() + self._gap()
        self.load_course()
        log.info("Language: native=%s course=%s", native, course_id)
        self.update_tray()
        if first_time and self.trainer:
            self.notifier.show_info(t("ob.toast_title"), t("ob.toast_body", lang=self.trainer.language,
                                                            how=t(f"set.annoy.{self.annoy_level() or 'custom'}_d")))

    # ---------- notification quiz flow ----------
    def ask(self, interrupt: bool = False) -> None:
        """Show a quiz. interrupt: we're in fullscreen, where Windows hides toasts, so the quiz opens
        in the window instead and pulls the user out (only the "fuckoff" level does that)."""
        if self.trainer is None:
            return
        with self.lock:
            q = self.trainer.next_question(self.retry_word)
            self.current_id = q.id
            self.open_since = time.time()
            nags = self.ignored_in_row

        limit = self.cfg.get("escalate_after_ignores", 3)   # 0: never escalate to a looping sound
        escalate = bool(limit) and nags >= limit
        if nags == 0:
            header = self.trainer.language
        elif nags == 1:
            header = t("notif.ignored1")
        elif not escalate:
            header = t("notif.ignored2", n=nags)
        else:
            header = t("notif.ignored3", n=nags)
        log.info("Asking %r (reverse=%s, ignored=%d)", q.word, q.reverse, nags)
        if interrupt:
            log.info("Fullscreen: pulling the user out for %r", q.word)
            self.events.put(("interrupt", q, header))
            return
        self.notifier.show_quiz(
            q,
            header=header,
            sound=self.cfg.get("sound", SOUNDS["default"]),
            looping=self.cfg.get("looping_sound", False) or escalate,
            on_answer=self.on_answer,
            on_ignored=self.on_ignored,
        )

    def on_answer(self, q, chosen: int) -> None:
        with self.lock:
            if q.id != self.current_id or self.trainer is None:
                return
            self.current_id = None
            self.open_since = None
            self.ignored_in_row = 0
        ok = self.trainer.record(q, chosen)
        now = time.time()
        with self.lock:
            if ok:
                self.retry_word = None
                if self.cfg.get("schedule") == "once":
                    self.once_done = True
                self.next_due = now + self._gap()
                extra = ""
            else:
                self.retry_word = q.word
                mins = self.cfg.get("wrong_retry_minutes", 2)
                self.next_due = now + mins * 60
                extra = t("notif.retry", n=mins)
        log.info("Answer %r -> %s", q.word, "right" if ok else "wrong")
        self.notifier.show_feedback(q, chosen, ok, extra)
        self.update_tray()
        self.events.put("refresh")

    def on_ignored(self, q) -> None:
        with self.lock:
            if q.id != self.current_id:
                return
            self.current_id = None
            self.open_since = None
            self.ignored_in_row += 1
            self.retry_word = q.word
            self.next_due = time.time() + self.cfg.get("nag_minutes", 5) * 60
        log.info("Ignored %r (%d in a row)", q.word, self.ignored_in_row)

    # ---------- called from the window ----------
    def on_gui_answer(self) -> None:
        with self.lock:
            self.gui_quiet_until = time.time() + GUI_QUIET_MINUTES * 60
        self.update_tray()

    def update_config(self, changes: dict) -> None:
        now = time.time()
        with self.lock:
            self.cfg.update(changes)
            save_settings(changes)
            self.next_due = min(self.next_due, now + self._gap())
        log.info("Settings changed: %s", changes)

    def set_native(self, code: str) -> None:
        """Switch the native language (the course's translations) now and remember it."""
        save_settings({"native": code})
        with self.lock:
            self.cfg["native"] = code
            self.retry_word, self.current_id, self.open_since = None, None, None  # an open quiz has old texts
        self.load_course()
        log.info("Native language: %s", code)
        self.update_tray()

    def set_app_language(self, code: str) -> None:
        """Switch the interface language now and remember it."""
        save_settings({"app_language": code})
        self.cfg["app_language"] = code
        i18n.set_language(code)
        self.load_course()   # lesson and unit titles follow the app language
        log.info("App language: %s", code)
        self.update_tray()

    def icon_image(self, size: int, on_dark: bool = False):
        return make_icon_image(size, on_dark)

    @property
    def annoy_presets(self) -> dict:
        """The slider levels in order, quiet to unbearable."""
        return ANNOY_LEVELS

    def annoy_level(self) -> str | None:
        for name, preset in ANNOY_LEVELS.items():
            if all(self.cfg.get(k) == v for k, v in preset.items()):
                return name
        return None

    def set_annoy_level(self, name: str) -> None:
        """Apply a slider level. The new rhythm starts now (a waiting quiz isn't kept from the old one)."""
        changes = dict(ANNOY_LEVELS[name])
        with self.lock:
            self.cfg.update(changes)
            save_settings(changes)
            now = time.time()
            if changes["schedule"] == "once" and not self.once_done:
                self.next_due = now + self.cfg.get("first_quiz_after_minutes", 1) * 60
            else:
                self.next_due = now + self._gap()
        log.info("Annoyance level: %s", name)
        self.update_tray()

    def _gap(self) -> float:
        """Seconds from now until the next regular quiz (inf: none)."""
        schedule = self.cfg.get("schedule", "interval")
        if schedule == "never" or (schedule == "once" and self.once_done):
            return float("inf")
        if schedule == "random":
            return random.uniform(*RANDOM_GAP_SECONDS)
        return self.cfg["interval_minutes"] * 60

    # ---------- scheduler ----------
    def loop(self) -> None:
        while not self.stop.wait(TICK_SECONDS):
            try:
                self.tick()
            except Exception:
                log.exception("Tick failed")

    def tick(self) -> None:
        now = time.time()
        with self.lock:
            if self.trainer is None or not self.cfg.get("notifications", True):
                return
            if self.cfg.get("schedule") == "never":
                return
            if now < self.paused_until or now < self.gui_quiet_until:
                return
            if self.open_since is not None:
                # Safety net: a toast that vanished without telling us.
                if now - self.open_since > self.cfg["interval_minutes"] * 60:
                    self.open_since = None
                    self.current_id = None
                return
            if now < self.next_due:
                return
        busy = presence.is_busy()
        if busy and not self.cfg.get("interrupt_fullscreen", False):
            return  # gaming / fullscreen: try again next tick
        idle = presence.idle_seconds()
        if idle > self.cfg.get("away_after_minutes", 5) * 60:
            return  # nobody at the PC: wait until they're back
        if idle < self.cfg.get("wait_for_pause_seconds", 0):
            return  # busy typing / clicking: wait for a short pause instead of interrupting
        self.ask(interrupt=busy)

    def listen_for_show(self, handle) -> None:
        while not self.stop.is_set():
            if presence.wait_for_event(handle, 1000):
                self.events.put("show")

    # ---------- window + tray ----------
    def run(self, show_window: bool, show_event) -> None:
        import tkinter as tk

        import pystray

        import gui

        self.root = tk.Tk()
        try:
            self.root.iconbitmap(default=str(ICO_PATH))
        except tk.TclError:
            pass
        self.window = gui.MainWindow(self.root, self)
        if not show_window and self.trainer is not None:
            self.root.withdraw()

        def ask_now(icon, item):
            with self.lock:
                self.open_since = None
            self.ask()

        def toggle_pause(icon, item):
            with self.lock:
                if time.time() < self.paused_until:
                    self.paused_until = 0
                else:
                    self.paused_until = time.time() + 3600
            self.update_tray()

        def is_paused(item):
            return time.time() < self.paused_until

        menu = pystray.Menu(
            pystray.MenuItem(lambda item: t("tray.open"), lambda icon, item: self.events.put("show"), default=True),
            pystray.MenuItem(lambda item: t("tray.ask"), ask_now, enabled=lambda item: self.trainer is not None),
            pystray.MenuItem(lambda item: t("tray.pause"), toggle_pause, checked=is_paused),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(lambda item: t("tray.quit"), lambda icon, item: self.events.put("quit")),
        )
        self.tray = pystray.Icon(IDENTITY["tray_id"], make_icon_image(), t("app.name"), menu)
        threading.Thread(target=self.tray.run, daemon=True).start()
        threading.Thread(target=self.loop, daemon=True).start()
        threading.Thread(target=self.listen_for_show, args=(show_event,), daemon=True).start()
        self.update_tray()

        self.root.after(PUMP_MS, self.pump)
        self.root.mainloop()
        self.stop.set()
        self.tray.stop()

    def pump(self) -> None:
        """Runs window work on the Tk thread for the tray / notification threads."""
        try:
            while True:
                event = self.events.get_nowait()
                if event == "show":
                    self.window.present()
                elif event == "refresh":
                    self.window.refresh()
                elif isinstance(event, tuple) and event[0] == "interrupt":
                    self.window.interrupt(*event[1:])
                elif event == "quit":
                    self.root.destroy()
                    return
        except queue.Empty:
            pass
        except Exception:
            log.exception("Window update failed")
        self.root.after(PUMP_MS, self.pump)

    def update_tray(self) -> None:
        if self.tray is None:
            return
        if self.trainer is None:
            self.tray.title = f"{t('app.name')}\n{t('tray.setup')}"
        else:
            s = self.trainer.stats()
            self.tray.title = f"{t('app.name')}\n" + t("tray.tooltip", lang=self.trainer.language, m=s["mastered"],
                                                   t=s["total"], d=s["due"])
        try:
            self.tray.update_menu()
        except Exception:
            pass


def check_texts() -> int:
    """Every interface text in every app language, every course text in every native language
    the course offers. Prints the gaps; exit code 1 if there are any."""
    from quiz import course_gaps

    gaps = [t("cli.gap_ui", key=key, lang=lang) for key, lang in i18n.missing_translations()]
    for path in sorted(COURSES_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        gaps += [t("cli.gap_course", file=path.name, where=where, lang=lang) for where, lang in course_gaps(data)]
    for g in gaps:
        print(g)
    print(t("cli.gaps", n=len(gaps)) if gaps else t("cli.all_ok", ui=", ".join(i18n.UI_LANGUAGES)))
    return 1 if gaps else 0


def check_detection() -> None:
    print(t("cli.watch"))
    for _ in range(30):
        print(t("cli.watch_line", busy=presence.is_busy(), idle=round(presence.idle_seconds())), flush=True)
        time.sleep(1)


def main() -> None:
    presence.make_dpi_aware()
    migrate_legacy()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    handlers = [logging.FileHandler(LOG_PATH, encoding="utf-8")]
    if sys.stdout is not None:  # pythonw has no console
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname)s %(message)s")

    if "--check" in sys.argv:
        check_detection()
        return
    if "--make-icon" in sys.argv:
        make_icons()
        return
    if "--check-texts" in sys.argv:
        sys.exit(check_texts())

    hidden = "--hidden" in sys.argv
    # portable and installed copies don't block each other
    instance = IDENTITY["portable_instance"] if PORTABLE else IDENTITY["instance"]
    presence.SHOW_EVENT = IDENTITY["show_event"].format(instance=instance)
    mutex = presence.acquire_single_instance(IDENTITY["single_instance"].format(instance=instance))
    if mutex is None:
        if not hidden and presence.signal_show():
            log.info("Already running, asked it to show the window.")
        else:
            log.info("Already running, exiting.")
        return
    show_event = presence.create_show_event()

    cfg = load_config()
    if "--now" in sys.argv:
        cfg["first_quiz_after_minutes"] = 0.05
    app = App(cfg)
    log.info("Started (native=%s, course=%s)", cfg.get("native"), cfg.get("course"))
    try:
        app.run(show_window=not hidden, show_event=show_event)
    except Exception:
        log.exception("Crashed")
        raise


if __name__ == "__main__":
    main()
