# 🎵 Song Roulette

A minimal Spotify game — press **New Song** to play a random track from your playlist, then hit **Reveal** to see what it was.

---

## Setup

### 1. Spotify Developer App
1. Go to [developer.spotify.com](https://developer.spotify.com/dashboard) and create an app.
2. Add your `REDIRECT_URI` to the app's **Redirect URIs** (e.g. `https://your-app.onrender.com/callback`).
3. Note your **Client ID** and **Client Secret**.

### 2. Environment Variables (Render)
Set these in your Render service's **Environment** tab:

| Variable | Value |
|---|---|
| `SPOTIFY_CLIENT_ID` | Your Spotify app's Client ID |
| `SPOTIFY_CLIENT_SECRET` | Your Spotify app's Client Secret |
| `REDIRECT_URI` | `https://your-app.onrender.com/callback` |
| `PLAYLIST_ID` | The Spotify playlist ID (from the playlist URL) |

### 3. Deploy on Render
- **Build Command:** `pip install -r requirements.txt`
- **Start Command:** `gunicorn app:app`
- **Environment:** Python 3

---

## How it works

1. **Login** — Connect your Spotify account via OAuth.
2. **New Song** — Picks a random track from the configured playlist and plays it on your active Spotify device (phone, desktop, etc.).
3. **Reveal** — Shows the song name, artist, year, and album art.

> **Note:** The user must have Spotify open and active on a device for playback to work. Spotify Premium is required for playback control via the API.
