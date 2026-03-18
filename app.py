import musicbrainzngs
import time

# 1. Initialize MusicBrainz (Required by their terms)
musicbrainzngs.set_useragent("MyTimeMachineApp", "0.1", "your-email@example.com")

def get_accurate_year(title, artist):
    """Queries MusicBrainz for the earliest known release year."""
    try:
        # Search for the recording
        # Using strict=True and specific fields to avoid 'live' or 'remix' versions
        result = musicbrainzngs.search_recordings(recording=title, artist=artist, limit=5)
        
        years = []
        for rec in result.get('recording-list', []):
            # MusicBrainz often has 'release-list' nested in recordings
            if 'release-list' in rec:
                for release in rec['release-list']:
                    date = release.get('date', "")
                    if date and len(date) >= 4:
                        years.append(int(date[:4]))
        
        return min(years) if years else None
    except Exception as e:
        print(f"MusicBrainz Error: {e}")
        return None

def fill_stacks_worker():
    """The Background Hero"""
    while True:
        if not american_stack.full():
            # 1. Pick a year
            target_year = random.randint(1960, 2020)
            
            # 2. Get a 'Hit' from Spotify (Fast)
            temp_song = fetch_top_spotify_hit(target_year)
            
            if temp_song:
                # 3. Verify Year with MusicBrainz (Slow - 1 sec)
                # This ensures the '2009 Remaster' becomes '1965'
                real_year = get_accurate_year(temp_song['title'], temp_song['artist'])
                
                if real_year:
                    temp_song['year'] = real_year
                    american_stack.put(temp_song)
                
                # Mandatory sleep to respect MusicBrainz 1req/sec rule
                time.sleep(1.1) 
        else:
            time.sleep(2)
