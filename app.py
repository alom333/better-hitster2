import os
import random
import time
import requests
import pandas as pd
import threading
import base64
from queue import Queue, Empty
from flask import Flask, redirect, request, session, jsonify, render_template
from urllib.parse import urlencode

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-key")

# Spotify Environment Variables
SPOTIFY_CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET")
REDIRECT_URI = os.environ.get("REDIRECT_URI")

# ── The Stacks (Queues) ─────────────────────────────────────────────────────
# These ensure the app is lightning fast by pre-loading songs.
american_stack = Queue(maxsize=15)
hebrew_stack = Queue(maxsize=15)

# ── MusicBrainz (Your Original Function) ────────────────────────────────────

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

# ── Spotify Helpers ─────────────────────────────────────────────────────────

def get_spotify_token():
    """Gets a Client Credentials token for background searching."""
    creds = base64.b64encode(f"{SPOTIFY_CLIENT_ID}:{SPOTIFY_CLIENT_SECRET}".encode()).decode()
    res = requests.post(
        "https://accounts.spotify.com/api/token",
        headers={"Authorization": f"Basic {creds}"},
        data={"grant_type": "client_credentials"},
        timeout=10
    )
    res.raise_for_status()
    return res.json()["access_token"]

def fetch_spotify_hit_by_year(year):
    """
    Finds a 'Hit' from a specific year.
    Filtering by popularity > 50 ensures we get Elton John/Beatles level tracks.
    """
    try:
        token = get_spotify_token()
        res = requests.get(
            "https://api.spotify.com/v1/search",
            headers={"Authorization": f"Bearer {token}"},
            params={
                "q": f"year:{year}",
                "type": "track",
                "limit": 20,
                "market": "US"
            },
            timeout=10
        )
        items = res.json().get("tracks", {}).get("items", [])
        if not items: return None

        # Filter for popularity to get the 'Classic' sound
        hits = [t for t in items if t.get("popularity", 0) > 50]
        selected = random.choice(hits if hits else items)
        
        return {
            "title": selected["name"],
            "artist": selected["artists"][0]["name"],
            "spotify_uri": selected["uri"],
            "album_image": selected["album"]["images"][0]["url"] if selected["album"]["images"] else None,
            "source": "american"
        }
    except Exception as e:
        print(f"Spotify hit fetch error: {e}")
        return None

# ── Hebrew Logic (CSV) ──────────────────────────────────────────────────────

_hebrew_tracks = None
def load_hebrew_tracks():
    global _hebrew_tracks
    if _hebrew_tracks is not None: return _hebrew_tracks
    csv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "israel.csv")
    try:
        df = pd.read_csv(csv_path)
        # Handle various possible column names in CSV
        _hebrew_tracks = []
        for _, row in df.iterrows():
            name = row.get("Track Name") or row.get("Name") or row.get("title")
            artist = row.get("Artist Name(s)") or row.get("Artist") or row.get("artist")
            if name and artist:
                _hebrew_tracks.append({"title": str(name).strip(), "artist": str(artist).strip()})
        return _hebrew_tracks
    except Exception as e:
        print(f"CSV load error: {e}")
        return []

# ── The Background Worker ───────────────────────────────────────────────────

def background_worker():
    """Background loop that fills the stacks so the user never has to wait."""
    while True:
        # 1. Fill American Stack (Spotify Hits + MB Year)
        if not american_stack.full():
            target_year = random.randint(1955, 2024)
            song = fetch_spotify_hit_by_year(target_year)
            if song:
                # Use your MusicBrainz logic to find the TRUE year
                real_year = get_real_year_musicbrainz(song["title"], song["artist"])
                song["year"] = real_year or target_year
                american_stack.put(song)
                time.sleep(1.1) # Respect MusicBrainz 1-req-per-sec rule

        # 2. Fill Hebrew Stack (CSV + MB Year + Spotify Image)
        if not hebrew_stack.full():
            tracks = load_hebrew_tracks()
            if tracks:
                t = random.choice(tracks)
                real_year = get_real_year_musicbrainz(t["title"], t["artist"])
                if real_year:
                    # Quick Spotify search to get the album art and URI
                    token = get_spotify_token()
                    s_res = requests.get("https://api.spotify.com/v1/search", 
                                       headers={"Authorization": f"Bearer {token}"},
                                       params={"q": f"track:{t['title']} artist:{t['artist']}", "type": "track", "limit": 1})
                    items = s_res.json().get("tracks", {}).get("items", [])
                    img = items[0]["album"]["images"][0]["url"] if items else None
                    uri = items[0]["uri"] if items else None
                    
                    hebrew_stack.put({
                        "title": t["title"], "artist": t["artist"], "year": real_year,
                        "album_image": img, "spotify_uri": uri, "source": "hebrew"
                    })
                    time.sleep(1.1)
        time.sleep(2)

# Start the worker thread
threading.Thread(target=background_worker, daemon=True).start()

# ── Routes ──────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html", logged_in="access_token" in session)

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
    res = requests.post(
        "https://accounts.spotify.com/api/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": SPOTIFY_CLIENT_ID,
            "client_secret": SPOTIFY_CLIENT_SECRET,
        }
    )
    data = res.json()
    session["access_token"] = data.get("access_token")
    return redirect("/")

@app.route("/api/random-song", methods=["POST"])
def random_song():
    data = request.get_json()
    israeli_ratio = int(data.get("israeli_ratio", 0))
    pick_israeli = random.randint(1, 100) <= israeli_ratio

    try:
        stack = hebrew_stack if pick_israeli else american_stack
        # Pop from queue - timeout if empty
        song = stack.get(timeout=3)
        
        # Trigger Playback if logged in
        if "access_token" in session and song.get("spotify_uri"):
            requests.put("https://api.spotify.com/v1/me/player/play",
                         headers={"Authorization": f"Bearer {session['access_token']}"},
                         json={"uris": [song["spotify_uri"]]})
            
        return jsonify(song)
    except Empty:
        return jsonify({"error": "Stacking songs, try again in 3 seconds..."}), 503

@app.route("/api/pause", methods=["POST"])
def pause():
    if "access_token" in session:
        requests.put("https://api.spotify.com/v1/me/player/pause", 
                     headers={"Authorization": f"Bearer {session['access_token']}"})
    return jsonify({"ok": True})

if __name__ == "__main__":
    app.run(debug=True)
