import threading
from queue import Queue

# 1. Create the 'Storage Room' for songs
# This ensures clicking 'Next' is instant
song_stack = Queue(maxsize=15)

def fill_song_stack_forever():
    """This runs in the background to find Elton John/Beatles-style hits."""
    while True:
        if not song_stack.full():
            # Pick a random year to ensure decade variety
            random_year = random.randint(1960, 2020)
            
            # 1. Ask Spotify for a 'Hit' (Popularity > 50) from that year
            # This is the "Spotify Hit" logic that avoids random rap
            song = fetch_spotify_hit(random_year)
            
            if song:
                # 2. Immediately verify the 'True' year with MusicBrainz
                # Using raw requests to avoid "ModuleNotFoundError"
                real_year = get_year_from_musicbrainz(song['title'], song['artist'])
                if real_year:
                    song['year'] = real_year
                
                # 3. Add to the stack for the user
                song_stack.put(song)
                
                # Respect MusicBrainz's 1-request-per-second rule
                time.sleep(1.1)
        else:
            time.sleep(5) # Wait if the stack is full

def fetch_spotify_hit(year):
    """Searches for popular tracks from a specific year."""
    token = get_spotify_token()
    # Search filter: 'year:1985'
    query = f"year:{year}"
    try:
        res = requests.get(
            "https://api.spotify.com/v1/search", # Using standard API
            headers={"Authorization": f"Bearer {token}"},
            params={"q": query, "type": "track", "limit": 10, "market": "US"}
        )
        items = res.json().get('tracks', {}).get('items', [])
        if not items: return None
        
        # Filter for popularity to get the 'Classic' sound
        hits = [t for t in items if t.get('popularity', 0) > 55]
        selected = random.choice(hits if hits else items)
        
        return {
            "title": selected["name"],
            "artist": selected["artists"][0]["name"],
            "year": year,
            "spotify_uri": selected["uri"],
            "album_image": selected["album"]["images"][0]["url"] if selected["album"]["images"] else None
        }
    except:
        return None

def get_year_from_musicbrainz(title, artist):
    """The 'True Year' logic using raw requests."""
    try:
        url = "https://musicbrainz.org/ws/2/recording"
        params = {"query": f'recording:"{title}" AND artist:"{artist}"', "fmt": "json"}
        headers = {"User-Agent": "TimeMachineApp/1.0 (your@email.com)"}
        
        r = requests.get(url, params=params, headers=headers, timeout=5)
        data = r.json().get("recordings", [])
        if not data: return None
        
        # Find the earliest release date in the list
        years = []
        for rec in data:
            date = rec.get("first-release-date", "")
            if date and len(date) >= 4:
                years.append(int(date[:4]))
        return min(years) if years else None
    except:
        return None

# START THE BACKGROUND WORKER
daemon = threading.Thread(target=fill_song_stack_forever, daemon=True)
daemon.start()
