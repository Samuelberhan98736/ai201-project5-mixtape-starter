"""
tests/test_notifications.py — Mixtape

Regression tests for Issue #4: rating a shared song must create a notification for the
song's original sharer, mirroring the playlist-add notification.

Before the fix, rate_song() saved the Rating but never called create_notification(), so
the sharer was never told their song had been rated.
"""

import pytest
from app import create_app, db
from models import User, Song, Notification
from services.notification_service import rate_song, get_notifications


@pytest.fixture
def app():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


@pytest.fixture
def sharer_and_song(app):
    with app.app_context():
        owner = User(username="aaliya", email="aaliya@example.com")
        rater = User(username="kenji", email="kenji@example.com")
        db.session.add_all([owner, rater])
        db.session.flush()
        song = Song(title="My Song", artist="Some Artist", shared_by=owner.id)
        db.session.add(song)
        db.session.commit()
        yield {"owner": owner, "rater": rater, "song": song}


def test_rating_creates_notification_for_sharer(app, sharer_and_song):
    """A friend rating a shared song creates exactly one notification for the sharer."""
    with app.app_context():
        owner = sharer_and_song["owner"]
        rater = sharer_and_song["rater"]
        song = sharer_and_song["song"]

        rate_song(rater.id, song.id, 5)

        notifs = get_notifications(owner.id)
        assert len(notifs) == 1
        assert notifs[0]["type"] == "song_rated"
        assert "kenji" in notifs[0]["body"]
        assert song.title in notifs[0]["body"]


def test_rating_own_song_creates_no_notification(app, sharer_and_song):
    """Rating your own shared song should not notify yourself."""
    with app.app_context():
        owner = sharer_and_song["owner"]
        song = sharer_and_song["song"]

        rate_song(owner.id, song.id, 4)

        assert get_notifications(owner.id) == []


def test_updating_a_rating_does_not_duplicate_the_rating_row(app, sharer_and_song):
    """Re-rating an already-rated song updates the score rather than erroring."""
    with app.app_context():
        rater = sharer_and_song["rater"]
        song = sharer_and_song["song"]

        rate_song(rater.id, song.id, 3)
        updated = rate_song(rater.id, song.id, 5)
        assert updated.score == 5
