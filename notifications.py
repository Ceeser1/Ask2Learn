"""Windows toast notifications: quiz with 3 answer buttons + feedback."""

import datetime as dt
import logging
import winreg
from pathlib import Path
from typing import Callable

from windows_toasts import (
    AudioSource,
    InteractableWindowsToaster,
    Toast,
    ToastActivatedEventArgs,
    ToastAudio,
    ToastButton,
    ToastButtonColour,
    ToastDismissalReason,
    ToastDuration,
    ToastScenario,
)

from appconfig import IDENTITY, SOUNDS, THEMES
from i18n import quote, t
from quiz import Question

log = logging.getLogger(__name__)

AUMID = IDENTITY["notification_id"]   # Windows' internal ID for our notifications, never shown
QUIZ_GROUP = "quiz"
FEEDBACK_GROUP = "feedback"


def register_app(icon_path: Path) -> None:
    """Registers our AUMID under HKCU so button clicks reach us (no admin needed)."""
    key_path = rf"Software\Classes\AppUserModelId\{AUMID}"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
        winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, t("app.name"))
        winreg.SetValueEx(key, "IconUri", 0, winreg.REG_SZ, str(icon_path.resolve()))
        winreg.SetValueEx(key, "IconBackgroundColor", 0, winreg.REG_SZ,
                          "FF" + THEMES["brand"]["blue"].lstrip("#").upper())


def _sound(name: str, looping: bool) -> ToastAudio:
    try:
        source = AudioSource[name]
    except KeyError:
        source = AudioSource[SOUNDS["default"]]
    if looping and not source.value.startswith("Looping."):
        source = AudioSource[SOUNDS["looping"]]
    return ToastAudio(source, looping=looping)


class Notifier:
    def __init__(self, icon_path: Path):
        register_app(icon_path)
        self.toaster = InteractableWindowsToaster(t("app.name"), notifierAUMID=AUMID)

    def show_quiz(
        self,
        q: Question,
        header: str,
        sound: str,
        looping: bool,
        on_answer: Callable[[Question, int], None],
        on_ignored: Callable[[Question], None],
    ) -> None:
        self.toaster.remove_toast_group(QUIZ_GROUP)  # never stack old quizzes

        def activated(args: ToastActivatedEventArgs) -> None:
            arg = args.arguments or ""
            qid, _, idx = arg.partition("|")
            if qid == q.id and idx.isdigit():
                on_answer(q, int(idx))
            else:  # clicked the toast body instead of a button
                on_ignored(q)

        def dismissed(args) -> None:
            reason = getattr(args, "reason", None)
            if reason == ToastDismissalReason.APPLICATION_HIDDEN:
                return  # we removed it ourselves
            on_ignored(q)

        toast = Toast(
            text_fields=[q.prompt, header],
            scenario=ToastScenario.Reminder,  # stays on screen until a button is pressed
            audio=_sound(sound, looping),
            group=QUIZ_GROUP,
            on_activated=activated,
            on_dismissed=dismissed,
            on_failed=lambda e: log.error("Quiz toast failed: %s", e),
        )
        for i, option in enumerate(q.options):
            toast.AddAction(ToastButton(option, f"{q.id}|{i}"))
        self.toaster.show_toast(toast)

    def show_feedback(self, q: Question, chosen: int, ok: bool, extra: str = "") -> None:
        if q.reverse:
            pair = t("fmt.pair", a=quote(q.translation), b=quote(q.word))
        else:
            pair = t("fmt.pair", a=quote(q.word), b=quote(q.translation))

        if ok:
            lines = [t("notif.right"), pair]
        else:
            lines = [t("notif.wrong"), t("fmt.pair_not", pair=pair, **{"not": t("notif.not", w=quote(q.options[chosen]))})]
        if extra:
            lines.append(extra)

        self.toaster.remove_toast_group(FEEDBACK_GROUP)
        self.toaster.show_toast(Toast(
            text_fields=lines,
            duration=ToastDuration.Short,
            group=FEEDBACK_GROUP,
            audio=ToastAudio(silent=ok),
            expiration_time=dt.datetime.now() + dt.timedelta(minutes=2),
        ))

    def show_info(self, title: str, body: str) -> None:
        self.toaster.remove_toast_group(FEEDBACK_GROUP)
        self.toaster.show_toast(Toast(
            text_fields=[title, body],
            group=FEEDBACK_GROUP,
            audio=ToastAudio(silent=True),
            expiration_time=dt.datetime.now() + dt.timedelta(minutes=5),
        ))
