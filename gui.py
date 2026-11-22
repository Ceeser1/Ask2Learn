"""The main window: welcome screen, overview, course, lessons, practice, daily challenge, review,
dictionary and settings. Every text comes from i18n."""

import datetime as dt
import random
import time
import tkinter as tk
from tkinter import messagebox, ttk
from types import SimpleNamespace

import i18n
from appconfig import LEARNING, THEMES
from i18n import loc, quote, t, tl
from quiz import DAILY_SIZE, check_typed, level_name

# Colors and fonts come from themes.json (brand palette from the A2L logo, a light and a dark theme).
FONT = THEMES["font"]
DEFAULT_THEME = THEMES["default"]
PALETTES = THEMES["themes"]
C = dict(PALETTES[DEFAULT_THEME])  # the active theme; widgets read it when they are built


def apply_theme(name: str) -> str:
    name = name if name in PALETTES else DEFAULT_THEME
    C.clear()
    C.update(PALETTES[name])
    return name


REVIEW_BATCH = LEARNING["review_batch"]
MIX_BATCH = LEARNING["mix_batch"]
NAV = ["overview", "course", "daily", "review", "words"]
NAV_BOTTOM = ["settings"]
SECTION = {"overview": "overview", "course": "course", "lesson": "course", "cards": "course",
           "daily": "daily", "review": "review", "words": "words", "settings": "settings"}
REFRESHABLE = {"overview", "course", "lesson", "daily", "review", "words"}


def font(size: int, weight: str = "normal"):
    return (FONT, size, weight)


def fmt_when(ts: float) -> str:
    secs = ts - time.time()
    if secs < 3600:
        return t("when.minutes", n=max(1, round(secs / 60)))
    if secs < 20 * 3600:
        return t("when.hours", n=round(secs / 3600))
    days = (dt.date.fromtimestamp(ts) - dt.date.today()).days
    return t("when.tomorrow") if days <= 1 else t("when.days", n=days)


class FlatButton(tk.Label):
    """A flat, colored button (tk.Button can't be styled properly on Windows)."""

    def __init__(self, parent, text, command, bg, fg, hover, **kw):
        super().__init__(parent, text=text, bg=bg, fg=fg, cursor="hand2", **kw)
        self.command = command
        self.colors = (bg, fg, hover)
        self.enabled = True
        self.bind("<Enter>", lambda e: self.enabled and self.config(bg=self.colors[2]))
        self.bind("<Leave>", lambda e: self.enabled and self.config(bg=self.colors[0]))
        self.bind("<Button-1>", self._click)

    def _click(self, _):
        if self.enabled and self.command:
            self.command()

    def set_style(self, bg, fg, hover=None):
        self.colors = (bg, fg, hover or bg)
        self.config(bg=bg, fg=fg)

    def disable(self):
        self.enabled = False
        self.config(cursor="arrow")


