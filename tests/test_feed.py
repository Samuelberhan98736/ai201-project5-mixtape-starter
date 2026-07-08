"""
tests/test_feed.py — Mixtape

Regression tests for Issue #2: "Friends Listening Now" must show only friends who
listened *today* (this calendar day), not friends within a rolling 24-hour window.

Before the fix, get_friends_listening_now used a cutoff of `now - 24h`, so a friend who
played at ~11pm the previous night still appeared in the feed the next morning. These
tests pin the calendar-day boundary at midnight UTC.
"""

import pytest
from datetime import datetime, timedelta, timezone
from app import create_app, db
from models import User, Song, ListeningEvent, friendships
from services.feed_service import get_friends_listening_now


@pytest.fixture
def app():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


def _make_user(username):
    u = User(username=username, email=f"{username}@example.com")
    db.session.add(u)
    db.session.flush()
    return u


def _befriend(a, b):
    db.session.execute(friendships.insert().values(user_id=a.id, friend_id=b.id))


def _listen(user, song, when):
    db.session.add(ListeningEvent(user_id=user.id, song_id=song.id, listened_at=when))


def test_friend_from_last_night_is_excluded(app):
    """
    A friend whose most recent listen was before today's midnight (e.g. 11pm last
    night) must NOT appear in 'listening now'. This is the exact Issue #2 scenario.
    """
    with app.app_context():
        me = _make_user("nova")
        darius = _make_user("darius")
        _befriend(me, darius)
        song = Song(title="Late Night", artist="A", shared_by=me.id)
        db.session.add(song)
        db.session.flush()

        now = datetime.now(timezone.utc)
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        # 30 minutes before today's midnight = "last night"
        _listen(darius, song, midnight - timedelta(minutes=30))
        db.session.commit()

        feed = get_friends_listening_now(me.id)
        usernames = [entry["friend"]["username"] for entry in feed]
        assert "darius" not in usernames


def test_friend_from_this_morning_is_included(app):
    """A friend who listened after midnight today should still appear (other side of the boundary)."""
    with app.app_context():
        me = _make_user("nova")
        simone = _make_user("simone")
        _befriend(me, simone)
        song = Song(title="Morning", artist="A", shared_by=me.id)
        db.session.add(song)
        db.session.flush()

        now = datetime.now(timezone.utc)
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        # 30 minutes after midnight = earlier today
        _listen(simone, song, midnight + timedelta(minutes=30))
        db.session.commit()

        feed = get_friends_listening_now(me.id)
        usernames = [entry["friend"]["username"] for entry in feed]
        assert "simone" in usernames
