import os
import random
import requests
from flask import Flask, redirect, request, session, jsonify, render_template
from urllib.parse import urlencode

app = Flask(__name__)
app.secret_key = os.urandom(24)

# Spotify config from environment variables (set in Render)
SPOTIFY_CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET")
REDIRECT_URI = os.environ.get("REDIRECT_URI")
PLAYLIST_ID = os.environ.get("PLAYLIST_ID")

SPOTIFY_AUTH_URL = "https://accounts.spotify.com/authorize"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_API_BASE = "https://api.spotify.com/v1"

SCOPES = "user-read-playback-state user-modify-playback-state playlist-read-private playlist-read-collaborative streaming"


@app.route("/")
def index():
    logged_in = "access_token" in session
    return render_template("index.html", logged_in=logged_in)


@app.route("/login")
def login():
    params = {
        "client_id": SPOTIFY_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "show_dialog": True,
    }
    return redirect(f"{SPOTIFY_AUTH_URL}?{urlencode(params)}")


@app.route("/callback")
def callback():
    code = request.args.get("code")
    error = request.args.get("error")

    if error:
        return redirect("/?error=access_denied")

    if not code:
        return redirect("/?error=no_code")

    # Exchange code for tokens
    response = requests.post(
        SPOTIFY_TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": SPOTIFY_CLIENT_ID,
            "client_secret": SPOTIFY_CLIENT_SECRET,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    if response.status_code != 200:
        return redirect("/?error=token_exchange_failed")

    tokens = response.json()
    session["access_token"] = tokens["access_token"]
    session["refresh_token"] = tokens.get("refresh_token")
    return redirect("/")


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


def refresh_token_if_needed():
    """Refresh the access token using the refresh token."""
    refresh_token = session.get("refresh_token")
    if not refresh_token:
        return False

    response = requests.post(
        SPOTIFY_TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": SPOTIFY_CLIENT_ID,
            "client_secret": SPOTIFY_CLIENT_SECRET,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    if response.status_code == 200:
        tokens = response.json()
        session["access_token"] = tokens["access_token"]
        if "refresh_token" in tokens:
            session["refresh_token"] = tokens["refresh_token"]
        return True
    return False


def spotify_get(endpoint, params=None):
    """Make authenticated GET request to Spotify API, refreshing token if needed."""
    access_token = session.get("access_token")
    if not access_token:
        return None, 401

    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get(f"{SPOTIFY_API_BASE}{endpoint}", headers=headers, params=params)

    if response.status_code == 401:
        if refresh_token_if_needed():
            headers["Authorization"] = f"Bearer {session['access_token']}"
            response = requests.get(f"{SPOTIFY_API_BASE}{endpoint}", headers=headers, params=params)
        else:
            return None, 401

    return response.json() if response.status_code == 200 else None, response.status_code


def spotify_put(endpoint, json_data=None):
    """Make authenticated PUT request to Spotify API."""
    access_token = session.get("access_token")
    if not access_token:
        return 401

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    response = requests.put(f"{SPOTIFY_API_BASE}{endpoint}", headers=headers, json=json_data)

    if response.status_code == 401:
        if refresh_token_if_needed():
            headers["Authorization"] = f"Bearer {session['access_token']}"
            response = requests.put(f"{SPOTIFY_API_BASE}{endpoint}", headers=headers, json=json_data)

    return response.status_code


@app.route("/api/status")
def status():
    if "access_token" not in session:
        return jsonify({"logged_in": False})

    data, code = spotify_get("/me")
    if code == 401 or data is None:
        session.clear()
        return jsonify({"logged_in": False})

    return jsonify({"logged_in": True, "display_name": data.get("display_name", "")})


@app.route("/api/play_random")
def play_random():
    if "access_token" not in session:
        return jsonify({"error": "Not logged in"}), 401

    # Get all tracks from the playlist (handle pagination)
    tracks = []
    url = f"/playlists/{PLAYLIST_ID}/tracks"
    params = {"limit": 100, "fields": "items(track(id,name,artists,album,duration_ms)),next,total"}

    while url:
        data, code = spotify_get(url, params)
        if not data or code != 200:
            return jsonify({"error": "Could not fetch playlist"}), 500

        for item in data.get("items", []):
            track = item.get("track")
            if track and track.get("id"):
                tracks.append(track)

        next_url = data.get("next")
        if next_url:
            # Extract relative path
            url = next_url.replace(SPOTIFY_API_BASE, "")
            params = None
        else:
            url = None

    if not tracks:
        return jsonify({"error": "Playlist is empty"}), 404

    # Pick a random track (avoid repeating the last one if possible)
    last_track_id = session.get("last_track_id")
    available = [t for t in tracks if t["id"] != last_track_id] if len(tracks) > 1 else tracks
    track = random.choice(available)
    session["last_track_id"] = track["id"]

    # Get active device
    devices_data, _ = spotify_get("/me/player/devices")
    devices = devices_data.get("devices", []) if devices_data else []

    if not devices:
        return jsonify({"error": "No active Spotify device found. Please open Spotify on your phone or desktop."}), 404

    # Prefer active device, else first available
    active_device = next((d for d in devices if d.get("is_active")), devices[0])
    device_id = active_device["id"]

    # Play the track
    status_code = spotify_put(
        f"/me/player/play?device_id={device_id}",
        {"uris": [f"spotify:track:{track['id']}"]},
    )

    if status_code not in (200, 204):
        return jsonify({"error": f"Could not start playback (status {status_code}). Make sure Spotify is open and active."}), 500

    # Build track info for reveal
    album = track.get("album", {})
    artists = [a["name"] for a in track.get("artists", [])]
    images = album.get("images", [])
    album_image = images[0]["url"] if images else None
    release_year = album.get("release_date", "")[:4]

    return jsonify({
        "success": True,
        "track": {
            "id": track["id"],
            "name": track["name"],
            "artists": artists,
            "album": album.get("name", ""),
            "album_image": album_image,
            "year": release_year,
        },
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
