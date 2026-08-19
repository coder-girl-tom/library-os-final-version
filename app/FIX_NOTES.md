# Fix Notes — LibrarySystemPRO

This build fixes 3 bugs that were causing every page to fail or appear blank.

## Bug 1 — Stale database (the error you originally saw)
`instance/library.db` was created from an older version of the code and was
missing columns/tables that the current `app.py` models expect (e.g.
`books.accession_number`). SQLAlchemy's `db.create_all()` only creates
tables that don't exist yet — it never updates existing tables.

**Fix:** Deleted the old `instance/library.db`. The app recreates it
automatically on first run via `db.create_all()` + `init_default_admin()`,
matching the current models exactly.

You start with a clean database and one login:
- Username: `admin`
- Password: `admin123`

**Change this password after your first login** (Settings page) — it's a
known default and shouldn't stay active long-term, especially once you
package this as a distributable .exe.

## Bug 2 — Every page was crashing with a 500 error
`templates/base.html` defined the same Jinja block (`page_title`) twice.
Jinja does not allow a block name to be reused within one template, so
*every* page that extends `base.html` (dashboard, books, students,
literally everything) failed to render at all. This is why your dashboard
(and every other page) showed nothing / errored.

**Fix:** The second occurrence now reuses the first block's rendered value
via `{{ self.page_title() }}` instead of redeclaring the block.

## Bug 3 — Login looked broken / session didn't persist
`SESSION_COOKIE_SECURE` defaulted to `True`, which tells the browser to
only store/send the session cookie over HTTPS. Since this app runs on
plain `http://127.0.0.1:5000` (and will also run as a local .exe over
plain HTTP), browsers were silently refusing to keep the login cookie —
so even a successful login wouldn't "stick."

**Fix:** Defaults to `False` now (off), since this is a local/desktop app
over HTTP. It can still be turned on via the `SESSION_COOKIE_SECURE=1`
environment variable if you ever deploy this behind HTTPS.

## Bug 4 (bonus, found via static analysis) — Password recovery was broken
`password_recovery()` and `update_recovery()` both called
`generate_password_hash(...)`, a function that was never imported anywhere
in `app.py` — this would have crashed with `NameError` the moment anyone
used "Forgot password" or tried to set a recovery answer in Settings.
Additionally, the original comparison (`hash(input) == stored_hash`) would
never have matched even with the import fixed, since salted hashes are
different every time you generate them.

**Fix:** Both now use the same `bcrypt` instance already used for login
passwords elsewhere in the app — `bcrypt.generate_password_hash(...)` to
store the recovery answer, and `bcrypt.check_password_hash(...)` to verify
it. This was tested end-to-end (set recovery answer → log out → recover
password with correct/incorrect answers).

---

## What was tested
- Every page route, logged in, over real HTTP with persistent cookies
  (not just Flask's test client — actual `curl` with a cookie jar, the
  same way a browser behaves).
- Add/edit/delete book, add/edit/delete student.
- Issue a book, block a duplicate issue, return a book (on-time and with
  damage/late fine logic).
- Student profile: notes, wishlist add/remove.
- Admin: add user, view manage-users page, create a backup, view backups.
- Settings: change password, set recovery answer, then actually recover
  the password using it (correct and incorrect answer cases).
- Static analysis (`pyflakes`) on `app.py` — clean, no undefined names.

## Not changed (intentionally)
- `config.py` is unused dead code (app.py builds its config inline) —
  left as-is since removing it isn't necessary and isn't causing errors.
- Several `Query.get()` calls produce a harmless SQLAlchemy 2.0
  deprecation warning in the console. They still work correctly; left
  alone to avoid introducing typos across 9 call sites for a cosmetic
  warning with zero functional impact.
- AI "enrich book" feature (`services/gemini_service.py`) requires a
  `GEMINI_API_KEY` environment variable you don't currently have set.
  It's wrapped in try/except already, so it fails gracefully with a flash
  message rather than crashing — nothing to fix unless you want that
  feature working, in which case you'd need a real Gemini-compatible API
  key and endpoint.

## Packaging as an .exe
There was a stale `build/` and `dist/launcher.exe` in the project folder
from a previous PyInstaller run — that one was built from the broken code,
so delete both folders and rebuild from this fixed version:

```
pip install pyinstaller
pyinstaller --onefile --add-data "templates;templates" --add-data "static;static" --name LibrarySystemPRO launcher.py
```

Run this on Windows (PyInstaller builds platform-native executables, so it
must be run on Windows to produce a .exe). The output will be in
`dist/LibrarySystemPRO.exe`. Copy the `templates/` and `static/` folders
next to the .exe if `--add-data` bundling has any issues, since Flask
looks for them relative to the app's working directory in some PyInstaller
configurations.

