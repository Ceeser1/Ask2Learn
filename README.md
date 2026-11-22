# Ask 2 Learn (A2L)

**The language app that keeps asking until you've got it.**

Most language apps wait politely until you open them, so you don't. A2L doesn't wait. It sits in your Windows tray and throws a quiz at you every hour (or every 5 minutes, if you dare). Ignore it and it comes back. Keep ignoring it and it gets louder. Answer wrong and you get the same word again a few minutes later, until you get it right.

You have to *want* to install this. The installer asks.

On top of the nagging there's a proper course: lessons that build on each other, grammar explanations, a Daily Challenge and spaced repetition.

## Languages

| You speak | You learn | Course |
|---|---|---|
| Deutsch, English | Portuguese (Portugal) 🇵🇹 | A1 complete: 72 lessons in 8 parts, 589 words and phrases, 22 grammar lessons |
| Deutsch, English | Spanish (Spain) 🇪🇸 | A1 parts 1–7: 34 lessons, 319 words and phrases, 8 grammar lessons (more coming) |

European variants on purpose: *comboio*, *autocarro*, *estou a ler* for Portuguese; *coche*, *vosotros*, *zumo* for Spanish. Where Portugal or Spain differs from Brazil or Latin America, the lesson says so.

On first start you pick your native language (your system language is preselected) and the language you want to learn. You can switch at any time; progress is kept per language.

Both can be changed separately in the settings:

- **Native language**: the language the course explains things in (translations, lesson titles, tips, grammar explanations). Switching it changes the whole course right away; your progress stays.
- **App language**: menus, buttons and messages. It starts with your system language and keeps whatever you pick.

## Install (Windows 10/11)

