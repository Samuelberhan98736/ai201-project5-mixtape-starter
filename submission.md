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
