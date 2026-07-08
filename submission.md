# Project 5 — Mixtape Bug Hunt — Submission

**Author:** Samuel Berhan
**Branch:** `bugfix/mixtape`

---

## AI Usage

_(Filled in fully in Milestone 4. See the "AI Usage" section at the end of this document for the complete write-up of how AI tools were used during navigation and debugging.)_

---

## Milestone 1 — Codebase Map

Mixtape is a Flask + SQLAlchemy JSON API. There is no HTML front end; every feature is an
endpoint that returns JSON. The app is layered strictly: **routes parse input and format
responses, services hold all business logic, models define the data.**

### Main files and their roles

| File | Responsibility |
|------|----------------|
| `app.py` | Flask application factory (`create_app`). Creates the single `db = SQLAlchemy()` instance, configures the SQLite DB (`mixtape.db`), registers the four blueprints under their URL prefixes (`/songs`, `/playlists`, `/users`, `/feed`), and calls `db.create_all()`. |
| `models.py` | All SQLAlchemy models + three association tables. |
| `routes/songs.py` | `/songs/search`, `/songs/<id>`, `POST /songs/<id>/rate`, `POST /songs/<id>/listen`. Thin — each route validates input and delegates to a service. |
| `routes/playlists.py` | Create playlist, get playlist metadata, `GET /playlists/<id>/songs`, `POST /playlists/<id>/songs`. |
| `routes/users.py` | User profile, `GET /users/<id>/streak`, `GET /users/<id>/notifications`, mark-notification-read. |
| `routes/feed.py` | `GET /feed/<id>/listening-now` (friends listening now) and `GET /feed/<id>/activity`. |
| `services/streak_service.py` | Records listening events and maintains each user's consecutive-day listening streak. |
| `services/feed_service.py` | Builds the "Friends Listening Now" feed (one most-recent song per recently-active friend). |
| `services/search_service.py` | Song search by title/artist (case-insensitive `ILIKE`). |
| `services/notification_service.py` | Creates/retrieves notifications; also owns `add_to_playlist` and `rate_song` (the two friend-interaction actions that *should* notify the song's sharer). |
| `services/playlist_service.py` | Creates playlists and returns a playlist's songs in position order. |
| `seed_data.py` | Drops + recreates the DB and inserts 5 users (with friendships), 13 songs (deliberately with 0, 1, and 3+ tags), 3 playlists, listening events, streak state, and one sample notification. |
| `tests/` | pytest suites for streaks, search, and playlists. Several tests already encode the *expected* (post-fix) behavior and currently fail — they double as regression tests. |

### Data models (`models.py`)

Six models plus three association tables:

- **`User`** — `username`, `email`, `listening_streak`, `last_listened_at`. Self-referential
  many-to-many `friends` via the `friendships` table (stored bidirectionally by the seed).
- **`Song`** — `title`, `artist`, `album`, `genre`, `shared_by` (FK → User), `shared_at`.
  Many-to-many `tags`.
- **`Tag`** — a tag name; linked to songs through `song_tags`.
- **`ListeningEvent`** — one row per play: `user_id`, `song_id`, `listened_at`. This is the
  source of truth for both streaks and the "listening now" feed.
- **`Rating`** — `user_id`, `song_id`, `score` (1–5), with a unique constraint on
  `(user_id, song_id)` so a user has at most one rating per song.
- **`Playlist`** — `name`, `created_by`, `is_collaborative`. Songs are attached through the
  **`playlist_entries`** association table, which carries an explicit **`position`** column
  (plus `added_by`, `added_at`) — so a playlist's song order is explicit, not insertion order.
- **`Notification`** — `user_id` (recipient), `notification_type`, `body`, `read`.

### Data flow — sharing/interaction triggers a notification

Example the brief calls out (a friend adds your song to a playlist):

```
POST /playlists/<playlist_id>/songs
  → routes/playlists.py: add_song()          # parse song_id + added_by from JSON
  → notification_service.add_to_playlist(playlist_id, song_id, added_by)
        - look up song, adder, playlist
        - append song to playlist.songs (if not already present)
        - if song.shared_by != added_by:
              create_notification(user_id=song.shared_by,
                                  type="song_added_to_playlist",
                                  body="<adder> added your song ...")
  → Notification row committed → shows up in GET /users/<sharer_id>/notifications
```

The parallel action — rating a song — flows
`POST /songs/<id>/rate → routes/songs.py: rate() → notification_service.rate_song()`.
Structurally it *should* mirror `add_to_playlist` and notify `song.shared_by`, which is the
lens for Issue #4.

### Data flow — a play updates a streak

```
POST /songs/<song_id>/listen
  → routes/songs.py: listen()
  → streak_service.record_listening_event(user_id, song_id)
        - create a ListeningEvent(listened_at=now)
        - update_listening_streak(user, now):
              compare now.date() to user.last_listened_at.date()
              days_since_last == 0  → no change (already listened today)
              days_since_last == 1  → streak += 1 (consecutive day)
              otherwise             → streak = 1 (gap → reset)
        - commit
  → GET /users/<id>/streak reads user.listening_streak
```

### Patterns I noticed

- **Strict route → service → model layering.** Every route immediately delegates to exactly one
  service function; routes never touch the DB except the trivial `get_user` lookup. All the
  logic that can be buggy lives in `services/`, which is exactly where the brief says the bugs are.
- **`db` is a module-level singleton in `app.py`** and imported everywhere. Services call
  `db.session.get(Model, id)` / `db.session.query(...)`.
- **Time is stored in UTC** (`datetime.now(timezone.utc)`), but some `last_listened_at` values
  loaded from SQLite come back naive, so the streak code defensively re-attaches `tzinfo`.
- **The seed data is engineered to expose the bugs**: songs with 3+ tags (Issue #3), a friend
  whose last listen was ~an evening ago (Issue #2), a 12-day streak user (Issue #1),
  full playlists (Issue #5), and a working playlist-add notification with no rating counterpart
  (Issue #4).

### The five issues → suspected service (from reading, confirmed in later milestones)

| # | Symptom | Service to trace |
|---|---------|------------------|
| 1 | Streak resets every Sunday | `streak_service.update_listening_streak` |
| 2 | Feed shows yesterday-evening friends | `feed_service.get_friends_listening_now` |
| 3 | Multi-tag songs duplicated in search | `search_service.search_songs` |
| 4 | Rating never creates a notification | `notification_service.rate_song` |
| 5 | Newest playlist song always missing | `playlist_service.get_playlist_songs` |

I read all five issue descriptions before choosing. I plan to fix **all five** (they are
independent, single-service bugs), starting with #1, #3, and #5 as the required three because
each already has a failing regression test in `tests/` I can verify against.

---

## Milestone 2 — Reproduction (before touching any code)

I reproduced every bug by calling the service functions directly against a fresh in-memory
database seeded to mirror each reporter's conditions (faster and more controllable than firing
HTTP requests, as the brief suggests). I also ran the shipped test suite as a baseline.

**Baseline `pytest tests/`:** `3 failed, 10 passed`.
Failing: `test_streak_increments_on_sunday`, `test_playlist_returns_all_songs`,
`test_playlist_returns_songs_in_order`. These are effectively pre-written regression tests
for Issues #1 and #5.

| # | Reproduction (controlled inputs) | Observed vs. expected |
|---|----------------------------------|-----------------------|
| 1 | User with streak 12, `last_listened_at` = Saturday; call `update_listening_streak(user, Sunday)`. Control: same setup ending on Monday. | Sunday → streak **1** (expected 13). Monday control → **13**. Confirms it's Sunday-specific. |
| 2 | `now` = 09:00 today; friend `darius` has one `ListeningEvent` at ~11pm "last night" (10h ago, but before today's midnight). Call `get_friends_listening_now`. | Feed **shows darius** (expected: excluded, since his play was on a previous calendar day). |
| 3 | Song "Crown Heights Anthem" with 3 tags; call `search_songs("Anthem")`. | Via `search_songs` (legacy `Query.all()`): appears **1×** — the reported dup is *masked*. Digging in: the `outerjoin(song_tags)` emits **3 raw rows** (`select(Song.id)…` → 3; `select(Song).scalars().all()` → 3). Only the legacy Query API's implicit entity de-duplication hides it. **The duplicate-producing join is real and latent.** (See RCA #3 for the full explanation.) |
| 4 | Owner shares a song; a friend calls `rate_song(friend, song, 5)`. Count owner's notifications before/after. | before **0**, after **0** (expected after = 1). No notification row is ever created. |
| 5 | Playlist with 7 entries (positions 1–7); call `get_playlist_songs`. | Returns **6** songs, missing "Track 7" — the highest position / most recently added. |

At this checkpoint no application code had been changed.

---

## Milestone 3 — Root Cause Analysis Entries

### RCA #1 — Issue #1: My listening streak keeps resetting

**1. Issue number and title:** #1 — My listening streak keeps resetting (every Sunday).

**2. How I reproduced it:** In an in-memory DB I set a user to `listening_streak = 12` with
`last_listened_at` on a Saturday (`datetime(2024, 6, 15)`, `weekday() == 5`), then called
`update_listening_streak(user, sunday)` with `datetime(2024, 6, 16)` (`weekday() == 6`). The
streak dropped to **1** instead of 13. As a control I ran the identical sequence ending on a
Monday and got **13**, which isolated the fault to Sundays specifically. The shipped test
`test_streak_increments_on_sunday` also failed with `assert 1 == 2`.

**3. How I found the root cause:** I traced the streak feature top-down from
`POST /songs/<id>/listen` → `routes/songs.py: listen()` →
`streak_service.record_listening_event()` → `update_listening_streak()`. The reset happens in
the day-difference branch in `update_listening_streak`. The `days_since_last == 1` branch —
the one that should increment on a consecutive day — carried an extra condition
`and today.weekday() != 6`. The moment I saw `weekday() != 6` I checked what `weekday()`
returns for Sunday: `datetime.weekday()` is **Monday=0 … Sunday=6**. So for a consecutive-day
listen that falls on a Sunday, `today.weekday() == 6`, the `elif` is `False`, and execution
falls through to the `else`, which resets the streak to 1. That's the exact line and the exact
reason it's Sunday-only.

**4. The root cause:** Python's `datetime.weekday()` returns `6` for Sunday. The increment
branch was written as `elif days_since_last == 1 and today.weekday() != 6:`. There is no
legitimate reason for a streak to care which weekday it is — consecutive is consecutive — but
this clause specifically excludes Sundays from being counted as a consecutive day. Every Sunday
listen (even one that directly follows a Saturday listen) was therefore treated like a skipped
day and reset the streak to 1. This is why kenji's 12-day streak collapsed to 1 both times, and
both times it was a Sunday.

**5. My fix and side-effect check:** I removed the spurious weekday clause, changing
`elif days_since_last == 1 and today.weekday() != 6:` to `elif days_since_last == 1:`. Now any
listen exactly one calendar day after the previous one increments the streak regardless of
weekday. Side-effect check: I confirmed the other three branches are untouched and still
correct — `days_since_last == 0` (same day, no change), and `days_since_last > 1` (real gap,
resets to 1). All five tests in `tests/test_streaks.py` pass, including
`test_streak_resets_after_skipped_day` (a genuine skipped day still resets) and
`test_streak_does_not_double_count_same_day` — so both sides of the day boundary still behave.

### RCA #2 — Issue #2: Friends Listening Now shows people from yesterday

**1. Issue number and title:** #2 — "Friends Listening Now" shows friends whose last listen was
yesterday evening.

**2. How I reproduced it:** With `now` set to 09:00 today, I created a friend (`darius`) with a
single `ListeningEvent` timestamped ~11pm the previous night (about 10 hours earlier, but on
the previous calendar day), then called `get_friends_listening_now(me)`. Darius appeared in the
feed even though his only play was the night before. To pin down the boundary I later created
two friends — one who played 30 minutes *before* midnight and one who played 30 minutes
*after* — and confirmed the pre-midnight one should drop off while the post-midnight one stays.

**3. How I found the root cause:** I traced `GET /feed/<id>/listening-now` →
`routes/feed.py: listening_now()` → `feed_service.get_friends_listening_now()`. The function
filters listening events with `ListeningEvent.listened_at >= cutoff`. I read how `cutoff` was
computed: `cutoff = datetime.now(timezone.utc) - RECENT_THRESHOLD`, where
`RECENT_THRESHOLD = timedelta(hours=24)`. That made me confident this was the cause: a
`now − 24h` cutoff is a **rolling 24-hour window**, which is a different thing from "today."
Plugging in the numbers confirmed it: at 09:00, the cutoff is 09:00 *yesterday*, so an event at
23:00 yesterday (10 hours before now) is comfortably inside the window and is returned.

**4. The root cause:** The feed defined "recently / listening now" as *"within the last 24
hours"* (`now - timedelta(hours=24)`) rather than *"today, this calendar day."* Because it's a
sliding window anchored to the current instant, any play from yesterday evening stays in the
window until the same clock time the next day — exactly the "hangs around until the same time
the next day" behavior nova described. The two definitions only agree at midnight; at every
other time of day the rolling window leaks in part of the previous calendar day.

**5. My fix and side-effect check:** I changed the cutoff from `now - 24h` to the **start of the
current UTC day**: `cutoff = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0,
microsecond=0)`, and removed the now-unused `RECENT_THRESHOLD` constant (and the unused
`timedelta` import). Now only events with `listened_at >= today-00:00 UTC` are included, which
is precisely "listened today." Side-effect check: I verified both sides of the midnight boundary
with a controlled test — a friend who played 30 min before midnight is correctly excluded, and
a friend who played 30 min after midnight is still shown. I also confirmed I did **not** touch
`get_activity_feed`, which is intentionally unfiltered by recency (its docstring says so) and
does not use the cutoff. The `>=` comparison keeps an event landing exactly at 00:00:00 in
"today," which is correct. (Note: the boundary is UTC, matching how the app stores all
timestamps; a per-user local-midnight boundary would be a larger feature, out of scope for a
targeted bug fix.)
