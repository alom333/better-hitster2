import os
import random
import time
import requests
import pandas as pd
from flask import Flask, redirect, request, session, jsonify, render_template
from urllib.parse import urlencode
import base64

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-key")

SPOTIFY_CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET")
REDIRECT_URI = os.environ.get("REDIRECT_URI")
PLAYLIST_ID = os.environ.get("PLAYLIST_ID")

# ── Billboard (American songs) ──────────────────────────────────────────────

import billboard

def get_random_american_song():
    year = random.randint(2006, 2024)
    try:
        chart = billboard.ChartData("hot-100-songs", year=f"{year}")
        top_50 = chart[:50]
        if not top_50:
            return None
        song = random.choice(top_50)
        return {
            "title": song.title,
            "artist": song.artist,
            "year": year,
            "source": "american"
        }
    except Exception as e:
        print(f"Billboard error: {e}")
        return None


# ── MusicBrainz year lookup ─────────────────────────────────────────────────

def get_real_year_musicbrainz(song_name, artist_name):
    try:
        res = requests.get(
            "https://musicbrainz.org/ws/2/recording",
            params={
                "query": f'recording:"{song_name}" AND artist:"{artist_name}"',
                "limit": 5,
                "fmt": "json",
            },
            headers={"User-Agent": "MusicTimeMachine/1.0 (music@timemachine.app)"},
            timeout=5
        )
        res.raise_for_status()
        recordings = res.json().get("recordings", [])
        if not recordings:
            return None
        years = []
        for r in recordings:
            date = r.get("first-release-date", "")
            if date and len(date) >= 4:
                try:
                    years.append(int(date[:4]))
                except ValueError:
                    pass
        return min(years) if years else None
    except Exception as e:
        print(f"MusicBrainz error: {e}")
        return None


# ── Hebrew CSV playlist ─────────────────────────────────────────────────────

_hebrew_tracks = None

def load_hebrew_tracks():
    global _hebrew_tracks
    if _hebrew_tracks is not None:
        return _hebrew_tracks
    csv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "israel.csv")
    try:
        df = pd.read_csv(csv_path)
        tracks = []
        for _, row in df.iterrows():
            name = (row.get("Track Name") or row.get("Name") or row.get("title") or "")
            artist = (row.get("Artist Name(s)") or row.get("Artist") or row.get("artist") or "")
            if name and artist:
                tracks.append({"title": str(name).strip(), "artist": str(artist).strip()})
        _hebrew_tracks = tracks
        print(f"Loaded {len(tracks)} Hebrew tracks from CSV")
        return _hebrew_tracks
    except Exception as e:
        print(f"CSV load error: {e}")
        return []

def get_random_hebrew_song():
    tracks = load_hebrew_tracks()
    if not tracks:
        return None
    track = random.choice(tracks)
    time.sleep(0.5)  # MusicBrainz rate limit
    real_year = get_real_year_musicbrainz(track["title"], track["artist"])
    return {
        "title": track["title"],
        "artist": track["artist"],
        "year": real_year,
        "source": "hebrew"
    }


# ── Spotify helpers ─────────────────────────────────────────────────────────

def get_spotify_token():
    """Client credentials token for search (no user needed)"""
    creds = base64.b64encode(f"{SPOTIFY_CLIENT_ID}:{SPOTIFY_CLIENT_SECRET}".encode()).decode()
    res = requests.post(
        "https://accounts.spotify.com/api/token",
        headers={"Authorization": f"Basic {creds}"},
        data={"grant_type": "client_credentials"},
        timeout=10
    )
    res.raise_for_status()
    return res.json()["access_token"]

