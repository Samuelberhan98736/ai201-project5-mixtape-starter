"""
services/search_service.py — Mixtape

Handles song search logic.
"""

from app import db
from models import Song


def search_songs(query: str) -> list[dict]:
    """
    Search for songs by title or artist name.

    Returns all songs where the title or artist contains the query string
    (case-insensitive), along with their associated tags.

    Args:
        query: The search string to match against title and artist fields.

    Returns:
        A list of song dicts. Each dict includes all song fields plus a
        'tags' list of tag name strings.
    """
    # NOTE: We intentionally do NOT join song_tags here. The search only filters on
    # title/artist, so the join adds nothing — but because a song has one song_tags row
    # per tag, joining multiplies the result by the tag count, producing duplicate Song
    # rows (a 3-tag song comes back 3 times). Tags are loaded separately by Song.to_dict()
    # via the lazy="subquery" relationship, so dropping the join loses no data.
    results = (
        db.session.query(Song)
        .filter(
            db.or_(
                Song.title.ilike(f"%{query}%"),
                Song.artist.ilike(f"%{query}%"),
            )
        )
        .all()
    )

    return [song.to_dict() for song in results]


def get_song(song_id: str) -> dict:
    """
    Get a single song by ID.

    Args:
        song_id: The UUID of the song.

    Returns:
        A song dict, or raises ValueError if not found.
    """
    song = db.session.get(Song, song_id)
    if not song:
        raise ValueError(f"Song {song_id} not found")
    return song.to_dict()
