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
SCOPE = "user-modify-playback-state user-read-playback-state playlist-read-private playlist-read-collaborative"

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
    token_info = sp_oauth.get_cached_token()
    
    if not token_info:
        return jsonify({"error": "Not logged in"}), 401

    sp = spotipy.Spotify(auth=token_info['access_token'])

    try:
        # 1. Fetch playlist items directly (this is more reliable than sp.playlist)
        # We ask for a limit of 1 just to get the 'total' count safely.
        results = sp.playlist_items(PLAYLIST_ID, fields='total', limit=1)
        
        if 'total' not in results:
            print(f"DEBUG: Response from Spotify: {results}")
            return jsonify({"error": "Could not find 'total' tracks. Check if PLAYLIST_ID is correct and public."}), 400
            
        total_tracks = results['total']
        
        if total_tracks == 0:
            return jsonify({"error": "This playlist is empty!"}), 400

        # 2. Pick a random song
        random_offset = random.randint(0, total_tracks - 1)
        
        # 3. Get the track at that offset
        track_data = sp.playlist_items(
            PLAYLIST_ID, 
            limit=1, 
            offset=random_offset,
            fields='items(track(name, uri, album(name, images, release_date), artists(name)))'
        )
        
        track = track_data['items'][0]['track']
        
        # Extract details
        track_uri = track['uri']
        song_name = track['name']
        artist_name = track['artists'][0]['name']
        album_pic = track['album']['images'][0]['url'] if track['album']['images'] else ""
        release_date = track['album']['release_date']
        year = release_date.split('-')[0] if release_date else "????"

        # 4. Try to play
        try:
            sp.start_playback(uris=[track_uri])
        except Exception as e:
            # If it's a 'No Active Device' error
            return jsonify({"error": "Open Spotify on your phone first!", "details": str(e)}), 400

        return jsonify({
            "song_name": song_name,
            "artist": artist_name,
            "year": year,
            "album_pic": album_pic
        })

    except Exception as e:
        print(f"CRITICAL ERROR: {str(e)}")
        return jsonify({"error": f"Backend Error: {str(e)}"}), 500

if __name__ == '__main__':
    # Render binds to port 10000 by default, but standard Flask is 5000. 
    # Using 0.0.0.0 is required for Render web services.
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
