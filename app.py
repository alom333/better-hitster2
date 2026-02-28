import os
import random
import requests
from flask import Flask, redirect, request, session, jsonify, render_template
from urllib.parse import urlencode
from songs import SONGS

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-in-production")

SPOTIFY_CLIENT_ID     = os.environ.get("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET")
REDIRECT_URI          = os.environ.get("REDIRECT_URI")

SPOTIFY_AUTH_URL  = "https://accounts.spotify.com/authorize"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_API_BASE  = "https://api.spotify.com/v1"

SCOPES = "user-read-playback-state user-modify-playback-state"


# ── Auth routes ────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


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
    code  = request.args.get("code")
    error = request.args.get("error")

    if error or not code:
        return redirect("/?error=access_denied")

    resp = requests.post(
        SPOTIFY_TOKEN_URL,
        data={
            "grant_type":    "authorization_code",
            "code":          code,
            "redirect_uri":  REDIRECT_URI,
            "client_id":     SPOTIFY_CLIENT_ID,
            "client_secret": SPOTIFY_CLIENT_SECRET,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    if resp.status_code != 200:
        return redirect("/?error=token_exchange_failed")

    tokens = resp.json()
    session["access_token"]  = tokens["access_token"]
    session["refresh_token"] = tokens.get("refresh_token")
    return redirect("/")


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


# ── Helpers ────────────────────────────────────────────────────────────────────

def refresh_access_token():
    refresh_token = session.get("refresh_token")
    if not refresh_token:
        return False
    resp = requests.post(
        SPOTIFY_TOKEN_URL,
        data={
            "grant_type":    "refresh_token",
            "refresh_token": refresh_token,
            "client_id":     SPOTIFY_CLIENT_ID,
            "client_secret": SPOTIFY_CLIENT_SECRET,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    if resp.status_code == 200:
        tokens = resp.json()
        session["access_token"] = tokens["access_token"]
        if "refresh_token" in tokens:
            session["refresh_token"] = tokens["refresh_token"]
        return True
    return False


def auth_headers():
    return {"Authorization": f"Bearer {session['access_token']}"}


def spotify_get(endpoint):
    resp = requests.get(f"{SPOTIFY_API_BASE}{endpoint}", headers=auth_headers())
    if resp.status_code == 401 and refresh_access_token():
        resp = requests.get(f"{SPOTIFY_API_BASE}{endpoint}", headers=auth_headers())
    return resp


def spotify_put(endpoint, body=None):
    resp = requests.put(
        f"{SPOTIFY_API_BASE}{endpoint}",
        headers={**auth_headers(), "Content-Type": "application/json"},
        json=body,
    )
    if resp.status_code == 401 and refresh_access_token():
        resp = requests.put(
            f"{SPOTIFY_API_BASE}{endpoint}",
            headers={**auth_headers(), "Content-Type": "application/json"},
            json=body,
        )
    return resp


# ── API routes ─────────────────────────────────────────────────────────────────

@app.route("/api/status")
def status():
    if "access_token" not in session:
        return jsonify({"logged_in": False})
    resp = spotify_get("/me")
    if resp.status_code != 200:
        session.clear()
        return jsonify({"logged_in": False})
    data = resp.json()
    return jsonify({"logged_in": True, "display_name": data.get("display_name", "")})


@app.route("/api/play_random")
def play_random():
    if "access_token" not in session:
        return jsonify({"error": "Not logged in"}), 401

    # Pick a random song, avoiding the last one played
    last_id = session.get("last_track_id")
    pool    = [s for s in SONGS if s["id"] != last_id] if len(SONGS) > 1 else SONGS
    song    = random.choice(pool)
    session["last_track_id"] = song["id"]

    # Get user's available devices
    resp = spotify_get("/me/player/devices")
    if resp.status_code != 200:
        return jsonify({"error": "Could not reach Spotify. Try logging out and back in."}), 500

    devices = resp.json().get("devices", [])
    if not devices:
        return jsonify({"error": "No active Spotify device found. Open Spotify on your phone or desktop first."}), 404

    # Prefer the currently active device, else take the first available
    device = next((d for d in devices if d.get("is_active")), devices[0])

    # Play the song
    play_resp = spotify_put(
        f"/me/player/play?device_id={device['id']}",
        {"uris": [song["uri"]]},
    )

    if play_resp.status_code not in (200, 204):
        app.logger.error(f"Playback failed: {play_resp.status_code} {play_resp.text}")
        return jsonify({"error": f"Could not start playback. Make sure Spotify is open and active. (status {play_resp.status_code})"}), 500

    return jsonify({"success": True, "track": song})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