class MainWindow:
    def __init__(self, root: tk.Tk, app):
        self.root = root
        self.app = app
        self.scale = root.winfo_fpixels("1i") / 96
        self.page = ("overview", ())
        self.section = None
        self.key_handler = None
        self._afters: list = []
        self._scroll_canvas = None
        self.word_filter = {"text": "", "level": None}
        self.nav_buttons = {}
        self._icons: dict = {}
        self.theme = apply_theme(app.cfg.get("theme", DEFAULT_THEME))

        root.title(t("app.name"))
        root.configure(bg=C["bg"])
        root.geometry(f"{self.px(1080)}x{self.px(740)}")
        root.minsize(self.px(1010), self.px(660))
        root.protocol("WM_DELETE_WINDOW", self.close)
        self._setup_styles()

        self.sidebar = tk.Frame(root, bg=C["sidebar"], width=self.px(210))
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)
        self.content = tk.Frame(root, bg=C["bg"])
        self.content.pack(side="left", fill="both", expand=True)

        root.bind("<Key>", lambda e: self.key_handler and self.key_handler(e))
        root.bind_all("<MouseWheel>", self._on_wheel)
        self._apply_titlebar()
        self.rebuild()

    @property
    def trainer(self):
        return self.app.trainer

    # ---------- basics ----------
    def px(self, n: float) -> int:
        return int(round(n * self.scale))

    def set_theme(self, name: str):
        """Switch between dark and light mode, save it and rebuild the window in the new colors."""
        self.theme = apply_theme(name)
        self.app.update_config({"theme": self.theme})
        self.root.configure(bg=C["bg"])
        self.sidebar.configure(bg=C["sidebar"])
        self.content.configure(bg=C["bg"])
        self._setup_styles()
        self._apply_titlebar()
        self._build_sidebar()
        self.show("settings", t("set.saved"))

    def _apply_titlebar(self):
        """Dark or light Windows title bar to match the theme (Windows 10 20H1+ / 11; ignored elsewhere)."""
        try:
            import ctypes
            self.root.update_idletasks()
            hwnd = int(self.root.wm_frame(), 16)
            value = ctypes.c_int(1 if C["dark_titlebar"] else 0)
            for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE; 19 on older Windows 10 builds
                if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(value),
                                                              ctypes.sizeof(value)) == 0:
                    break
        except Exception:
            return
        # Windows only repaints the title bar on a size change: nudge the window by a pixel and back.
        if self.root.winfo_viewable() and self.root.state() == "normal":
            w, h = self.root.winfo_width(), self.root.winfo_height()
            self.root.geometry(f"{w + 1}x{h}")
            self.root.update_idletasks()
            self.root.geometry(f"{w}x{h}")

    def _setup_styles(self):
        st = ttk.Style(self.root)
        st.theme_use("clam")
        st.configure("Treeview", background=C["card"], fieldbackground=C["card"],
                     foreground=C["text"], rowheight=self.px(30), font=font(10), borderwidth=0,
                     bordercolor=C["card"], lightcolor=C["card"], darkcolor=C["card"])
        st.configure("Treeview.Heading", background=C["bg"], foreground=C["muted"],
                     font=font(9, "bold"), relief="flat", padding=(self.px(8), self.px(6)),
                     bordercolor=C["border"], lightcolor=C["bg"], darkcolor=C["bg"])
        st.map("Treeview", background=[("selected", C["accent_soft"])],
               foreground=[("selected", C["text"])])
        st.map("Treeview.Heading", background=[("active", C["border"])])
        st.configure("Vertical.TScrollbar", background=C["border"], troughcolor=C["bg"],
                     bordercolor=C["bg"], arrowcolor=C["muted"], relief="flat",
                     lightcolor=C["border"], darkcolor=C["border"], gripcount=0)
        # Dropdowns are one piece: a flat arrow inside the field (no separate button box). The visible
        # border comes from the frame around each dropdown (see dropdown()), because in clam the arrow
        # element draws the field's right edge.
        if "Flat.downarrow" not in st.element_names():
            st.element_create("Flat.downarrow", "from", "default")
        st.layout("TCombobox", [("Combobox.field", {"sticky": "nswe", "children": [
            ("Flat.downarrow", {"side": "right", "sticky": "ns"}),
            ("Combobox.padding", {"expand": "1", "sticky": "nswe", "children": [
                ("Combobox.textarea", {"sticky": "nswe"})]})]})])
        st.configure("TCombobox", fieldbackground=C["card"], background=C["card"], foreground=C["text"],
                     arrowcolor=C["accent"], bordercolor=C["card"], lightcolor=C["card"], darkcolor=C["card"],
                     relief="flat", arrowsize=self.px(13), padding=(self.px(10), self.px(7), self.px(4), self.px(7)))
        st.map("TCombobox", fieldbackground=[("readonly", C["card"])], selectbackground=[("readonly", C["card"])],
               selectforeground=[("readonly", C["text"])], bordercolor=[("focus", C["card"])],
               background=[("active", C["card"]), ("pressed", C["card"]), ("readonly", C["card"])])
        self.root.option_add("*TCombobox*Listbox.font", font(11))
        self.root.option_add("*TCombobox*Listbox.selectBackground", C["accent_soft"])
        self.root.option_add("*TCombobox*Listbox.selectForeground", C["text"])
        self.root.option_add("*TCombobox*Listbox.background", C["card"])
        self.root.option_add("*TCombobox*Listbox.foreground", C["text"])

    def rebuild(self):
        """(Re)build everything for the current language and course."""
        self.root.title(t("app.name"))
        self._build_sidebar()
        self.word_filter = {"text": "", "level": None}
        self.show("overview" if self.trainer else "onboarding")

    def present(self):
        self.root.deiconify()
        if self.root.state() == "iconic":
            self.root.state("normal")
        self.root.attributes("-topmost", True)
        self.root.lift()
        self.root.after(200, lambda: self.root.attributes("-topmost", False))
        self.root.focus_force()
        self.refresh()

    def interrupt(self, q, header):
        """The "Fuck-Off" level while a fullscreen app has the focus: Windows hides toasts there, so the
        quiz opens here, on top of everything, until it's answered. Afterwards the window gets out of
        the way again (hidden if it was hidden, minimized otherwise) so the user can go back."""
        was_hidden = self.root.state() == "withdrawn"
        back = self.page if self.page[0] not in ("alert", "summary", "practice") else ("overview", ())
        self.show("alert", q, header, was_hidden, back)
        self.root.deiconify()
        if self.root.state() == "iconic":
            self.root.state("normal")
        self.root.attributes("-topmost", True)
        self.root.lift()
        self.root.update_idletasks()
        try:
            import presence
            presence.force_foreground(int(self.root.wm_frame(), 16))
        except Exception:
            pass
        self.root.focus_force()

    def close(self):
        """The window's X quits the whole app, tray and notification quizzes included."""
        self.app.events.put("quit")

    def refresh(self):
        if self.trainer and self.page[0] in REFRESHABLE and self.root.state() != "withdrawn":
            self.show(self.page[0], *self.page[1])

    def show(self, page: str, *args):
        for a in self._afters:
            try:
                self.root.after_cancel(a)
            except tk.TclError:
                pass
        self._afters.clear()
        self.key_handler = None
        # Redrawing the same page (a setting changed): keep the scroll position instead of jumping up.
        keep_scroll = None
        if self._scroll_canvas is not None and page == self.page[0]:
            try:
                keep_scroll = self._scroll_canvas.yview()[0]
            except tk.TclError:
                pass
        self._scroll_canvas = None
        for w in self.content.winfo_children():
            w.destroy()
        self.page = (page, args)
        if page == "onboarding":
            self.sidebar.pack_forget()
        elif not self.sidebar.winfo_manager():
            self.sidebar.pack(side="left", fill="y", before=self.content)
        self._set_section(SECTION.get(page, self.section))
        body = tk.Frame(self.content, bg=C["bg"])
        body.pack(fill="both", expand=True, padx=self.px(32), pady=(self.px(24), self.px(20)))
        self.root.focus_set()
        getattr(self, f"_page_{page}")(body, *args)
        if keep_scroll and self._scroll_canvas is not None:
            cv = self._scroll_canvas
            self.root.update_idletasks()   # the scroll region must exist before moving to it
            cv.configure(scrollregion=cv.bbox("all"))
            cv.yview_moveto(keep_scroll)

    def later(self, ms: int, fn):
        a = self.root.after(ms, fn)
        self._afters.append(a)
        return a

    def _on_wheel(self, e):
        cv = self._scroll_canvas
        if cv is None or not cv.winfo_exists() or cv.yview() == (0.0, 1.0):
            return
        cv.yview_scroll(int(-e.delta / 120), "units")

    # ---------- building blocks ----------
    def label(self, parent, text="", size=10, weight="normal", color="text", **kw):
        kw.setdefault("justify", "left")
        return tk.Label(parent, text=text, font=font(size, weight), bg=parent["bg"],
                        fg=C.get(color, color), **kw)

    def button(self, parent, text, command, kind="primary", size=10):
        styles = {
            "primary": (C["accent"], C["on_accent"], C["accent_hover"]),
            "secondary": (C["accent_soft"], C["accent"], C["accent_soft_hover"]),
            "danger": (C["bad"], "white", C["bad_hover"]),
            "ghost": (parent["bg"], C["muted"], C["border"]),
        }
        bg, fg, hover = styles[kind]
        pad = (self.px(6), self.px(4)) if kind == "ghost" else (self.px(18), self.px(9))
        return FlatButton(parent, text, command, bg, fg, hover, font=font(size, "bold"),
                          padx=pad[0], pady=pad[1])

    def dropdown(self, parent, values, width=30, current=0, on_select=None):
        """A one-piece dropdown. Returns the combobox; pack or grid its frame: `box.master`.
        The frame draws the border and turns to the accent color on hover and focus."""
        wrap = tk.Frame(parent, bg=C["card"], highlightthickness=1, highlightbackground=C["border"],
                        highlightcolor=C["border"])
        box = ttk.Combobox(wrap, state="readonly", font=font(11), width=width, values=values)
        if values:
            box.current(current)
        box.pack(padx=(0, self.px(6)))
        state = {"hover": False, "focus": False}

        def paint(**kw):
            state.update(kw)
            color = C["accent"] if state["hover"] or state["focus"] else C["border"]
            wrap.config(highlightbackground=color, highlightcolor=color)

        box.bind("<Enter>", lambda e: paint(hover=True), add="+")
        box.bind("<Leave>", lambda e: paint(hover=False), add="+")
        box.bind("<FocusIn>", lambda e: paint(focus=True), add="+")
        box.bind("<FocusOut>", lambda e: paint(focus=False), add="+")
        if on_select:
            box.bind("<<ComboboxSelected>>", on_select)
        return box

    def notice(self, parent, text, kind="warn"):
        """A notice row, not packed yet. kind "warn": a red triangle with an "!",
        kind "info": a blue circle with an "i"."""
        warn = kind == "warn"
        row = tk.Frame(parent, bg=C["red_soft"] if warn else C["accent_soft"], padx=self.px(12), pady=self.px(10))
        size = self.px(26)
        sign = tk.Canvas(row, width=size, height=size, bg=row["bg"], highlightthickness=0)
        m = self.px(1)
        if warn:
            sign.create_polygon(size / 2, m, size - m, size - m, m, size - m, fill=C["red"], outline=C["red"],
                                joinstyle="round", width=self.px(2))
            sign.create_text(size / 2, size * 0.62, text="!", fill="white", font=font(11, "bold"))
        else:
            sign.create_oval(m, m, size - m, size - m, fill=C["accent"], outline="")
            sign.create_text(size / 2, size / 2, text="i", fill=C["on_accent"], font=font(11, "bold"))
        sign.pack(side="left", anchor="n")
        lbl = self.label(row, text, 10, "bold", anchor="w", justify="left")
        lbl.configure(bg=row["bg"])
        lbl.pack(side="left", fill="x", expand=True, padx=(self.px(10), 0))
        self._autowrap(row, lbl, margin=50)
        return row

    def level_slider(self, parent, steps: int):
        """A slider that snaps to `steps` positions. Set `.on_move(i)` (while dragging) and
        `.on_change(i)` (on release / arrow key); `.set(i)` moves it without calling either."""
        pad, r = self.px(12), self.px(9)
        cv = tk.Canvas(parent, bg=parent["bg"], height=self.px(32), highlightthickness=0, cursor="hand2",
                       takefocus=1)
        cv.level, cv.on_move, cv.on_change = 0, None, None

        def x_of(i):
            w = max(cv.winfo_width(), 2 * pad + 1)
            return pad + (w - 2 * pad) * i / (steps - 1)

        def draw(_=None):
            cv.delete("all")
            y = cv.winfo_height() // 2 or self.px(16)
            cv.create_line(x_of(0), y, x_of(steps - 1), y, fill=C["border"], width=self.px(4), capstyle="round")
            cv.create_line(x_of(0), y, x_of(cv.level), y, fill=C["accent"], width=self.px(4), capstyle="round")
            for i in range(steps):
                dot = self.px(3)
                color = C["accent"] if i <= cv.level else C["muted"]
                cv.create_oval(x_of(i) - dot, y - dot, x_of(i) + dot, y + dot, fill=color, outline="")
            x = x_of(cv.level)
            cv.create_oval(x - r, y - r, x + r, y + r, fill=C["accent"], outline=parent["bg"], width=self.px(3))

        def index_at(x):
            w = max(cv.winfo_width() - 2 * pad, 1)
            return max(0, min(steps - 1, round((x - pad) / w * (steps - 1))))

        def move(e):
            i = index_at(e.x)
            if i != cv.level:
                cv.level = i
                draw()
                if cv.on_move:
                    cv.on_move(i)

        def release(e):
            move(e)
            if cv.on_change:
                cv.on_change(cv.level)

        def key(d):
            i = max(0, min(steps - 1, cv.level + d))
            if i != cv.level:
                cv.level = i
                draw()
                if cv.on_change:
                    cv.on_change(i)
            return "break"

        def set_(i):
            cv.level = i
            draw()

        cv.set = set_
        cv.bind("<Configure>", draw)
        cv.bind("<Button-1>", lambda e: (cv.focus_set(), move(e)))
        cv.bind("<B1-Motion>", move)
        cv.bind("<ButtonRelease-1>", release)
        cv.bind("<Left>", lambda e: key(-1))
        cv.bind("<Right>", lambda e: key(1))
        return cv

    def card(self, parent, pad=20):
        outer = tk.Frame(parent, bg=C["card"], highlightthickness=1,
                         highlightbackground=C["border"], highlightcolor=C["border"])
        inner = tk.Frame(outer, bg=C["card"])
        inner.pack(fill="both", expand=True, padx=self.px(pad), pady=self.px(pad * 0.8))
        return outer, inner

    def header(self, parent, title, subtitle=None, back=None, eyebrow=None):
        if back:
            self.button(parent, t("fmt.back", text=back[0]), back[1], "ghost").pack(anchor="w", pady=(0, self.px(6)))
        if eyebrow:
            self.label(parent, eyebrow.upper(), 8, "bold", color="red").pack(anchor="w")
        self.label(parent, title, 20, "bold").pack(anchor="w")
        if subtitle:
            self.label(parent, subtitle, 10, color="muted", wraplength=self.px(760)).pack(
                anchor="w", pady=(self.px(2), 0))
        tk.Frame(parent, bg=C["bg"], height=self.px(16)).pack()

    def pill(self, parent, text, bg, fg):
        return tk.Label(parent, text=text, bg=bg, fg=fg, font=font(8, "bold"),
                        padx=self.px(8), pady=self.px(1))

    def level_pill(self, parent, level: int):
        return self.pill(parent, level_name(level), C["level"][level], C["level_text"][level])

    def kind_pill(self, parent, lesson):
        if lesson.is_vocab:
            return self.pill(parent, lesson.kind_label.upper(), C["teal_soft"], C["pill_text"])
        return self.pill(parent, lesson.kind_label.upper(), C["red_soft"], C["pill_text"])

    def level_bar(self, parent, counts, height=10, width=None):
        # Tk's default canvas width (~380 px) would stretch grids; bars fill their space anyway.
        cv = tk.Canvas(parent, height=self.px(height), width=self.px(width or 40), bg=parent["bg"],
                       highlightthickness=0)

        def draw(_=None):
            cv.delete("all")
            w, h, total = cv.winfo_width(), self.px(height), sum(counts) or 1
            x = 0.0
            for lvl in (3, 2, 1, 0):
                seg = w * counts[lvl] / total
                if seg > 0:
                    cv.create_rectangle(x, 0, x + seg, h, fill=C["level"][lvl], width=0)
                x += seg

        cv.bind("<Configure>", draw)
        return cv

    def progress_bar(self, parent, height=8):
        cv = tk.Canvas(parent, height=self.px(height), width=self.px(40), bg=parent["bg"], highlightthickness=0)
        cv.fraction = 0.0

        def draw(_=None):
            cv.delete("all")
            w, h = cv.winfo_width(), self.px(height)
            cv.create_rectangle(0, 0, w, h, fill=C["border"], width=0)
            if cv.fraction > 0:
                cv.create_rectangle(0, 0, w * cv.fraction, h, fill=C["teal"], width=0)

        def set_fraction(f):
            cv.fraction = f
            draw()

        cv.bind("<Configure>", draw)
        cv.set_fraction = set_fraction
        return cv

    def legend(self, parent, counts, horizontal=False):
        box = tk.Frame(parent, bg=parent["bg"])
        for lvl in (3, 2, 1, 0):
            row = tk.Frame(box, bg=parent["bg"])
            row.pack(side="left" if horizontal else "top", anchor="w",
                     padx=(0, self.px(16)) if horizontal else 0, pady=self.px(2))
            tk.Frame(row, bg=C["level"][lvl], width=self.px(10), height=self.px(10)).pack(side="left")
            self.label(row, f"  {level_name(lvl)}", 9).pack(side="left")
            self.label(row, f"  {counts[lvl]}", 9, "bold").pack(side="left")
        return box

    def tip(self, parent, text, title=None):
        box = tk.Frame(parent, bg=C["teal_soft"])
        tk.Frame(box, bg=C["teal"], width=self.px(4)).pack(side="left", fill="y")
        inner = tk.Frame(box, bg=C["teal_soft"])
        inner.pack(side="left", fill="both", expand=True, padx=self.px(12), pady=self.px(8))
        self.label(inner, title or t("tip.title"), 9, "bold").pack(anchor="w")
        lbl = self.label(inner, text, 10)
        lbl.pack(anchor="w", fill="x")
        self._autowrap(inner, lbl)
        return box

    def _autowrap(self, container, label, margin=10):
        container.bind("<Configure>", lambda e: label.config(wraplength=max(50, e.width - self.px(margin))), add="+")

    def scrollable(self, parent):
        outer = tk.Frame(parent, bg=parent["bg"])
        cv = tk.Canvas(outer, bg=parent["bg"], highlightthickness=0)
        sb = ttk.Scrollbar(outer, orient="vertical", command=cv.yview)
        inner = tk.Frame(cv, bg=parent["bg"])
        win = cv.create_window(0, 0, window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: cv.configure(scrollregion=cv.bbox("all")))
        cv.bind("<Configure>", lambda e: cv.itemconfigure(win, width=e.width))
        cv.configure(yscrollcommand=sb.set)
        cv.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self._scroll_canvas = cv
        return outer, inner

    def clickable(self, widget, command):
        widget.configure(cursor="hand2")
        widget.bind("<Button-1>", lambda e: command())
        for child in widget.winfo_children():
            if not isinstance(child, FlatButton):
                self.clickable(child, command)

    def lesson_eyebrow(self, lesson) -> str:
        return t("lesson.eyebrow", u=lesson.unit.number, unit=lesson.unit.title, n=lesson.number)

    def logo(self, parent, size=36):
        """The app logo, `size` px square, transparent. On a dark background (the sidebar, dark theme)
        it uses the light variant, whose navy parts are white."""
        px = self.px(size)
        r, g, b = (v / 257 for v in parent.winfo_rgb(parent["bg"]))
        on_dark = 0.299 * r + 0.587 * g + 0.114 * b < 128
        key = (px, on_dark)
        if key not in self._icons:
            try:
                from PIL import Image, ImageTk
                pil = self.app.icon_image(px * 4, on_dark=on_dark).resize((px, px), Image.LANCZOS)  # smooth edges
                self._icons[key] = ImageTk.PhotoImage(pil, master=self.root)
            except Exception:
                self._icons[key] = None
        if self._icons[key] is None:  # no icon available: plain text badge
            return tk.Label(parent, text=t("app.short"), bg=C["red"], fg="white", font=font(max(9, size // 3), "bold"),
                            width=4, pady=self.px(4))
        return tk.Label(parent, image=self._icons[key], bg=parent["bg"], bd=0)

    # ---------- sidebar ----------
    def _build_sidebar(self):
        for w in self.sidebar.winfo_children():
            w.destroy()
        self.nav_buttons = {}
        top = tk.Frame(self.sidebar, bg=C["sidebar"])
        top.pack(fill="x", padx=self.px(16), pady=(self.px(22), self.px(26)))
        self.logo(top, 44).pack(side="left")
        names = tk.Frame(top, bg=C["sidebar"])
        names.pack(side="left", padx=self.px(12))
        tk.Label(names, text=t("app.name"), bg=C["sidebar"], fg="white",
                 font=font(12, "bold")).pack(anchor="w")
        if self.trainer:
            course = t("fmt.course", name=self.trainer.language, level=self.trainer.level_name) \
                if self.trainer.level_name else self.trainer.language
            tk.Label(names, text=course, bg=C["sidebar"], fg=C["sidebar_muted"],
                     font=font(9, "bold")).pack(anchor="w")

        bottom = tk.Frame(self.sidebar, bg=C["sidebar"])
        bottom.pack(side="bottom", fill="x", pady=(0, self.px(14)))
        for parent, keys in ((self.sidebar, NAV), (bottom, NAV_BOTTOM)):
            for key in keys:
                b = FlatButton(parent, t(f"nav.{key}"), lambda k=key: self.show(k), C["sidebar"],
                               C["sidebar_text"], C["sidebar_hover"], font=font(10, "bold"),
                               anchor="w", padx=self.px(22), pady=self.px(10))
                b.pack(fill="x")
                self.nav_buttons[key] = b

    def _set_section(self, section):
        self.section = section
        for key, b in self.nav_buttons.items():
            if key == section:
                b.set_style(C["red"], "white")
            else:
                b.set_style(C["sidebar"], C["sidebar_text"], C["sidebar_hover"])

    @staticmethod
    def _course_label(c) -> str:
        """A course as listed in the language choice: name · level (coverage)."""
        text = t("fmt.course", name=loc(c["name"]), level=i18n.cefr(c.get("level", "")))
        return t("fmt.note", text=text, note=loc(c["coverage"])) if c.get("coverage") else text

    # ---------- pages: welcome / language choice ----------
    # ---------- page: fullscreen interrupt ("Fuck-Off" level) ----------
    def _page_alert(self, body, q, header, was_hidden, back):
        center = tk.Frame(body, bg=C["bg"])
        center.place(relx=0.5, rely=0.45, anchor="center")
        o, inn = self.card(center, pad=36)
        o.pack()
        self.label(inn, t("alert.title"), 20, "bold").pack(anchor="w")
        self.label(inn, t("alert.sub"), 10, color="muted", wraplength=self.px(560), justify="left").pack(
            anchor="w", pady=(self.px(4), self.px(22)))
        self.label(inn, header, 9, "bold", color="muted").pack(anchor="w")
        self.label(inn, q.prompt, 22, "bold", color="accent", wraplength=self.px(560), justify="left").pack(
            anchor="w", pady=(self.px(2), self.px(18)))
        buttons = []
        for i, option in enumerate(q.options):
            b = self.button(inn, t("fmt.numbered", n=i + 1, text=option), lambda i=i: answer(i), "secondary", 12)
            b.pack(fill="x", pady=(0, self.px(8)))
            buttons.append(b)
        result = self.label(inn, "", 11, "bold", wraplength=self.px(560), justify="left")
        result.pack(anchor="w", pady=(self.px(10), 0))
        done = {"answered": False}

        def leave():
            self.root.attributes("-topmost", False)
            if was_hidden:
                self.root.withdraw()
            else:
                self.show(*back)
                self.root.iconify()   # hands the focus back to the app the user came from

        def answer(i):
            if done["answered"]:
                return
            done["answered"] = True
            ok = i == q.correct
            for b in buttons:
                b.disable()
            self.app.on_answer(q, i)
            pair = t("fmt.pair", a=quote(q.word), b=quote(q.translation))
            if ok:
                result.config(text=t("fmt.verdict", verdict=t("notif.right"), pair=pair), fg=C["good"])
                self.later(1500, leave)
            else:
                result.config(text=t("fmt.verdict", verdict=t("notif.wrong"), pair=pair), fg=C["bad"])
                self.button(inn, t("alert.back"), leave).pack(anchor="w", pady=(self.px(12), 0))
                self.later(6000, leave)

        def key(e):
            if e.char in "123" and e.char and int(e.char) <= len(q.options):
                answer(int(e.char) - 1)

        self.key_handler = key

    def _page_onboarding(self, body, cancelable=False, native=None, course_id=None):
        system = i18n.system_language()
        # native languages: whatever the courses offer (a course file lists them), root language first
        natives = sorted({n for c in self.app.courses() for n in c.get("natives", [])} or set(i18n.UI_LANGUAGES),
                         key=lambda n: (n != i18n.FALLBACK, i18n.endonym(n)))
        native = native or self.app.cfg.get("native") or (system if system in natives else natives[0])
        courses = [c for c in self.app.courses() if native in c.get("natives", []) and c.get("language") != native]
        course_id = course_id or self.app.cfg.get("course")
        if course_id not in [c["id"] for c in courses]:
            course_id = courses[0]["id"] if courses else None

        course_label = self._course_label
        center = tk.Frame(body, bg=C["bg"])
        center.place(relx=0.5, rely=0.46, anchor="center")
        o, inn = self.card(center, pad=40)
        o.pack()
        self.logo(inn, 56).pack(anchor="w")
        self.label(inn, t("ob.welcome"), 22, "bold").pack(anchor="w", pady=(self.px(16), 0))
        self.label(inn, t("ob.tagline"), 11, color="muted").pack(anchor="w", pady=(self.px(2), self.px(26)))

        width = 54
        self.label(inn, t("ob.native"), 10, "bold").pack(anchor="w")
        native_box = self.dropdown(inn, [i18n.endonym(n) for n in natives], width=width,
                                   current=natives.index(native))
        native_box.master.pack(anchor="w", pady=(self.px(4), self.px(2)))
        if system in natives:
            detected = t("ob.detected", name=i18n.endonym(system))
        else:
            detected = t("ob.detected_other", name=i18n.endonym(system))
        self.label(inn, detected, 9, color="muted").pack(anchor="w", pady=(0, self.px(16)))

        self.label(inn, t("ob.target"), 10, "bold").pack(anchor="w")
        if courses:
            target_box = self.dropdown(inn, [course_label(c) for c in courses], width=width,
                                       current=[c["id"] for c in courses].index(course_id))
            target_box.master.pack(anchor="w", pady=(self.px(4), 0))
        else:
            target_box = None
            self.label(inn, t("ob.no_course"), 10, color="bad").pack(anchor="w", pady=(self.px(4), 0))

        tk.Frame(inn, bg=C["card"], height=self.px(34)).pack()
        buttons = tk.Frame(inn, bg=C["card"])
        buttons.pack(fill="x")

        def selected_course():
            return courses[target_box.current()]["id"] if target_box is not None else None

        def go():
            if target_box is None:
                return
            self.app.choose_language(natives[native_box.current()], selected_course())
            self.rebuild()

        def change_native(_):
            self.show("onboarding", cancelable, natives[native_box.current()], selected_course())

        def cancel():
            self.show("settings")

        go_btn = self.button(buttons, t("ob.go"), go, size=12)
        go_btn.pack(side="left")
        if target_box is None:
            go_btn.disable()
            go_btn.set_style(C["border"], C["muted"])
        if cancelable:
            self.button(buttons, t("ob.cancel"), cancel, "ghost").pack(side="left", padx=self.px(12))
        native_box.bind("<<ComboboxSelected>>", change_native)
        self.key_handler = lambda e: e.keysym in ("Return", "KP_Enter") and go()

    # ---------- pages: overview ----------
    def _page_overview(self, body):
        tr = self.trainer
        s = tr.stats()
        self.header(body, t("ov.title"), t("ov.greet_today", n=s["today"]) if s["today"] else None)

        stats = tk.Frame(body, bg=C["bg"])
        stats.pack(fill="x")
        tiles = [
            (t("fmt.of", a=s["lessons_done"], b=s["lessons_total"]), t("ov.tile_lessons"), t("ov.tile_lessons_sub"), None),
            (f"{s['mastered']}", t("ov.tile_mastered"), t("ov.tile_mastered_sub", n=s["total"]), None),
            (f"{s['due']}", t("ov.tile_due"), t("ov.tile_due_sub"), lambda: self.show("review")),
            (f"{s['streak']}", t("ov.tile_streak"), t("ov.tile_streak_sub", p=s["accuracy"]), None),
        ]
        for i, (value, title, sub, cmd) in enumerate(tiles):
            o, inn = self.card(stats, pad=18)
            o.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else self.px(12), 0))
            stats.columnconfigure(i, weight=1, uniform="tile")
            self.label(inn, value, 22, "bold", color="accent" if i == 0 else "text").pack(anchor="w")
            self.label(inn, title, 10, "bold").pack(anchor="w")
            self.label(inn, sub, 9, color="muted").pack(anchor="w")
            if cmd:
                self.clickable(o, cmd)

        row = tk.Frame(body, bg=C["bg"])
        row.pack(fill="x", pady=(self.px(14), 0))
        row.columnconfigure(0, weight=3, uniform="row")
        row.columnconfigure(1, weight=2, uniform="row")

        o, inn = self.card(row)
        o.grid(row=0, column=0, sticky="nsew", padx=(0, self.px(12)))
        lesson = tr.next_lesson()
        if lesson:
            self.label(inn, t("ov.next_eyebrow", n=lesson.number), 8, "bold", color="muted").pack(anchor="w")
            title_row = tk.Frame(inn, bg=C["card"])
            title_row.pack(anchor="w", pady=(self.px(4), 0))
            self.label(title_row, lesson.title, 15, "bold").pack(side="left")
            self.kind_pill(title_row, lesson).pack(side="left", padx=self.px(10))
            self.label(inn, t("ov.unit_line", n=lesson.unit.number, title=lesson.unit.title), 9,
                       color="muted").pack(anchor="w", pady=(0, self.px(8)))
            if lesson.is_vocab:
                self.level_bar(inn, tr.lesson_levels(lesson)).pack(fill="x")
                text = t("ov.next_vocab", n=lesson.size)
            else:
                text = t("ov.next_grammar", n=lesson.size)
            self.label(inn, text, 9, color="muted", wraplength=self.px(380)).pack(
                anchor="w", pady=(self.px(6), self.px(12)))
            self.button(inn, t("ov.open_lesson"), lambda: self.show("lesson", lesson)).pack(anchor="w")
        else:
            self.label(inn, t("ov.course_label"), 8, "bold", color="muted").pack(anchor="w")
            self.label(inn, t("ov.course_done", level=tr.level_name), 15, "bold").pack(anchor="w", pady=self.px(4))
            self.label(inn, t("ov.course_done_sub"), 10, color="muted", wraplength=self.px(380)).pack(anchor="w")

        o, inn = self.card(row)
        o.grid(row=0, column=1, sticky="nsew")
        self.label(inn, t("ov.daily_label"), 8, "bold", color="muted").pack(anchor="w")
        if not tr.known_entries():
            self.label(inn, t("ov.daily_locked"), 15, "bold").pack(anchor="w", pady=(self.px(4), self.px(8)))
            self.label(inn, t("ov.daily_locked_sub"), 9, color="muted", wraplength=self.px(260)).pack(anchor="w")
        else:
            d = tr.daily_state()
            if d.get("runs"):
                head, sub = t("ov.daily_done", p=d["best"]), t("ov.daily_done_sub")
            else:
                head, sub = t("ov.daily_waiting", n=len(d["words"])), t("ov.daily_waiting_sub")
            self.label(inn, head, 15, "bold").pack(anchor="w", pady=(self.px(4), self.px(8)))
            self.label(inn, sub, 9, color="muted", wraplength=self.px(260)).pack(anchor="w", pady=(0, self.px(12)))
            self.button(inn, t("ov.daily_go"), lambda: self.show("daily")).pack(anchor="w", side="bottom")

        row2 = tk.Frame(body, bg=C["bg"])
        row2.pack(fill="both", expand=True, pady=(self.px(14), 0))
        row2.columnconfigure(0, weight=3, uniform="row")
        row2.columnconfigure(1, weight=2, uniform="row")
        row2.rowconfigure(0, weight=1)

        o, inn = self.card(row2)
        o.grid(row=0, column=0, sticky="nsew", padx=(0, self.px(12)))
        self.label(inn, t("ov.chart"), 8, "bold", color="muted").pack(anchor="w")
        self._chart(inn, s["days"]).pack(fill="both", expand=True, pady=(self.px(8), 0))

        o, inn = self.card(row2)
        o.grid(row=0, column=1, sticky="nsew")
        self.label(inn, t("ov.vocab"), 8, "bold", color="muted").pack(anchor="w")
        self.label(inn, t("ov.vocab_seen", s=s["seen"], t=s["total"]), 13, "bold").pack(
            anchor="w", pady=(self.px(2), self.px(10)))
        self.level_bar(inn, s["levels"], height=14).pack(fill="x", pady=(0, self.px(12)))
        self.legend(inn, s["levels"]).pack(anchor="w")

    def _chart(self, parent, days):
        cv = tk.Canvas(parent, height=self.px(130), width=self.px(40), bg=C["card"], highlightthickness=0)
        today = dt.date.today()
        weekdays = tl("weekdays")

        def draw(_=None):
            cv.delete("all")
            w, h = cv.winfo_width(), cv.winfo_height()
            if w < 20 or h < 40:
                return
            label_h, top = self.px(20), self.px(18)
            base = h - label_h
            peak = max([r + x for _, r, x in days] + [1])
            slot = w / len(days)
            bw = min(slot * 0.6, self.px(26))
            for i, (day, right, wrong) in enumerate(days):
                x = i * slot + (slot - bw) / 2
                hr = (base - top) * right / peak
                hw = (base - top) * wrong / peak
                if right + wrong == 0:
                    cv.create_rectangle(x, base - 2, x + bw, base, fill=C["border"], width=0)
                else:
                    if right:
                        cv.create_rectangle(x, base - hr, x + bw, base, fill=C["good"], width=0)
                    if wrong:
                        cv.create_rectangle(x, base - hr - hw, x + bw, base - hr, fill=C["bad_soft"], width=0)
                    cv.create_text(x + bw / 2, base - hr - hw - self.px(8), text=str(right + wrong),
                                   font=font(8), fill=C["muted"])
                d = dt.date.fromisoformat(day)
                cv.create_text(x + bw / 2, h - label_h / 2, font=font(8),
                               text=t("today") if d == today else weekdays[d.weekday()],
                               fill=C["text"] if d == today else C["muted"])

        cv.bind("<Configure>", draw)
        return cv

    # ---------- pages: course ----------
    def _page_course(self, body):
        tr = self.trainer
        nxt = tr.next_lesson()
        done = sum(1 for l in tr.lessons if tr.is_done(l))
        sub = t("course.sub", variant=tr.variant, done=done, total=len(tr.lessons))
        if tr.coverage:
            sub = t("fmt.note", text=sub, note=tr.coverage)
        self.header(body, t("course.title", level=tr.level_name), sub)
        outer, inner = self.scrollable(body)
        outer.pack(fill="both", expand=True)

        target = None
        for unit in tr.units:
            u_done = sum(1 for l in unit.lessons if tr.is_done(l))
            head = tk.Frame(inner, bg=C["bg"])
            head.pack(fill="x", padx=(0, self.px(8)),
                      pady=(self.px(4) if unit.number == 1 else self.px(20), self.px(8)))
            head.columnconfigure(0, weight=1)
            self.label(head, t("course.part", n=unit.number), 8, "bold", color="red").grid(row=0, column=0, sticky="w")
            self.label(head, unit.title, 14, "bold").grid(row=1, column=0, sticky="w")
            self.label(head, unit.subtitle, 9, color="muted").grid(row=2, column=0, sticky="w")
            self.label(head, t("fmt.of", a=u_done, b=len(unit.lessons)), 10, "bold",
                       color="accent" if u_done == len(unit.lessons) else "muted").grid(
                row=0, column=1, rowspan=3, sticky="e")
            for lesson in unit.lessons:
                row = self._lesson_row(inner, lesson, lesson is nxt)
                if lesson is nxt:
                    target = row

        if target is not None:
            cv = self._scroll_canvas

            def scroll_to_next():
                inner.update_idletasks()
                height = inner.winfo_height()
                if height > 0:
                    cv.yview_moveto(max(0.0, (target.winfo_y() - self.px(140)) / height))

            self.later(30, scroll_to_next)

    def _lesson_row(self, parent, lesson, is_next):
        tr = self.trainer
        rec = tr.lesson_record(lesson)
        o, inn = self.card(parent, pad=14)
        o.pack(fill="x", pady=(0, self.px(8)), padx=(0, self.px(8)))
        if is_next:
            o.config(highlightbackground=C["accent"], highlightthickness=2)
        inn.columnconfigure(1, weight=1)
        inn.columnconfigure(3, minsize=self.px(170))

        done = rec is not None
        tk.Label(inn, text=t("mark.done") if done else str(lesson.number), font=font(11, "bold"), width=3,
                 bg=C["accent"] if done else C["accent_soft"], fg=C["on_accent"] if done else C["accent"],
                 pady=self.px(6)).grid(row=0, column=0, rowspan=2, padx=(0, self.px(16)))
        self.label(inn, lesson.title, 12, "bold").grid(row=0, column=1, sticky="w")
        size = t("row.words", n=lesson.size) if lesson.is_vocab else t("row.exercises", n=lesson.size)
        if lesson.multi:
            size = i18n.sep(size, t("row.sections", n=len(lesson.sections)))
        if done:
            status = t("row.best", p=rec["best"], r=rec["runs"])
        elif is_next:
            status = t("row.next")
        else:
            status = t("row.not_done")
        self.label(inn, i18n.sep(size, status), 9, color="accent" if is_next else "muted").grid(
            row=1, column=1, sticky="w")
        self.kind_pill(inn, lesson).grid(row=0, column=2, rowspan=2, padx=self.px(12))
        if lesson.is_vocab:
            self.level_bar(inn, tr.lesson_levels(lesson), width=150).grid(row=0, column=3, rowspan=2, padx=self.px(8))
        if is_next:
            b = self.button(inn, t("row.start"), lambda: self.show("lesson", lesson))
        else:
            b = self.button(inn, t("row.repeat") if done else t("row.open"), lambda: self.show("lesson", lesson),
                            "secondary")
        b.grid(row=0, column=4, rowspan=2, padx=(self.px(8), 0))
        self.clickable(o, lambda: self.show("lesson", lesson))
        return o

    def _lesson_status_line(self, lesson) -> str:
        rec = self.trainer.lesson_record(lesson)
        if not rec:
            return t("lesson.status_none")
        return t("lesson.status", p=rec["best"], r=rec["runs"])

    def _lesson_nav(self, parent, lesson):
        """Previous / next lesson links."""
        lessons = self.trainer.lessons
        i = lessons.index(lesson)
        nav = tk.Frame(parent, bg=C["bg"])
        if i > 0:
            prev = lessons[i - 1]
            self.button(nav, t("fmt.back", text=prev.title), lambda: self.show("lesson", prev), "ghost").pack(side="left")
        if i + 1 < len(lessons):
            nxt = lessons[i + 1]
            self.button(nav, t("fmt.forward", text=nxt.title), lambda: self.show("lesson", nxt), "ghost").pack(side="right")
        return nav

    def _section_name(self, lesson, sec) -> str:
        return sec.title or t("section.title", n=sec.number, t=len(lesson.sections))

    def _section_head(self, parent, lesson, sec):
        """Heading of one section of a multi-section lesson, with its own practise button."""
        tr = self.trainer
        done = tr.section_record(lesson, sec) is not None
        row = tk.Frame(parent, bg=parent["bg"])
        head = t("fmt.section", n=sec.number, title=self._section_name(lesson, sec))
        self.label(row, t("fmt.done", text=head) if done else head, 12, "bold",
                   color="accent").pack(side="left")
        self.button(row, t("section.repeat") if done else t("section.practise"),
                    lambda: self.start(tr.lesson_session(lesson, sec), ("lesson", lesson)), "secondary", 9).pack(
            side="right")
        return row

    def _page_lesson(self, body, lesson):
        if lesson.is_vocab:
            self._vocab_lesson(body, lesson)
        else:
            self._grammar_lesson(body, lesson)

    def _vocab_lesson(self, body, lesson):
        tr = self.trainer
        done = tr.is_done(lesson)
        self.header(body, lesson.title, t("vocab.sub", n=lesson.size),
                    back=(t("lesson.back"), lambda: self.show("course")), eyebrow=self.lesson_eyebrow(lesson))

        o, inn = self.card(body)
        o.pack(fill="x")
        inn.columnconfigure(0, weight=1)
        steps = tk.Frame(inn, bg=C["card"])
        steps.grid(row=0, column=0, sticky="w")
        for n, (name, text) in enumerate(((t("round.recognize"), t("vocab.step1_text", lang=tr.language)),
                                          (t("round.recall"), t("vocab.step2_text", native=tr.native, lang=tr.language)),
                                          (t("round.write"), t("vocab.step3_text", lang=tr.language))), start=1):
            r = tk.Frame(steps, bg=C["card"])
            r.pack(anchor="w", pady=self.px(2))
            tk.Label(r, text=str(n), bg=C["accent_soft"], fg=C["accent"], font=font(9, "bold"),
                     width=2).pack(side="left")
            self.label(r, f"  {name}", 10, "bold").pack(side="left")
            self.label(r, t("fmt.step", text=text), 10, color="muted").pack(side="left")
        btns = tk.Frame(inn, bg=C["card"])
        btns.grid(row=0, column=1, sticky="e")
        self.button(btns, t("vocab.repeat") if done else t("vocab.start"),
                    lambda: self.start(tr.lesson_session(lesson), ("lesson", lesson))).pack(fill="x")
        self.button(btns, t("vocab.cards"), lambda: self.show("cards", lesson), "secondary").pack(
            fill="x", pady=(self.px(8), 0))
        self.label(inn, self._lesson_status_line(lesson), 9, color="muted").grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(self.px(12), 0))
        if lesson.multi:
            self.label(inn, t("section.hint"), 9, color="muted").grid(row=2, column=0, columnspan=2, sticky="w")

        for note in lesson.notes:
            self.tip(body, note).pack(fill="x", pady=(self.px(10), 0))

        tk.Frame(body, bg=C["bg"], height=self.px(12)).pack()
        self._lesson_nav(body, lesson).pack(side="bottom", fill="x", pady=(self.px(8), 0))
        outer, inner = self.scrollable(body)
        outer.pack(fill="both", expand=True)
        o, inn = self.card(inner, pad=16)
        o.pack(fill="x", padx=(0, self.px(8)))
        inn.columnconfigure(0, weight=1, uniform="w")
        inn.columnconfigure(1, weight=1, uniform="w")
        for col, text in enumerate((tr.language, tr.native, t("table.status"))):
            self.label(inn, text.upper(), 8, "bold", color="muted").grid(
                row=0, column=col, sticky="w", pady=(0, self.px(6)))
        i = 1
        pad = self.px(4)
        for sec in lesson.sections:
            if lesson.multi:
                self._section_head(inn, lesson, sec).grid(row=i, column=0, columnspan=3, sticky="ew",
                                                          pady=(self.px(16 if i > 1 else 2), self.px(4)))
                i += 1
            for e in sec.words:
                self.label(inn, e["word"], 11, "bold").grid(row=i, column=0, sticky="w", pady=pad)
                self.label(inn, e["translation"], 11).grid(row=i, column=1, sticky="w", pady=pad)
                self.level_pill(inn, tr.level(e["word"])).grid(row=i, column=2, sticky="w", pady=pad)
                i += 1

    def _grammar_lesson(self, body, lesson):
        tr = self.trainer
        done = tr.is_done(lesson)
        n_choice = sum(1 for ex in lesson.exercises if ex["opts"])
        self.header(body, lesson.title, t("grammar.sub", n=lesson.size),
                    back=(t("lesson.back"), lambda: self.show("course")), eyebrow=self.lesson_eyebrow(lesson))

        o, inn = self.card(body)
        o.pack(fill="x")
        inn.columnconfigure(0, weight=1)
        self.label(inn, t("grammar.intro", a=n_choice, b=lesson.size - n_choice), 10,
                   wraplength=self.px(520)).grid(row=0, column=0, sticky="w")
        self.label(inn, self._lesson_status_line(lesson), 9, color="muted").grid(
            row=1, column=0, sticky="w", pady=(self.px(6), 0))
        if lesson.multi:
            self.label(inn, t("section.hint"), 9, color="muted").grid(row=2, column=0, sticky="w")
        self.button(inn, t("grammar.repeat") if done else t("grammar.start"),
                    lambda: self.start(tr.lesson_session(lesson), ("lesson", lesson))).grid(
            row=0, column=1, rowspan=2, sticky="e")

        tk.Frame(body, bg=C["bg"], height=self.px(12)).pack()
        self._lesson_nav(body, lesson).pack(side="bottom", fill="x", pady=(self.px(8), 0))
        outer, inner = self.scrollable(body)
        outer.pack(fill="both", expand=True)
        o, inn = self.card(inner, pad=24)
        o.pack(fill="x", padx=(0, self.px(8)))
        self.label(inn, t("grammar.explanation"), 8, "bold", color="muted").pack(anchor="w", pady=(0, self.px(6)))
        if not lesson.multi:
            for block in lesson.explanation:
                self._render_block(inn, block)
            return
        for sec in lesson.sections:
            self._section_head(inn, lesson, sec).pack(fill="x", pady=(self.px(18 if sec.number > 1 else 4), 0))
            for block in sec.explanation:
                self._render_block(inn, block)

    def _render_block(self, parent, block):
        kind, value = next(iter(block.items()))
        gap = self.px(10)
        if kind == "h":
            self.label(parent, value, 12, "bold").pack(anchor="w", pady=(gap * 1.5, 0))
        elif kind == "p":
            lbl = self.label(parent, value, 11)
            lbl.pack(anchor="w", fill="x", pady=(gap, 0))
            self._autowrap(parent, lbl, margin=10)
        elif kind == "tip":
            self.tip(parent, value).pack(fill="x", pady=(gap, 0))
        elif kind == "table":
            grid = tk.Frame(parent, bg=C["border"])
            grid.pack(anchor="w", pady=(gap, 0))
            for r, row in enumerate(value):
                for c, cell in enumerate(row):
                    head = r == 0
                    bg = C["accent_soft"] if head else (C["cell"] if c == 0 else C["card"])
                    tk.Label(grid, text=cell, bg=bg, fg=C["accent"] if head else C["text"],
                             font=font(10, "bold" if head or c == 0 else "normal"), anchor="w",
                             justify="left", padx=self.px(12), pady=self.px(5)).grid(
                        row=r, column=c, sticky="nsew", padx=(0, 1), pady=(0, 1))
        elif kind == "ex":
            grid = tk.Frame(parent, bg=parent["bg"])
            grid.pack(anchor="w", fill="x", pady=(gap, 0))
            for r, (pt, de) in enumerate(value):
                self.label(grid, pt, 11, "bold", color="accent").grid(row=r, column=0, sticky="w",
                                                                    padx=(self.px(4), self.px(20)), pady=self.px(2))
                self.label(grid, de, 10, color="muted").grid(row=r, column=1, sticky="w")

    # ---------- pages: flashcards ----------
    def _page_cards(self, body, lesson):
        entries = lesson.words
        state = SimpleNamespace(i=0, flipped=False)
        self.header(body, t("cards.title", title=lesson.title), t("cards.sub"),
                    back=(lesson.title, lambda: self.show("lesson", lesson)))
        counter = self.label(body, "", 10, "bold", color="muted")
        counter.pack()

        o, inn = self.card(body)
        o.pack(fill="both", expand=True, pady=self.px(12), padx=self.px(60))
        center = tk.Frame(inn, bg=C["card"])
        center.pack(expand=True)
        word = self.label(center, "", 28, "bold", justify="center")
        word.pack(pady=(0, self.px(14)))
        trans = self.label(center, "", 18, color="accent", justify="center")
        trans.pack()
        hint = self.label(center, "", 9, color="muted")
        hint.pack(pady=(self.px(18), 0))
        inn.bind("<Configure>", lambda e: (word.config(wraplength=e.width - 40),
                                           trans.config(wraplength=e.width - 40)))

        nav = tk.Frame(body, bg=C["bg"])
        nav.pack(fill="x", padx=self.px(60))
        self.button(nav, t("cards.back"), lambda: step(-1), "secondary").pack(side="left")
        next_b = self.button(nav, t("cards.next"), lambda: step(1))
        next_b.pack(side="right")
        self.button(nav, t("cards.flip"), lambda: flip(), "secondary").pack(side="right", padx=self.px(10))

        def render():
            e = entries[state.i]
            text = t("cards.counter", i=state.i + 1, n=len(entries))
            if lesson.multi:
                text = i18n.sep(text, self._section_name(lesson, lesson.sections[e["section"] - 1]))
            counter.config(text=text)
            word.config(text=e["word"])
            trans.config(text=e["translation"] if state.flipped else " ")
            hint.config(text="" if state.flipped else t("cards.hint"))
            next_b.config(text=t("cards.start") if state.i == len(entries) - 1 else t("cards.next"))

        def flip():
            state.flipped = not state.flipped
            render()

        def step(d):
            if state.i + d >= len(entries):
                self.start(self.trainer.lesson_session(lesson), ("lesson", lesson))
                return
            state.i = max(0, state.i + d)
            state.flipped = False
            render()

        def key(e):
            if e.keysym == "space":
                flip()
            elif e.keysym in ("Right", "Return"):
                step(1)
            elif e.keysym == "Left":
                step(-1)

        self.clickable(o, flip)
        self.key_handler = key
        render()

    # ---------- pages: practice ----------
    def start(self, session, back):
        if session.total:
            self.show("practice", session, back)

    def start_review(self):
        self.start(self.trainer.practice_session(self.trainer.due_entries(REVIEW_BATCH), t("rev.session")),
                   ("review",))

    def _page_practice(self, body, session, back):
        top = tk.Frame(body, bg=C["bg"])
        top.pack(fill="x")
        self.label(top, session.title, 14, "bold").pack(side="left")
        self.button(top, t("pr.quit"), lambda: self.show(*back), "ghost").pack(side="right")
        count = self.label(top, "", 10, "bold", color="muted")
        count.pack(side="right", padx=self.px(14))
        round_lbl = self.label(top, "", 10, "bold", color="accent")
        round_lbl.pack(side="right", padx=self.px(14))
        bar = self.progress_bar(body)
        bar.pack(fill="x", pady=(self.px(10), self.px(16)))

        o, inn = self.card(body, pad=28)
        o.pack(fill="both", expand=True)
        ask = self.label(inn, "", 9, "bold", color="muted", justify="center")
        ask.pack(pady=(self.px(10), 0))
        shown = self.label(inn, "", 26, "bold", justify="center")
        shown.pack(pady=(self.px(6), 0))
        hint = self.label(inn, "", 11, color="muted", justify="center")
        hint.pack(pady=(self.px(4), self.px(20)))
        answers = tk.Frame(inn, bg=C["card"])
        answers.pack(fill="x", padx=self.px(30))
        feedback = self.label(inn, "", 12, "bold", justify="center")
        feedback.pack(pady=(self.px(14), 0))
        bottom = tk.Frame(inn, bg=C["card"])
        bottom.pack(side="bottom", fill="x")
        next_b = self.button(bottom, t("pr.next"), lambda: self._next_card())
        inn.bind("<Configure>", lambda e: [w.config(wraplength=e.width - 40) for w in (shown, hint, feedback)])

        self.pr = SimpleNamespace(session=session, back=back, count=count, round=round_lbl, bar=bar,
                                  ask=ask, shown=shown, hint=hint, answers=answers, feedback=feedback,
                                  next_b=next_b, card=None, answered=False, auto=None, options=[],
                                  entry=None, type_buttons=None)
        self.key_handler = self._practice_key
        self._next_card()

    def _update_progress(self):
        pr = self.pr
        done, total = pr.session.done, pr.session.total
        pr.count.config(text=t("fmt.of", a=done, b=total))
        pr.round.config(text=pr.session.round_label)
        pr.bar.set_fraction(done / total if total else 0)

    def _next_card(self):
        pr = self.pr
        if pr.auto:
            self.root.after_cancel(pr.auto)
            pr.auto = None
        card = pr.session.next_card()
        if card is None:
            self.show("summary", pr.session, pr.back)
            return
        pr.card, pr.answered, pr.options, pr.entry, pr.type_buttons = card, False, [], None, None
        for w in pr.answers.winfo_children():
            w.destroy()
        pr.feedback.config(text="")
        pr.next_b.pack_forget()
        self._update_progress()

        ask = t("fmt.retry", ask=card.ask, again=t("pr.again")) if card.retry else card.ask
        pr.ask.config(text=ask.upper())
        n = len(card.shown)
        pr.shown.config(text=card.shown, font=font(26 if n <= 24 else 20 if n <= 48 else 16, "bold"))
        pr.hint.config(text=card.hint)
        if card.kind == "choice":
            self._build_choices(card)
        else:
            self._build_typing(card)

    def _build_choices(self, card):
        pr = self.pr
        for i, option in enumerate(card.options):
            b = FlatButton(pr.answers, t("fmt.numbered", n=i + 1, text=option), lambda i=i: self._choose(i),
                           C["bg"], C["text"], C["accent_soft"], font=font(12), anchor="w",
                           justify="left", padx=self.px(16), pady=self.px(12),
                           wraplength=self.px(300), highlightthickness=1,
                           highlightbackground=C["border"])
            b.grid(row=i // 2, column=i % 2, sticky="nsew", padx=self.px(6), pady=self.px(6))
            pr.options.append(b)
        pr.answers.columnconfigure(0, weight=1, uniform="opt")
        pr.answers.columnconfigure(1, weight=1, uniform="opt")
        self.label(pr.answers, t("pr.keys", n=len(card.options)), 8, color="muted").grid(
            row=10, column=0, columnspan=2, pady=(self.px(8), 0))

    def _build_typing(self, card):
        pr = self.pr
        wrap = tk.Frame(pr.answers, bg=C["card"])
        wrap.pack(padx=self.px(60), fill="x")
        entry = tk.Entry(wrap, font=font(16), relief="flat", bg=C["bg"], fg=C["text"],
                         insertbackground=C["text"], highlightthickness=2,
                         highlightbackground=C["border"], highlightcolor=C["accent"],
                         disabledbackground=C["bg"], disabledforeground=C["text"], justify="center")
        entry.pack(fill="x", ipady=self.px(8))
        pr.entry = entry

        if card.accents and self.trainer.accents:
            accents = tk.Frame(wrap, bg=C["card"])
            accents.pack(pady=(self.px(8), 0))
            for ch in self.trainer.accents:
                FlatButton(accents, ch, lambda ch=ch: (entry.insert("insert", ch), entry.focus_set()),
                           C["bg"], C["text"], C["accent_soft"], font=font(11), width=2,
                           pady=self.px(2)).pack(side="left", padx=self.px(2))

        btns = tk.Frame(wrap, bg=C["card"])
        btns.pack(pady=(self.px(14), 0))
        self.button(btns, t("pr.check"), self._check_typed).pack(side="left")
        self.button(btns, t("pr.dont_know"), self._dont_know, "ghost").pack(side="left", padx=self.px(10))
        pr.type_buttons = btns
        entry.focus_set()

    def _practice_key(self, e):
        pr = self.pr
        if pr.answered:
            if e.keysym in ("Return", "KP_Enter", "space"):
                self._next_card()
            return
        if pr.card.kind == "choice":
            if e.char and e.char.isdigit() and 1 <= int(e.char) <= len(pr.options):
                self._choose(int(e.char) - 1)
        elif e.keysym in ("Return", "KP_Enter"):
            self._check_typed()

    def _choose(self, idx):
        pr = self.pr
        if pr.answered:
            return
        card = pr.card
        for i, b in enumerate(pr.options):
            b.disable()
            if i == card.correct:
                b.set_style(C["good"], "white")
            elif i == idx:
                b.set_style(C["bad"], "white")
        self._answered(idx == card.correct, "")

    def _check_typed(self):
        pr = self.pr
        if pr.answered or not pr.entry.get().strip():
            return
        card = pr.card
        result = check_typed(pr.entry.get(), card.expected, card.strict)
        if result in ("accent", "close") and not card.strict:
            # vocabulary: a missing accent or a small typo is almost right; show the exact spelling
            self._answered(True, t("pr.close", s=quote(card.expected)), head=t("pr.almost"))
        elif result == "accent":
            # grammar: the accents are part of the answer
            self._answered(False, t("pr.accent"))
        else:
            self._answered(result == "exact", "")

    def _dont_know(self):
        if not self.pr.answered:
            self._answered(False, "")

    def _answered(self, ok, note, head=None):
        pr = self.pr
        card = pr.card
        pr.answered = True
        if pr.entry is not None:
            pr.entry.config(state="disabled", highlightbackground=C["good"] if ok else C["bad"])
            pr.type_buttons.destroy()
        pr.session.answer(card, ok)
        self.app.on_gui_answer()
        grammar = card.word is None
        if ok:
            text = head or t("pr.right")
            if note:
                text += f"\n{note}"
            elif grammar:
                text += f"\n{card.solution}"
            pr.feedback.config(text=text, fg=C["good"])
        else:
            head = t("fmt.wrong", text=note) if note else t("pr.wrong")
            pr.feedback.config(text=f"{head}\n{card.solution}", fg=C["bad"])
        self._update_progress()
        pr.next_b.pack(side="right")
        if ok and not note:
            pr.auto = self.later(1600 if grammar else 900, self._next_card)

    # ---------- pages: summary ----------
    def _page_summary(self, body, session, back):
        tr = self.trainer
        n = len(session.first_try)
        pct = session.score
        msg = t("sum.great") if pct >= 90 else t("sum.good") if pct >= 60 else t("sum.low")
        title = t("sum.lesson") if session.lesson else t("sum.daily") if session.daily else t("sum.done")
        self.header(body, title, t("sum.sub", title=session.title, r=session.first_try_right, n=n))

        o, inn = self.card(body, pad=24)
        o.pack(fill="x")
        self.label(inn, t("fmt.percent", p=pct), 30, "bold", color="accent").pack(anchor="w")
        self.label(inn, msg, 11).pack(anchor="w", pady=(self.px(2), self.px(16)))
        btns = tk.Frame(inn, bg=C["card"])
        btns.pack(anchor="w")
        mistakes = session.mistake_solutions()
        primary_used = False

        def add(text, cmd, kind):
            self.button(btns, text, cmd, kind).pack(side="left", padx=(0, self.px(10)))

        lesson, sec = session.lesson, session.section
        next_sec = None
        if lesson and sec and lesson.multi and sec.number < len(lesson.sections):
            next_sec = lesson.sections[sec.number]
        if next_sec:
            add(t("sum.next_section", title=self._section_name(lesson, next_sec)),
                lambda: self.start(tr.lesson_session(lesson, next_sec), back), "primary")
            primary_used = True
            add(t("sum.repeat"), lambda: self.start(session.again(), back), "secondary")
        elif session.lesson:
            nxt = tr.lesson_after(session.lesson)
            if nxt:
                add(t("sum.next", title=nxt.title), lambda: self.show("lesson", nxt), "primary")
                primary_used = True
            add(t("sum.repeat"), lambda: self.start(session.again(), back), "secondary")
        elif session.daily:
            add(t("sum.again"), lambda: self.start(session.again(), back), "secondary")
        if mistakes:
            add(t("sum.mistakes_btn"), lambda: self.start(session.again(only_mistakes=True), back),
                "secondary" if primary_used else "primary")
            primary_used = True
        if not session.lesson and not session.daily:
            add(t("sum.all_again"), lambda: self.start(session.again(), back), "secondary")
        add(t("sum.finish"), lambda: self.show(*back), "ghost")
        self.key_handler = lambda e: e.keysym in ("Return", "KP_Enter") and self.show(*back)

        if mistakes:
            tk.Frame(body, bg=C["bg"], height=self.px(14)).pack()
            outer, inner = self.scrollable(body)
            outer.pack(fill="both", expand=True)
            o, inn = self.card(inner)
            o.pack(fill="x", padx=(0, self.px(8)))
            self.label(inn, t("sum.mistakes"), 8, "bold", color="muted").pack(anchor="w", pady=(0, self.px(6)))
            for text in mistakes:
                first, _, second = text.partition("\n")
                row = tk.Frame(inn, bg=C["card"])
                row.pack(anchor="w", fill="x", pady=self.px(3))
                self.label(row, first, 11, "bold").pack(side="left")
                if second:
                    self.label(row, f"   {second}", 10, color="muted").pack(side="left")

    # ---------- pages: daily challenge ----------
    def _page_daily(self, body, status=""):
        tr = self.trainer
        today = dt.date.today()
        self.header(body, t("daily.title"), t("daily.sub", n=DAILY_SIZE))
        known = len(tr.known_entries())
        if not known:
            o, inn = self.card(body)
            o.pack(fill="x")
            self.label(inn, t("daily.none"), 15, "bold").pack(anchor="w")
            self.label(inn, t("daily.none_sub"), 10, color="muted", wraplength=self.px(620)).pack(
                anchor="w", pady=(self.px(4), self.px(14)))
            self.button(inn, t("daily.to_course"), lambda: self.show("course")).pack(anchor="w")
            return

        d = tr.daily_state()
        n = len(d["words"])
        o, inn = self.card(body, pad=24)
        o.pack(fill="x")
        inn.columnconfigure(0, weight=1)
        date = t("date", d=today.day, month=tl("months")[today.month - 1])
        self.label(inn, t("daily.today", date=date.upper()), 8, "bold", color="red").grid(row=0, column=0, sticky="w")
        self.label(inn, t("daily.words", n=n), 24, "bold").grid(row=1, column=0, sticky="w")
        if d.get("runs"):
            line, color = t("daily.done", p=d["best"], r=d["runs"]), "accent"
        else:
            line, color = t("daily.not_played"), "muted"
        self.label(inn, line, 10, "bold", color=color).grid(row=2, column=0, sticky="w", pady=(self.px(2), 0))
        if known < DAILY_SIZE:
            self.label(inn, t("daily.few", k=known, n=n), 9, color="muted").grid(
                row=3, column=0, sticky="w", pady=(self.px(6), 0))
        btns = tk.Frame(inn, bg=C["card"])
        btns.grid(row=0, column=1, rowspan=4, sticky="e")
        self.button(btns, t("daily.again") if d.get("runs") else t("daily.start"),
                    lambda: self.start(tr.daily_session(), ("daily",))).pack(fill="x")

        def redraw():
            tr.redraw_daily()
            if known > DAILY_SIZE:
                msg = t("daily.redrawn", n=min(DAILY_SIZE, known - n))
            else:
                msg = t("daily.redrawn_few")
            self.show("daily", msg)

        self.button(btns, t("daily.redraw"), redraw, "secondary").pack(fill="x", pady=(self.px(8), 0))
        if status:
            self.label(body, status, 10, "bold", color="accent").pack(anchor="w", pady=(self.px(10), 0))

        tk.Frame(body, bg=C["bg"], height=self.px(14)).pack()
        o, inn = self.card(body)
        o.pack(fill="x")
        self.label(inn, t("daily.how"), 8, "bold", color="muted").pack(anchor="w", pady=(0, self.px(6)))
        for key in ("daily.how1", "daily.how2", "daily.how3", "daily.how4"):
            row = tk.Frame(inn, bg=C["card"])
            row.pack(anchor="w", fill="x", pady=self.px(2))
            self.label(row, "•", 10, "bold", color="accent").pack(side="left", anchor="n")
            lbl = self.label(row, t(key, n=DAILY_SIZE), 10)
            lbl.pack(side="left", padx=(self.px(8), 0), fill="x", expand=True)
            self._autowrap(row, lbl, margin=30)

    # ---------- pages: review ----------
    def _page_review(self, body):
        tr = self.trainer
        self.header(body, t("rev.title"), t("rev.sub"))
        due = tr.due_entries()
        hard = tr.hard_entries(10)
        seen = tr.seen_entries()

        def block(title, text, button=None, command=None, kind="primary"):
            o, inn = self.card(body)
            o.pack(fill="x", pady=(0, self.px(12)))
            inn.columnconfigure(0, weight=1)
            self.label(inn, title, 13, "bold").grid(row=0, column=0, sticky="w")
            self.label(inn, text, 9, color="muted", wraplength=self.px(560)).grid(
                row=1, column=0, sticky="w", pady=(self.px(2), 0))
            if button:
                self.button(inn, button, command, kind).grid(row=0, column=1, rowspan=2, padx=(self.px(16), 0))

        if due:
            n = min(len(due), REVIEW_BATCH)
            block(t("rev.due", n=len(due)), t("rev.due_many", n=n) if len(due) > n else t("rev.due_all"),
                  t("rev.start", n=n), self.start_review)
        else:
            nxt = tr.next_due_at()
            block(t("rev.none"), t("rev.next", when=fmt_when(nxt)) if nxt else t("rev.none_sub"))

        if hard:
            words = ", ".join(e["word"] for e in hard[:5]) + (" …" if len(hard) > 5 else "")
            block(t("rev.hard"), t("rev.hard_sub", list=words), t("rev.practise", n=len(hard)),
                  lambda: self.start(tr.practice_session(hard, t("rev.hard")), ("review",)), "secondary")
        if seen:
            mix = random.sample(seen, min(MIX_BATCH, len(seen)))
            block(t("rev.mix"), t("rev.mix_sub", n=len(mix)), t("rev.shuffle"),
                  lambda: self.start(tr.practice_session(mix, t("rev.mix")), ("review",)), "secondary")

    # ---------- pages: dictionary ----------
    def _page_words(self, body):
        tr = self.trainer
        self.header(body, t("words.title"), t("words.sub", n=len(tr.entries)))
        bar = tk.Frame(body, bg=C["bg"])
        bar.pack(fill="x", pady=(0, self.px(12)))

        var = tk.StringVar(value=self.word_filter["text"])
        search = tk.Entry(bar, textvariable=var, font=font(11), relief="flat", bg=C["card"],
                          fg=C["text"], insertbackground=C["text"], highlightthickness=1,
                          highlightbackground=C["border"], highlightcolor=C["accent"], width=26)
        search.pack(side="left", ipady=self.px(6))
        self.label(bar, t("words.search"), 9, color="muted").pack(side="left")

        filters = tk.Frame(bar, bg=C["bg"])
        filters.pack(side="right")
        filter_buttons = {}

        frame = tk.Frame(body, bg=C["card"], highlightthickness=1, highlightbackground=C["border"],
                         highlightcolor=C["border"])
        frame.pack(fill="both", expand=True)
        cols = ("word", "trans", "lesson", "level", "score")
        tree = ttk.Treeview(frame, columns=cols, show="headings", selectmode="browse")
        heads = (tr.language, tr.native, t("words.lesson"), t("table.status"), t("words.score"))
        widths = (210, 210, 170, 75, 105)
        for c, h, w in zip(cols, heads, widths):
            tree.heading(c, text=h, anchor="w")
            tree.column(c, width=self.px(w), minwidth=self.px(60), anchor="w", stretch=True)
        sb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        for lvl, color in ((1, C["learning_text"]), (3, C["good"])):
            tree.tag_configure(f"l{lvl}", foreground=color)

        def fill(*_):
            self.word_filter["text"] = var.get()
            q = var.get().strip().lower()
            want = self.word_filter["level"]
            for b_lvl, b in filter_buttons.items():
                active = b_lvl == want
                b.set_style(C["accent"] if active else C["card"], C["on_accent"] if active else C["muted"],
                            None if active else C["accent_soft"])
            tree.delete(*tree.get_children())
            for e in tr.entries:
                p = tr.progress_of(e["word"])
                lvl = tr.level(e["word"])
                if want is not None and lvl != want:
                    continue
                if q and q not in e["word"].lower() and q not in e["translation"].lower():
                    continue
                lesson = tr.lesson_of(e["word"])
                score = t("fmt.of", a=p["right"], b=p["wrong"]) if p else t("mark.none")
                tree.insert("", "end", values=(e["word"], e["translation"],
                                               t("fmt.lesson", n=lesson.number, title=lesson.title) if lesson else "",
                                               level_name(lvl), score), tags=(f"l{lvl}",))

        def set_level(lvl):
            self.word_filter["level"] = lvl
            fill()

        for lvl in (None, 0, 1, 2, 3):
            text = t("words.all") if lvl is None else level_name(lvl)
            b = FlatButton(filters, text, lambda l=lvl: set_level(l), C["card"], C["muted"],
                           C["accent_soft"], font=font(9, "bold"), padx=self.px(12), pady=self.px(6))
            b.pack(side="left", padx=(self.px(4), 0))
            filter_buttons[lvl] = b

        var.trace_add("write", fill)
        fill()
        search.focus_set()

    # ---------- pages: settings ----------
    def _page_settings(self, body, status=""):
        cfg = self.app.cfg
        tr = self.trainer
        self.header(body, t("set.title"), t("set.sub"))
        outer, page = self.scrollable(body)
        outer.pack(fill="both", expand=True)

        def section(title, sub=None):
            """A settings card. Title and hint sit on the left (`inn.text`), a selection goes on the
            right (`inn.right`), the rest of the card below both."""
            o, inn = self.card(page)
            o.pack(fill="x", pady=(0, self.px(12)), padx=(0, self.px(8)))
            head = tk.Frame(inn, bg=C["card"])
            head.pack(fill="x")
            head.columnconfigure(0, weight=1)
            inn.text = tk.Frame(head, bg=C["card"])
            inn.text.grid(row=0, column=0, sticky="nw")
            inn.right = tk.Frame(head, bg=C["card"])
            inn.right.grid(row=0, column=1, sticky="ne", padx=(self.px(20), 0))
            self.label(inn.text, title, 13, "bold").pack(anchor="w")
            if sub:
                hint = self.label(inn.text, sub, 9, color="muted", anchor="w", justify="left")
                hint.pack(anchor="w", pady=(self.px(2), 0))
                # the hint wraps in the room the selection on the right leaves it
                head.bind("<Configure>", lambda e: hint.config(
                    wraplength=max(120, e.width - inn.right.winfo_reqwidth() - self.px(30))), add="+")
            return inn

        def selection(inn, values, current, on_select):
            """A dropdown on the right of a section's title and hint."""
            box = self.dropdown(inn.right, values, width=32, current=current, on_select=on_select)
            box.master.pack(anchor="e")
            return box

        # 1. app language: menus, buttons and messages (defaults to the system language)
        inn = section(t("set.app_lang"), t("set.app_lang_sub"))
        codes = list(i18n.UI_LANGUAGES)
        current_ui = i18n.language()

        def change_app_language(_):
            code = codes[app_box.current()]
            if code == cfg.get("app_language"):
                return
            self.app.set_app_language(code)
            self.rebuild()
            self.show("settings", t("set.saved"))

        app_box = selection(inn, [i18n.endonym(c) for c in codes],
                            codes.index(current_ui) if current_ui in codes else 0, change_app_language)
        if not cfg.get("app_language"):
            self.label(inn.text, t("set.app_lang_detected"), 9, color="muted").pack(anchor="w", pady=(self.px(4), 0))

        # 2. native language: the course's translations, titles, tips and explanations
        inn = section(t("set.native"), t("set.native_sub"))
        info = next((c for c in self.app.courses() if c["id"] == tr.course_id), {})
        natives = [n for n in info.get("natives", [tr.native_code]) if n != info.get("language")]

        def change_native(_):
            code = natives[native_box.current()]
            if code == tr.native_code:
                return
            self.app.set_native(code)
            self.rebuild()
            self.show("settings", t("set.saved"))

        native_box = selection(inn, [i18n.endonym(n) for n in natives],
                               natives.index(tr.native_code) if tr.native_code in natives else 0, change_native)

        # 3. language to learn (the course), offered for the native language above
        inn = section(t("set.lang"), t("set.lang_note"))
        courses = [c for c in self.app.courses()
                   if tr.native_code in c.get("natives", []) and c.get("language") != tr.native_code]
        ids = [c["id"] for c in courses]

        def change_course(_):
            course_id = ids[course_box.current()]
            if course_id == tr.course_id:
                return
            self.app.choose_language(tr.native_code, course_id)
            self.rebuild()
            self.show("settings", t("set.saved"))

        course_box = selection(inn, [self._course_label(c) for c in courses],
                               ids.index(tr.course_id) if tr.course_id in ids else 0, change_course)

        # appearance: every theme in themes.json (label: set.theme.<name>)
        inn = section(t("set.look"))
        theme_names = list(PALETTES)

        def change_theme(_):
            name = theme_names[theme_box.current()]
            if name != self.theme:
                self.set_theme(name)

        theme_box = selection(inn, [t(f"set.theme.{n}") for n in theme_names],
                              theme_names.index(self.theme) if self.theme in theme_names else 0, change_theme)

        # annoyance level: a slider with seven steps. Changes apply in place (no redraw, no jump to the top).
        inn = section(t("set.annoy"), t("set.annoy_sub"))
        presets = self.app.annoy_presets
        levels = list(presets)
        field_vars = {}   # filled by the notifications section below, updated when the level changes
        title = self.label(inn, "", 12, "bold", color="accent")
        title.pack(anchor="w", pady=(self.px(12), 0))
        desc = self.label(inn, "", 9, color="muted", anchor="w", justify="left")
        desc.pack(anchor="w", fill="x")
        self._autowrap(inn, desc)
        slider = self.level_slider(inn, len(levels))
        slider.pack(fill="x", pady=(self.px(8), 0))
        ends = tk.Frame(inn, bg=C["card"])
        ends.pack(fill="x")
        self.label(ends, t("set.annoy.quiet"), 8, color="muted").pack(side="left")
        self.label(ends, t("set.annoy.loud"), 8, color="muted").pack(side="right")
        # warning for the top level: it pulls you out of everything (shown only while it's selected)
        # what a level means for you: an info for the calm levels, a warning for the top one
        notice_slot = tk.Frame(inn, bg=C["card"])
        notice_slot.pack(fill="x")
        notices = {
            "3h": self.notice(notice_slot, t("set.annoy.calm_info"), "info"),
            "possible": self.notice(notice_slot, t("set.annoy.possible_info"), "info"),
            "fuckoff": self.notice(notice_slot, t("set.annoy.fuckoff_warn"), "warn"),
        }
        notices["random"] = notices["1h"] = notices["3h"]

        def show_level(name):
            title.config(text=t(f"set.annoy.{name or 'custom'}"))
            desc.config(text=t(f"set.annoy.{name or 'custom'}_d"))
            for row in set(notices.values()):
                row.pack_forget()
            if name in notices:
                notices[name].pack(fill="x", pady=(self.px(12), 0))

        def current_index():
            name = self.app.annoy_level()
            if name:
                return levels.index(name)
            # custom values: the knob sits at the level with the nearest interval
            iv = cfg.get("interval_minutes", 60)
            steps = [i for i, n in enumerate(levels) if presets[n]["schedule"] == "interval"]
            return min(steps, key=lambda i: abs(presets[levels[i]]["interval_minutes"] - iv))

        def sync():
            slider.set(current_index())
            show_level(self.app.annoy_level())

        def preview(i):
            show_level(levels[i])

        def apply(i):
            name = levels[i]
            if name == self.app.annoy_level():
                return
            self.app.set_annoy_level(name)
            for key, (v, _, _, factor) in field_vars.items():
                v.set(str(round(cfg.get(key, 0) * factor)))
            show_level(name)
            msg.config(text=t("set.saved"), fg=C["accent"])

        slider.on_move, slider.on_change = preview, apply

        # notifications
        inn = section(t("set.notif"))
        grid = tk.Frame(inn, bg=C["card"])
        grid.pack(fill="x")
        on = tk.BooleanVar(value=cfg.get("notifications", True))
        tk.Checkbutton(grid, text=t("set.notif_on"), variable=on, font=font(10),
                       bg=C["card"], activebackground=C["card"], fg=C["text"], selectcolor=C["card"],
                       highlightthickness=0, bd=0).grid(row=0, column=0, columnspan=2, sticky="w",
                                                        pady=(self.px(10), self.px(6)))
        fields = [
            ("interval_minutes", t("set.interval"), 5, 600, 1),
            ("nag_minutes", t("set.nag"), 1, 120, 1),
            ("wrong_retry_minutes", t("set.wrong"), 1, 120, 1),
            ("reverse_chance", t("set.reverse", native=tr.native, lang=tr.language), 0, 100, 100),
        ]
        vars_ = {}
        for i, (key, text, lo, hi, factor) in enumerate(fields, start=1):
            self.label(grid, text, 10).grid(row=i, column=0, sticky="w", pady=self.px(5))
            v = tk.StringVar(value=str(round(cfg.get(key, 0) * factor)))
            tk.Spinbox(grid, from_=lo, to=hi, textvariable=v, width=6, font=font(10), relief="flat",
                       bg=C["bg"], fg=C["text"], insertbackground=C["text"], highlightthickness=1,
                       highlightbackground=C["border"], buttonbackground=C["bg"]).grid(row=i, column=1, sticky="w", padx=(self.px(20), 0))
            vars_[key] = (v, lo, hi, factor)
        field_vars.update(vars_)

        msg = self.label(inn, status, 9, color="accent")

        def save():
            changes = {"notifications": on.get()}
            for key, (v, lo, hi, factor) in vars_.items():
                try:
                    n = int(v.get())
                except ValueError:
                    msg.config(text=t("set.int_error"), fg=C["bad"])
                    return
                n = max(lo, min(hi, n))
                changes[key] = n / factor if factor != 1 else n
            if changes["interval_minutes"] != cfg.get("interval_minutes"):
                changes["schedule"] = "interval"   # a fixed interval typed in: back to a regular rhythm
            self.app.update_config(changes)
            sync()
            msg.config(text=t("set.saved"), fg=C["accent"])

        self.button(inn, t("set.save"), save).pack(anchor="w", pady=(self.px(12), 0))
        msg.pack(anchor="w", pady=(self.px(6), 0))
        sync()

        # reset
        inn = section(t("set.reset"))
        row = tk.Frame(inn, bg=C["card"])
        row.pack(fill="x", pady=(self.px(4), 0))
        self.label(row, t("set.reset_sub", lang=tr.language), 9, color="muted", wraplength=self.px(520)).pack(side="left")

        def reset():
            if messagebox.askyesno(t("set.reset"), t("set.reset_q", lang=tr.language), icon="warning", parent=self.root):
                tr.reset()
                self.app.update_tray()
                self.show("settings", t("set.reset_done"))

        self.button(row, t("set.reset_btn"), reset, "danger").pack(side="right")