def search_spotify_track(title, artist, token):
    res = requests.get(
        "https://api.spotify.com/v1/search",
        headers={"Authorization": f"Bearer {token}"},
        params={"q": f"track:{title} artist:{artist}", "type": "track", "limit": 1},
        timeout=10
    )
    res.raise_for_status()
    items = res.json().get("tracks", {}).get("items", [])
    if not items:
        return None
    t = items[0]
    # Extract year from Spotify release_date (format: YYYY, YYYY-MM, or YYYY-MM-DD)
    release_date = t["album"].get("release_date", "")
    spotify_year = int(release_date[:4]) if release_date and len(release_date) >= 4 else None
    return {
        "spotify_uri": t["uri"],
        "album_image": t["album"]["images"][0]["url"] if t["album"]["images"] else None,
        "spotify_id": t["id"],
        "spotify_year": spotify_year
    }

def play_spotify_track(uri, access_token):
    res = requests.put(
        "https://api.spotify.com/v1/me/player/play",
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
        json={"uris": [uri]},
        timeout=10
    )
    return res.status_code in (200, 204)

def pause_spotify(access_token):
    res = requests.put(
        "https://api.spotify.com/v1/me/player/pause",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10
    )
    return res.status_code in (200, 204)

def resume_spotify(access_token):
    res = requests.put(
        "https://api.spotify.com/v1/me/player/play",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10
    )
    return res.status_code in (200, 204)


# ── Routes ──────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    logged_in = "access_token" in session
    return render_template("index.html", logged_in=logged_in)

@app.route("/login")
def login():
    params = urlencode({
        "client_id": SPOTIFY_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": "user-read-playback-state user-modify-playback-state streaming",
    })
    return redirect(f"https://accounts.spotify.com/authorize?{params}")

@app.route("/callback")
def callback():
    code = request.args.get("code")
    if not code:
        return redirect("/")
    res = requests.post(
        "https://accounts.spotify.com/api/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": SPOTIFY_CLIENT_ID,
            "client_secret": SPOTIFY_CLIENT_SECRET,
        },
        timeout=10
    )
    data = res.json()
    session["access_token"] = data.get("access_token")
    session["refresh_token"] = data.get("refresh_token")
    return redirect("/")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

@app.route("/api/random-song", methods=["POST"])
def random_song():
    data = request.get_json()
    # israeli_ratio: 0 = all American, 100 = all Israeli
    israeli_ratio = int(data.get("israeli_ratio", 0))

    pick_israeli = random.randint(1, 100) <= israeli_ratio

    song = None
    if pick_israeli:
        song = get_random_hebrew_song()
        if not song:  # fallback to american if CSV empty
            song = get_random_american_song()
    else:
        song = get_random_american_song()
        if not song:
            return jsonify({"error": "Could not fetch song"}), 500

    # Search Spotify for the track (for playback + album art)
    try:
        token = get_spotify_token()
        spotify_data = search_spotify_track(song["title"], song["artist"], token)
    except Exception as e:
        print(f"Spotify search error: {e}")
        spotify_data = None

    # Play it if user is logged in
    if spotify_data and "access_token" in session:
        try:
            play_spotify_track(spotify_data["spotify_uri"], session["access_token"])
        except Exception as e:
            print(f"Playback error: {e}")

    # For Hebrew songs: MusicBrainz year first, fall back to Spotify year
    final_year = song["year"]
    year_source = "musicbrainz"
    if final_year is None and spotify_data and spotify_data.get("spotify_year"):
        final_year = spotify_data["spotify_year"]
        year_source = "spotify"

    return jsonify({
        "title": song["title"],
        "artist": song["artist"],
        "year": final_year,
        "year_source": year_source,
        "source": song["source"],
        "album_image": spotify_data["album_image"] if spotify_data else None,
        "spotify_uri": spotify_data["spotify_uri"] if spotify_data else None,
    })

@app.route("/api/pause", methods=["POST"])
def pause():
    if "access_token" not in session:
        return jsonify({"error": "Not logged in"}), 401
    pause_spotify(session["access_token"])
    return jsonify({"ok": True})

@app.route("/api/resume", methods=["POST"])
def resume():
    if "access_token" not in session:
        return jsonify({"error": "Not logged in"}), 401
    resume_spotify(session["access_token"])
    return jsonify({"ok": True})

@app.route("/api/status")
def status():
    return jsonify({"logged_in": "access_token" in session})

if __name__ == "__main__":
    app.run(debug=True)