Needs [Python 3.10+](https://www.python.org/downloads/) with the "py launcher" option.

```powershell
git clone <this repo>
cd <repo folder>
.\setup.bat
```

Or double-click `setup.bat`. It asks whether you really want this, creates a virtual environment, installs the dependencies, adds **Ask 2 Learn** shortcuts to your Desktop, Start menu and autostart, and opens the app.

Run `setup.bat` again after pulling updates. Uninstall with `setup.bat -Remove` (your progress stays in `%APPDATA%\Ask 2 Learn`).

## What's inside

- **Course**: eight parts that build on each other, vocabulary and grammar taking turns up to the end of A1: core words → first grammar → simple requests & questions → simple grammar → everyday vocabulary → core grammar → extended vocabulary → extended grammar.
  - *Usage first*: right after the core words come the things you actually say: *where am I?*, *where is …?*, *what time is it?*, *can you please …?*, *I don't understand*, ordering, paying, tickets. Family trees, colours, animals and describing your flat come last.
  - *Sections*: a lesson can be split into sections, and each section can be practised on its own. Once every section is done, the lesson counts as done.
  - *Vocabulary lessons* in three rounds: recognise the word, pick it from your language, type it yourself. Flashcards and tips included.
  - *Grammar lessons*: explanation with tables and examples, then multiple-choice exercises, then exercises where you type the answer. Accents count (*e* ≠ *é*).
  - Missed items come back a few cards later. Every lesson can be repeated; your best score is kept.
- **Daily Challenge**: 30 words you've answered correctly before, no second chances. **Reshuffle** swaps in 30 different ones.
- **Review**: spaced repetition. Words come back after 1, 2, 4, 8 and 16 days; a wrong answer sends them back to the start.
- **Dictionary**: every word with its level, searchable.
- **Notifications**: a quiz with three answers to pick from. It stays on screen until you answer, holds off while you're gaming or watching something in fullscreen (except at *Fuck-Off*, which opens the quiz on top of the game and pulls you out) or away from the PC, and pauses for 15 minutes after you practise in the window.
- **Annoyance level**: a slider with seven steps: *Never*, *Only once after startup*, *Every 3 hours*, *Random* (some time between 1 and 20 hours later), *Once every hour* (default), *Whenever possible* (every 15 min) and *Fuck-Off* (every 5 min). Everything up to *Whenever possible* never interrupts you: a quiz waits for a short pause in your typing and clicking, never in fullscreen, and never with a looping sound. *Fuck-Off* doesn't wait for anything, loops the sound once you ignore it twice and pulls you out of fullscreen.

## Configuration

Most things are in the app's settings. Defaults live in `config.json`; your own settings and progress are in `%APPDATA%\Ask 2 Learn` (`settings.json`, plus one folder per course).

Nothing about the app is hard-coded. Everything can be adjusted in data files, without touching code:

| File | What's in it |
|---|---|
| `config.json` | Defaults for the settings below |
| `app.json` | The seven annoyance levels, timings, learning rules (review intervals, box weights, Daily Challenge size, batch sizes), sounds, file and folder names, Windows IDs |
| `themes.json` | Colors (brand palette, dark and light theme) and fonts |
| `lang/*.json` | Every interface text, one file per language |
| `courses/*.json` | The courses, including their language rules (articles you may leave out when typing, letters that count as the same) |

| Setting | Meaning |
|---|---|
| `native` | Native language the course translates and explains in (`en`, `de`) |
| `app_language` | Interface language (`en`, `de`), also used for unit, lesson and section titles. Not set: your system language |
| `schedule` | `interval` (every `interval_minutes`), `random` (1 to 20 hours), `once` (once per start) or `never`. Set by the annoyance slider |
| `interval_minutes` | Time between quizzes after a correct answer |
| `nag_minutes` | How soon an ignored quiz comes back |
| `wrong_retry_minutes` | How soon a wrongly answered word comes back |
| `escalate_after_ignores` | Ignored quizzes in a row before the sound starts looping (`0`: never) |
| `wait_for_pause_seconds` | A quiz only comes after this many seconds without typing or clicking (`0`: right away) |
| `away_after_minutes` | No input for this long counts as "away" |
| `reverse_chance` | Share of questions asked from your language into the one you're learning |
| `new_words_at_once` | How many unfamiliar words the notifications keep in rotation |
| `sound` / `looping_sound` | `Reminder`, `Default`, `IM`, `Mail`, `SMS`, `Alarm`, `Alarm2` … `Call10` |
| `interrupt_fullscreen` | `true` only at *Fuck-Off*: the quiz pulls you out of fullscreen apps and games instead of waiting |
| `notifications` | `false` turns the notification quiz off |

Debug the fullscreen/idle detection with `.venv\Scripts\python.exe main.py --check`.

## Adding languages

**A course to learn**: add a file to `courses/`. Look at `courses/es-ES.json` for the format:

- Header: `id`, `language`, `name` / `short` / `variant` (one text per native language), `level`, `natives` (the native languages it supports), `accents` (letters offered as buttons when typing), `articles` (articles that may be left out when typing a word: `["el", "la", …]`), `equivalents` (letters that count as the same when typing loosely, e.g. `{"ß": "ss"}`).
- Vocabulary lessons: `"words": [["hola", "hallo", "hello"], …]`, the word followed by one translation per entry in `natives`. Whole phrases work the same way: `["¿dónde está el baño?", "wo ist die Toilette?", "where is the toilet?"]`.
- Grammar lessons: `"explanation"` per native language (blocks of `h`, `p`, `table`, `ex`, `tip`), and `"exercises"` as `[sentence with ___, answer, translation, options or null, optional instruction]`. `null` options make it a typing exercise. Answers may list alternatives as `"a / b"`.
- Sections: every lesson has at least one. Without `"sections"` the whole lesson is a single section. To split a lesson, replace `"words"` (or `"explanation"` + `"exercises"`) with `"sections": [{"title": {…}, "words": […]}, …]` (or `{"title", "explanation", "exercises"}` for grammar). There's no upper limit, so harder languages can split a lesson into as many sections as they need.

**Structure every course from the point of use.** Courses have eight parts, vocabulary and grammar taking turns, ending at A1:

1. Core vocabulary: greetings and politeness, small words, pronouns, question words, key verbs, numbers 0–10
2. Very simple grammar
3. Simple vocabulary for simple requests: where am I, where is …, time and date, can you please …, not understanding, introducing yourself, ordering, paying, tickets
4. Still simple grammar
5. Everyday vocabulary
6. Core grammar
7. Extended vocabulary
8. Extended grammar (end of A1)

Teach the phrases you'd actually say (*¿dónde está el baño?*, *queria um café*), not only the nouns, and put the most useful items first within a lesson. Anything that doesn't help in a real conversation (grandparents, animals, describing your own flat) goes in part 7, or is left out. Notes that say "you'll learn this in part N" must point to the right part.

**A language for the interface**: copy `lang/en.json` to `lang/<code>.json` (e.g. `lang/fr.json`), set `code` and `name` (the language's own name), and translate `languages` (language names) and `texts`. That's all: the app finds the file and offers the language under *App language*. English is the root: every key exists there, and a text a file doesn't have yet is shown in English.

**A native language for a course**: add its code to the course's `natives` and one translation per text in the course file. The welcome screen and the settings offer every native language a course supports.

**Every text needs a translation.** No text is written in the code: every interface text is a key in the language files (`lang/*.json`), one file per language. Formats are texts too (`fmt.*`: separators, arrows, number formats like `{a} / {b}`), because other languages may need them differently. Names (a feature, a level, the app) are translated once under their own key, and other texts point to them instead of repeating the word: `{@name.daily}` inserts the name of the daily challenge, `{@name.daily:upper}` the same in capitals, and every text in a course file has one entry per native language listed in `natives`. Check with `.venv\Scripts\python.exe main.py --check-texts`, which lists every gap and exits with code 1 if there is one.

## Logo

The tray and window icon is a placeholder ("A2L"). Put a square `assets/logo.png` in the folder and it's used everywhere (tray, shortcuts, notifications) after the next start or `setup.bat`.

## Project layout

| File | What it does |
|---|---|
| `main.py` | Start-up, settings, tray icon, notification scheduler |
| `gui.py` | The window (Tkinter) |
| `quiz.py` | Courses, lessons, sessions, spaced repetition, Daily Challenge |
| `i18n.py` | Loads the language files, looks up texts, detects the system language |
| `appconfig.py` | Loads `app.json` and `themes.json` |
| `notifications.py` | Windows toast notifications |
| `presence.py` | Fullscreen / idle detection, single instance |
| `courses/` | Course content |
| `lang/` | Interface texts, one file per language |
| `app.json`, `themes.json`, `config.json` | Adjustable app values, colors, setting defaults |
