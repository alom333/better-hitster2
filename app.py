import os
import random
from flask import Flask, session, request, redirect, render_template, jsonify
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from spotipy.cache_handler import FlaskSessionCacheHandler

app = Flask(__name__)
# Render needs a secret key for session management. We'll use a random string.
app.config['SECRET_KEY'] = os.urandom(64)

# Environment variables from Render
CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID")
CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET")
REDIRECT_URI = os.environ.get("REDIRECT_URI")
PLAYLIST_ID = os.environ.get("PLAYLIST_ID")

# Scopes needed to control playback and read playlists
SCOPE = "user-modify-playback-state user-read-playback-state playlist-read-private"

def get_spotify_oauth():
    cache_handler = FlaskSessionCacheHandler(session)
    return SpotifyOAuth(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        redirect_uri=REDIRECT_URI,
        scope=SCOPE,
        cache_handler=cache_handler,
        show_dialog=True
    )

@app.route('/')
def home():
    sp_oauth = get_spotify_oauth()
    is_logged_in = sp_oauth.validate_token(sp_oauth.cache_handler.get_cached_token()) is not None
    return render_template('index.html', is_logged_in=is_logged_in)

@app.route('/login')
def login():
    sp_oauth = get_spotify_oauth()
    auth_url = sp_oauth.get_authorize_url()
    return redirect(auth_url)

@app.route('/callback')
def callback():
    sp_oauth = get_spotify_oauth()
    session.clear()
    code = request.args.get('code')
    try:
        sp_oauth.get_access_token(code)
    except Exception as e:
        print(f"Error getting token: {e}")
    return redirect('/')

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')

@app.route('/play_random')
def play_random():
    sp_oauth = get_spotify_oauth()
    if not sp_oauth.validate_token(sp_oauth.cache_handler.get_cached_token()):
        return jsonify({"error": "Not logged in"}), 401

    sp = spotipy.Spotify(auth_manager=sp_oauth)

    try:
        # 1. Get total tracks in the playlist to pick a random offset
        playlist_info = sp.playlist(PLAYLIST_ID, fields="tracks.total")
        total_tracks = playlist_info['tracks']['total']
        
        if total_tracks == 0:
            return jsonify({"error": "Playlist is empty!"}), 400

        random_offset = random.randint(0, total_tracks - 1)

        # 2. Fetch the specific random track
        track_items = sp.playlist_items(PLAYLIST_ID, limit=1, offset=random_offset)
        track = track_items['items'][0]['track']
        
        # 3. Extract information
        track_uri = track['uri']
        song_name = track['name']
        artist_name = track['artists'][0]['name']
        album_pic = track['album']['images'][0]['url'] if track['album']['images'] else ""
        release_date = track['album']['release_date']
        year = release_date.split('-')[0] if release_date else "Unknown"

        # 4. Play the track on the active device
        try:
            sp.start_playback(uris=[track_uri])
        except spotipy.SpotifyException as e:
            if "NO_ACTIVE_DEVICE" in str(e) or e.http_status == 404:
                return jsonify({"error": "No active Spotify device found. Please open Spotify on your phone or computer and try again!"}), 400
            else:
                return jsonify({"error": "Requires Spotify Premium to control playback."}), 403

        # Return info (hidden by frontend until Reveal is clicked)
        return jsonify({
            "song_name": song_name,
            "artist": artist_name,
            "year": year,
            "album_pic": album_pic
        })

    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"error": "Something went wrong fetching the song."}), 500

if __name__ == '__main__':
    # Render binds to port 10000 by default, but standard Flask is 5000. 
    # Using 0.0.0.0 is required for Render web services.
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