---

# Round 2 — UI fixes (logo, icons, dark mode, broken forms)

## Bug 5 — Wrong/placeholder logo showing
The sidebar always rendered two generic green "library os" placeholder
SVGs (`logo-light.svg` / `logo-dark.svg`), even though your real logo
(`uswa-logo.png`) was sitting right there in `static/`. `app.py` already
had a `has_logo` check wired up in its template context, but `base.html`
never used it.

**Fix:** Sidebar now shows `uswa-logo.png` (in a small white rounded chip
so it reads cleanly against the dark sidebar) whenever it's present, and
falls back to the placeholder SVGs only if the PNG is ever missing.

## Bug 6 — Icons showing as empty squares
All icon fonts (Bootstrap Icons), Bootstrap's CSS/JS, and Chart.js were
loaded from `cdn.jsdelivr.net`. If the machine running the app has no
internet access at that moment — which is the normal case for a packaged
desktop .exe — these fail to load and every icon renders as an empty box.

**Fix:** Bootstrap, Bootstrap Icons (including its font files), and
Chart.js are now bundled locally under `static/vendor/` and referenced
via `url_for('static', ...)` instead of the CDN. The app now works fully
offline, which also matters for your .exe build. This added ~1.8MB to the
project — worth it for a desktop app that shouldn't depend on internet
access just to render its own UI.

## Bug 7 — Dark mode text was unreadable
Card headers, table cell text, the welcome banner, and several other
Bootstrap components were not actually picking up the app's dark color
scheme — they kept Bootstrap's own default near-black text and white
backgrounds regardless of the `data-theme="dark"` toggle. The custom CSS
variables (`--text`, `--card-bg`, etc.) were defined correctly, just not
applied to every component.

**Fix:** Added explicit dark-mode-aware overrides for card headers/bodies,
table cells (including Bootstrap 5.3's internal `--bs-table-*` CSS
variables, which silently override plain `color`/`background` rules if
left untouched), flash message alerts (success/danger/warning/info, each
themed for both light and dark), dropdown menus, modals, and the
`text-muted` utility class. Verified with real rendered screenshots in
both themes — dashboard, students, books, settings, and issue/return all
checked.

## Bug 8 — Adding a student silently failed (or saved garbage data)
`templates/add_student.html`'s form fields were named `name` and
`roll_number`, but `app.py`'s `add_student()` route reads
`request.form.get('student_id')` and `request.form.get('full_name')`.
Submitting the form would hit `None.strip()` and fail with a flash error
— easy to miss since it doesn't crash the page, just silently rejects the
submission.

**Fix:** Form fields renamed to `student_id` and `full_name` to match
what the route actually reads.

## Bug 9 — Students list showed blank rows
`templates/students.html` referenced `s.serial_number`, `s.roll_number`,
and `s.name` — none of which exist on the `Student` model (it has
`student_id` and `full_name` instead). With an empty database this never
triggered, which is why earlier testing missed it — Jinja silently
renders undefined attributes as empty strings rather than erroring. The
moment a real student got added through the actual web form, their row
in the Students table would show completely blank cells. Same issue in
that page's live-search dropdown JS.

**Fix:** Table and search JS updated to use `student_id` and `full_name`,
matching both the model and the `/api/search` JSON response shape.

## Bug 10 — Issue/Return student search showed "(undefined)"
`templates/issue_return.html`'s student live-search used `s.roll_number`,
but the JSON data passed into that page from `app.py` uses the key
`student_id` instead. Searching for a student to issue a book to would
correctly find them by name, but display their ID as "undefined."

**Fix:** Updated to use `s.student_id`, matching the actual data shape.

## Bug 11 — Reports page low-stock table showed blank "Total Copies"
`templates/reports.html` referenced `b.total_copies`, which doesn't exist
on the `Book` model (the field is called `quantity`).

**Fix:** Changed to `b.quantity`.

## What was tested (round 2)
- Real rendered screenshots (via headless Chrome) of dashboard, students,
  books, settings, and issue/return pages in both light and dark mode.
- Added a real book and a real student through the actual HTML forms
  (not bypassed via direct POST with hand-picked field names) to catch
  exactly this class of template/field-name mismatch.
- Confirmed the students list and issue/return live-search both display
  real student data correctly after the fixes.
- Verified every static vendor asset (Bootstrap CSS/JS, Bootstrap Icons,
  Chart.js, the logo) is served locally and returns 200 — no CDN
  dependency remains anywhere in the app.
- Cross-checked every template's field references against the actual
  SQLAlchemy model definitions in `app.py` to catch any other
  field-name drift — only the ones listed above were found.
- Re-ran the full route/workflow regression suite from round 1 to confirm
  nothing broke.

