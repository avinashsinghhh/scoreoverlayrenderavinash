#!/usr/bin/env python3
"""
Chess Stream Overlay - Local Server & Auto-Tracker
Zero external dependencies (uses Python standard library only).
"""

import os
import sys
import re
import json
import time
import socket
import urllib.request
import urllib.error
from datetime import datetime, timezone
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
import webbrowser

# Ensure safe UTF-8 output on Windows consoles
try:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

PORT = int(os.environ.get("PORT", 5050))
HOST = os.environ.get("HOST", "0.0.0.0")
STATE_FILE = Path(__file__).parent / "session_state.json"
LIKES_STATE_FILE = Path(__file__).parent / "likes_state.json"
USER_AGENT = "StreamOverlay/2.0 (StreamerSessionOverlay; contact@stream-overlay.local)"

DEFAULT_STATE = {
    "username": "",
    "wins": 0,
    "losses": 0,
    "draws": 0,
    "sessionStartTime": int(time.time()),
    "baselineRatings": {},
    "currentRatings": {},
    "processedGames": [],
    "history": [],
    "streak": {"type": None, "count": 0},
    "settings": {
        "timeClass": "all",       # all, blitz, bullet, rapid, daily
        "ratedOnly": False,
        "theme": "chesscom",       # chesscom, neon, dark, purple, minimal
        "layout": "horizontal",   # horizontal, vertical, pill, card
        "showDraws": True,
        "showRating": True,
        "showWinRate": True,
        "showStreak": True,
        "showUsername": True,
        "customTitle": "SESSION RECORD",
        "scale": 100
    },
    "lastGame": None,
    "lastPolled": None,
    "status": "ready",
    "statusMessage": "Ready. Set your Chess.com username in the control panel."
}

DEFAULT_LIKES_STATE = {
    "likes": 0,
    "goal": 50,
    "goalStep": 50,
    "autoBumpGoal": True,
    "rewardText": "LIKE GOAL",
    "channelHandle": "",
    "trackMode": "channel",       # "channel" (auto-detect livestream) or "url" (specific stream)
    "youtubeUrl": "",
    "videoId": "",
    "isLive": False,
    "apiKey": "",
    "autoUpdate": True,
    "pollInterval": 5,
    "lastPolled": None,
    "lastUpdated": None,
    "status": "ready",
    "statusMessage": "Ready. Set your YouTube Channel handle to auto-track your livestreams.",
    "streamTitle": "",
    "settings": {
        "layout": "bar",
        "theme": "youtube",
        "icon": "thumb",
        "soundEnabled": True,
        "soundVolume": 0.5,
        "scale": 100,
        "showPercentage": True,
        "showGoal": True,
        "showRemaining": True,
        "accentColor": "#ff0033"
    }
}

state_lock = threading.Lock()
state = {}

likes_lock = threading.Lock()
likes_state = {}

def load_likes_state():
    global likes_state
    if LIKES_STATE_FILE.exists():
        try:
            with open(LIKES_STATE_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                likes_state = {**DEFAULT_LIKES_STATE, **loaded}
                likes_state["settings"] = {**DEFAULT_LIKES_STATE["settings"], **loaded.get("settings", {})}
                return
        except Exception as e:
            print(f"[Warning] Failed to load likes_state.json: {e}")
    likes_state = dict(DEFAULT_LIKES_STATE)
    save_likes_state()

def save_likes_state():
    try:
        with open(LIKES_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(likes_state, f, indent=2)
    except Exception as e:
        print(f"[Error] Failed to save likes_state.json: {e}")

def parse_like_number(text):
    if not text:
        return 0
    t = text.strip().upper().replace(",", "").replace(" ", "")
    try:
        if "M" in t:
            return int(float(t.replace("M", "")) * 1000000)
        if "K" in t:
            return int(float(t.replace("K", "")) * 1000)
        return int(float(t))
    except Exception:
        return 0

def extract_channel_handle(text):
    if not text:
        return ""
    t = text.strip()
    m = re.search(r'youtube\.com\/@([a-zA-Z0-9_.-]+)', t)
    if m:
        return f"@{m.group(1)}"
    m_chan = re.search(r'youtube\.com\/(channel\/[a-zA-Z0-9_-]+)', t)
    if m_chan:
        return m_chan.group(1)
    if t.startswith("@"):
        return t
    if " " not in t and "/" not in t and "?" not in t:
        return f"@{t}"
    return t

def resolve_live_stream_from_channel(channel_input, api_key=""):
    """
    Given a channel handle or URL, automatically detects the active livestream,
    its video ID, stream title, and live like count.
    """
    handle = extract_channel_handle(channel_input)
    if not handle:
        return {"success": False, "error": "No channel handle provided"}

    if handle.startswith("channel/"):
        live_url = f"https://www.youtube.com/{handle}/live"
    elif handle.startswith("@"):
        live_url = f"https://www.youtube.com/{handle}/live"
    elif handle.startswith("http"):
        live_url = handle if handle.endswith("/live") else f"{handle}/live"
    else:
        live_url = f"https://www.youtube.com/@{handle}/live"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache"
    }

    try:
        req = urllib.request.Request(live_url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            final_url = resp.geturl()
            html = resp.read().decode("utf-8", errors="ignore")

            video_id = None
            m_url_vid = re.search(r'(?:v=|\/live\/)([a-zA-Z0-9_-]{11})', final_url)
            if m_url_vid:
                video_id = m_url_vid.group(1)

            if not video_id:
                m_vid = re.search(r'"videoId"\s*:\s*"([a-zA-Z0-9_-]{11})"', html)
                if not m_vid:
                    m_vid = re.search(r'canonical"\s+href="https://www\.youtube\.com/watch\?v=([a-zA-Z0-9_-]{11})"', html)
                if m_vid:
                    video_id = m_vid.group(1)

            # Check if definitely offline or live
            is_offline = bool(
                re.search(r'Live stream offline', html, re.I) or
                re.search(r'Stream offline', html, re.I) or
                re.search(r'Live stream recording is not available', html, re.I) or
                (video_id is None and "/@" in final_url)
            )

            is_live = bool(
                re.search(r'"isLive"\s*:\s*true', html, re.I) or
                re.search(r'"liveBroadcastContent"\s*:\s*"LIVE"', html, re.I) or
                re.search(r'"status"\s*:\s*"LIVE"', html, re.I) or
                re.search(r'"label"\s*:\s*"LIVE"', html, re.I) or
                re.search(r'"isLiveStream"\s*:\s*true', html, re.I) or
                ("watch?v=" in final_url and not is_offline)
            )

            if is_offline and not re.search(r'"isLive"\s*:\s*true', html, re.I):
                is_live = False

            title = ""
            m_title = re.search(r'<meta\s+name="title"\s+content="([^"]+)"', html)
            if not m_title:
                m_title = re.search(r'<title>([^<]+)</title>', html)
            if m_title:
                title = m_title.group(1).replace(" - YouTube", "").strip()

            # API key query if available
            if api_key and video_id:
                try:
                    api_url = f"https://www.googleapis.com/youtube/v3/videos?part=statistics,snippet&id={video_id}&key={api_key}"
                    api_req = urllib.request.Request(api_url, headers={"User-Agent": USER_AGENT})
                    with urllib.request.urlopen(api_req, timeout=6) as api_resp:
                        if api_resp.status == 200:
                            api_data = json.loads(api_resp.read().decode("utf-8"))
                            items = api_data.get("items", [])
                            if items:
                                stats = items[0].get("statistics", {})
                                snip = items[0].get("snippet", {})
                                title = snip.get("title", title)
                                is_live = snip.get("liveBroadcastContent") == "live"
                                lk_str = stats.get("likeCount")
                                if lk_str is not None:
                                    return {
                                        "success": True,
                                        "isLive": is_live,
                                        "likes": int(lk_str),
                                        "title": title,
                                        "videoId": video_id,
                                        "handle": handle
                                    }
                except Exception:
                    pass

            # Extract like count via regexes
            like_count = None
            m_likes = re.search(r'"likeCount"\s*:\s*"(\d+)"', html)
            if m_likes:
                like_count = int(m_likes.group(1))

            if like_count is None:
                m_acc = re.search(r'"accessibilityData"\s*:\s*\{\s*"label"\s*:\s*"([0-9,.]+[KMkm]?)\s+likes', html, re.I)
                if m_acc:
                    like_count = parse_like_number(m_acc.group(1))

            if like_count is None:
                m_gen = re.search(r'([0-9,.]+[KMkm]?)\s+(?:likes|people liked this)', html, re.I)
                if m_gen:
                    like_count = parse_like_number(m_gen.group(1))

            if like_count is None:
                m_ld = re.search(r'"LikeAction"[^}]*\},?\s*"userInteractionCount"\s*:\s*"(\d+)"', html)
                if m_ld:
                    like_count = int(m_ld.group(1))

            if like_count is None and (video_id and is_live):
                like_count = 0

            return {
                "success": True,
                "isLive": is_live,
                "likes": like_count if like_count is not None else 0,
                "title": title or f"Live Stream ({handle})",
                "videoId": video_id or "",
                "handle": handle
            }

    except Exception as e:
        return {"success": False, "error": str(e), "isLive": False, "handle": handle}

def resolve_youtube_likes(identifier, identifier_type="raw", api_key=""):
    """
    Fetches like count and stream title for a given video ID, stream URL, or channel handle.
    Supports official YouTube Data API v3 and direct public scraper.
    """
    if not identifier:
        return {"success": False, "error": "No identifier provided"}

    ident = identifier.strip()

    # If it's a channel handle or channel URL, delegate to resolve_live_stream_from_channel
    if ident.startswith("@") or "/@" in ident or "/channel/" in ident:
        return resolve_live_stream_from_channel(ident, api_key)

    video_id = None
    if re.match(r'^[a-zA-Z0-9_-]{11}$', ident):
        video_id = ident
    else:
        m_vid = re.search(r'(?:v=|\/live\/|\/embed\/|youtu\.be\/)([a-zA-Z0-9_-]{11})', ident)
        if m_vid:
            video_id = m_vid.group(1)

    title = ""
    like_count = None

    if api_key and video_id:
        try:
            api_url = f"https://www.googleapis.com/youtube/v3/videos?part=statistics,snippet&id={video_id}&key={api_key}"
            req = urllib.request.Request(api_url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=8) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    items = data.get("items", [])
                    if items:
                        item = items[0]
                        stats = item.get("statistics", {})
                        snip = item.get("snippet", {})
                        title = snip.get("title", "")
                        like_str = stats.get("likeCount")
                        if like_str is not None:
                            return {
                                "success": True,
                                "isLive": snip.get("liveBroadcastContent") == "live",
                                "likes": int(like_str),
                                "title": title,
                                "videoId": video_id
                            }
        except Exception:
            pass

    target_url = f"https://www.youtube.com/watch?v={video_id}" if video_id else ident
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache"
        }
        req = urllib.request.Request(target_url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

            if not video_id:
                m_vid2 = re.search(r'"videoId"\s*:\s*"([a-zA-Z0-9_-]{11})"', html)
                if not m_vid2:
                    m_vid2 = re.search(r'canonical"\s+href="https://www\.youtube\.com/watch\?v=([a-zA-Z0-9_-]{11})"', html)
                if m_vid2:
                    video_id = m_vid2.group(1)

            m_title = re.search(r'<meta\s+name="title"\s+content="([^"]+)"', html)
            if not m_title:
                m_title = re.search(r'<title>([^<]+)</title>', html)
            if m_title:
                title = m_title.group(1).replace(" - YouTube", "").strip()

            is_live = bool(
                re.search(r'"isLive"\s*:\s*true', html, re.I) or
                re.search(r'"liveBroadcastContent"\s*:\s*"LIVE"', html, re.I)
            )

            m_likes = re.search(r'"likeCount"\s*:\s*"(\d+)"', html)
            if m_likes:
                like_count = int(m_likes.group(1))

            if like_count is None:
                m_acc = re.search(r'"accessibilityData"\s*:\s*\{\s*"label"\s*:\s*"([0-9,.]+[KMkm]?)\s+likes', html, re.I)
                if m_acc:
                    like_count = parse_like_number(m_acc.group(1))

            if like_count is None:
                m_gen = re.search(r'([0-9,.]+[KMkm]?)\s+(?:likes|people liked this)', html, re.I)
                if m_gen:
                    like_count = parse_like_number(m_gen.group(1))

            if like_count is None:
                m_ld = re.search(r'"LikeAction"[^}]*\},?\s*"userInteractionCount"\s*:\s*"(\d+)"', html)
                if m_ld:
                    like_count = int(m_ld.group(1))

            return {
                "success": True,
                "isLive": is_live,
                "likes": like_count if like_count is not None else 0,
                "title": title or (f"Video {video_id}" if video_id else "YouTube Stream"),
                "videoId": video_id or ""
            }
    except Exception as e:
        return {"success": False, "error": str(e)}

def likes_poller_thread():
    """Background polling worker for live YouTube stream like count updates."""
    while True:
        poll_interval = 5
        try:
            with likes_lock:
                auto_update = likes_state.get("autoUpdate", False)
                track_mode = likes_state.get("trackMode", "channel")
                channel_handle = likes_state.get("channelHandle", "").strip()
                yt_url = likes_state.get("youtubeUrl", "").strip()
                api_key = likes_state.get("apiKey", "").strip()
                poll_interval = likes_state.get("pollInterval", 5)
                current_video_id = likes_state.get("videoId", "")

            if auto_update:
                res = None
                # Auto-detect livestream from channel handle
                if track_mode == "channel" and channel_handle:
                    res = resolve_live_stream_from_channel(channel_handle, api_key)
                elif yt_url:
                    res = resolve_youtube_likes(yt_url, "raw", api_key)

                if res and res.get("success"):
                    is_live = res.get("isLive", False)
                    new_vid = res.get("videoId", "")
                    title = res.get("title", "")
                    new_likes = res.get("likes", 0)

                    with likes_lock:
                        likes_state["isLive"] = is_live
                        likes_state["lastPolled"] = int(time.time())

                        if is_live:
                            old_likes = likes_state.get("likes", 0)

                            # If a brand new livestream starts on the channel:
                            if new_vid and new_vid != current_video_id:
                                print(f"[Live Detected] Channel went live! Stream: '{title}' (ID: {new_vid})")
                                likes_state["videoId"] = new_vid
                                likes_state["streamTitle"] = title
                                likes_state["likes"] = new_likes
                                likes_state["status"] = "live"
                                likes_state["statusMessage"] = f"LIVE NOW: {title} ({new_likes:,} likes)"
                                save_likes_state()
                            else:
                                likes_state["likes"] = new_likes
                                if title:
                                    likes_state["streamTitle"] = title
                                if new_vid:
                                    likes_state["videoId"] = new_vid
                                likes_state["lastUpdated"] = int(time.time())
                                likes_state["status"] = "live"
                                likes_state["statusMessage"] = f"LIVE NOW: {new_likes:,} likes"

                                # Auto-bump goal if reached
                                if likes_state.get("autoBumpGoal", True) and new_likes >= likes_state.get("goal", 50):
                                    step = likes_state.get("goalStep", 50)
                                    g = likes_state.get("goal", 50)
                                    while g <= new_likes:
                                        g += step
                                    likes_state["goal"] = g

                                if new_likes != old_likes:
                                    save_likes_state()
                                    print(f"[Like Update] Live Stream Likes: {old_likes} -> {new_likes} ({title})")
                        else:
                            likes_state["status"] = "standby"
                            likes_state["statusMessage"] = f"Waiting for {channel_handle} to go live..."
                else:
                    with likes_lock:
                        likes_state["lastPolled"] = int(time.time())
        except Exception:
            pass

        time.sleep(max(3, poll_interval))

def load_state():
    global state
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                state = {**DEFAULT_STATE, **loaded}
                state["settings"] = {**DEFAULT_STATE["settings"], **loaded.get("settings", {})}
                return
        except Exception as e:
            print(f"[Warning] Failed to load session_state.json: {e}")
    state = dict(DEFAULT_STATE)
    save_state()

def save_state():
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        print(f"[Error] Failed to save session_state.json: {e}")

LOSS_RESULTS = {'checkmated', 'timeout', 'resigned', 'abandoned', 'lose', 'bughousepartnerlose'}
DRAW_RESULTS = {'agreed', 'repetition', 'stalemate', 'insufficient', '50move', 'timevsinsufficient'}

def parse_game(game, username):
    if not game or not username:
        return None
    user_lower = username.strip().lower()

    white = game.get("white", {})
    black = game.get("black", {})
    white_user = (white.get("username") or "").lower()
    black_user = (black.get("username") or "").lower()

    if white_user != user_lower and black_user != user_lower:
        return None

    is_white = (white_user == user_lower)
    user_data = white if is_white else black
    opp_data = black if is_white else white

    user_res = (user_data.get("result") or "").lower()
    opp_res = (opp_data.get("result") or "").lower()

    if user_res == "win":
        outcome = "win"
    elif user_res in LOSS_RESULTS:
        outcome = "loss"
    elif user_res in DRAW_RESULTS or opp_res in DRAW_RESULTS:
        outcome = "draw"
    elif opp_res == "win":
        outcome = "loss"
    else:
        outcome = "draw"

    return {
        "outcome": outcome,
        "userResult": user_res,
        "oppResult": opp_res,
        "userRating": user_data.get("rating"),
        "oppRating": opp_data.get("rating"),
        "oppUsername": opp_data.get("username") or "Opponent",
        "userColor": "white" if is_white else "black",
        "timeClass": game.get("time_class", "unknown"),
        "timeControl": game.get("time_control", ""),
        "rated": bool(game.get("rated", True)),
        "url": game.get("url", ""),
        "endTime": game.get("end_time") or int(time.time())
    }

def fetch_url_json(url):
    """Fetch URL with anti-caching headers."""
    headers = {
        "User-Agent": USER_AGENT,
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0"
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as res:
            if res.status == 200:
                return json.loads(res.read().decode("utf-8"))
    except Exception:
        pass
    return None

def fetch_latest_chess_games(username):
    """
    Fetches games from the latest archive available for the user.
    Uses the /archives endpoint to get the exact current active archive URL.
    """
    archives_url = f"https://api.chess.com/pub/player/{username}/games/archives"
    data = fetch_url_json(archives_url)
    if data and "archives" in data and len(data["archives"]) > 0:
        latest_archive_url = data["archives"][-1]
        archive_data = fetch_url_json(latest_archive_url)
        if archive_data and "games" in archive_data:
            return archive_data.get("games", [])

    # Fallback: try current UTC year/month
    now_utc = datetime.now(timezone.utc)
    fallback_url = f"https://api.chess.com/pub/player/{username}/games/{now_utc.year}/{now_utc.month:02d}"
    fb_data = fetch_url_json(fallback_url)
    if fb_data and "games" in fb_data:
        return fb_data.get("games", [])

    return None

def fetch_chess_stats(username):
    url = f"https://api.chess.com/pub/player/{username}/stats"
    return fetch_url_json(url)

def record_game_in_state(game_info):
    """Helper to register a completed match in session state."""
    outcome = game_info["outcome"]
    if outcome == "win":
        state["wins"] += 1
    elif outcome == "loss":
        state["losses"] += 1
    elif outcome == "draw":
        state["draws"] += 1

    # Update streak
    curr_streak = state.get("streak", {"type": None, "count": 0})
    if curr_streak.get("type") == outcome:
        curr_streak["count"] = curr_streak.get("count", 0) + 1
    else:
        curr_streak = {"type": outcome, "count": 1}
    state["streak"] = curr_streak

    # Update ratings
    tc = game_info.get("timeClass", "blitz")
    user_rt = game_info.get("userRating")
    if user_rt:
        state["currentRatings"][tc] = user_rt
        if tc not in state["baselineRatings"]:
            state["baselineRatings"][tc] = user_rt

    base_rt = state["baselineRatings"].get(tc, user_rt or 0)
    rating_diff = (user_rt - base_rt) if user_rt else 0
    game_info["ratingDiff"] = rating_diff

    state["lastGame"] = game_info
    state["history"].append(game_info)

    if game_info.get("url") and game_info["url"] not in state.get("processedGames", []):
        state["processedGames"].append(game_info["url"])
        state["processedGames"] = state["processedGames"][-500:]

    print(f"[Match Completed] {outcome.upper()} vs {game_info['oppUsername']} ({game_info['timeClass']}) -> Score: {state['wins']}W / {state['losses']}L / {state['draws']}D")

def poller_thread():
    """Background polling worker for Chess.com game updates."""
    last_stats_poll = 0
    while True:
        try:
            with state_lock:
                username = state.get("username", "").strip()
                start_time = state.get("sessionStartTime", 0)
                processed_set = set(state.get("processedGames", []))
                time_class_filter = state.get("settings", {}).get("timeClass", "all")
                rated_only = state.get("settings", {}).get("ratedOnly", False)

            if username:
                games = fetch_latest_chess_games(username)

                if games is not None:
                    new_games_found = []
                    # Allow 5-minute grace buffer for clock skew between local PC and Chess.com server
                    grace_start_time = start_time - 300

                    for g in games:
                        g_url = g.get("url")
                        g_end = g.get("end_time", 0)
                        if not g_url or g_url in processed_set:
                            continue

                        # If game ended well before the session started, mark as processed
                        if g_end < grace_start_time:
                            processed_set.add(g_url)
                            continue

                        parsed = parse_game(g, username)
                        if not parsed:
                            continue

                        # Apply filters
                        if rated_only and not parsed["rated"]:
                            processed_set.add(g_url)
                            continue
                        if time_class_filter != "all" and parsed["timeClass"] != time_class_filter:
                            processed_set.add(g_url)
                            continue

                        new_games_found.append(parsed)
                        processed_set.add(g_url)

                    # Periodically fetch latest ratings
                    ratings_update = {}
                    if time.time() - last_stats_poll > 15:
                        stats = fetch_chess_stats(username)
                        last_stats_poll = time.time()
                        if stats:
                            for tc in ["chess_blitz", "chess_bullet", "chess_rapid", "chess_daily"]:
                                if tc in stats and "last" in stats[tc] and "rating" in stats[tc]["last"]:
                                    short_tc = tc.replace("chess_", "")
                                    ratings_update[short_tc] = stats[tc]["last"]["rating"]

                    with state_lock:
                        state["lastPolled"] = int(time.time())
                        state["status"] = "active"
                        state["statusMessage"] = f"Tracking live: {username}"
                        state["processedGames"] = list(processed_set)[-500:]

                        if ratings_update:
                            state["currentRatings"].update(ratings_update)
                            for k, v in ratings_update.items():
                                if k not in state["baselineRatings"]:
                                    state["baselineRatings"][k] = v

                        for game_info in new_games_found:
                            record_game_in_state(game_info)

                        if new_games_found:
                            save_state()

                else:
                    with state_lock:
                        state["lastPolled"] = int(time.time())

        except Exception as e:
            pass

        time.sleep(5)

class OverlayRequestHandler(SimpleHTTPRequestHandler):
    """Handles static files and overlay API requests."""

    def __init__(self, *args, **kwargs):
        directory = str(Path(__file__).parent)
        super().__init__(*args, directory=directory, **kwargs)

    def log_message(self, format, *args):
        if "/api/" in self.path:
            super().log_message(format, *args)

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        if self.path.startswith("/api/") or self.path.endswith(".html"):
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def _send_json(self, data, status=200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self.path = "/control.html"

        if self.path == "/api/state":
            with state_lock:
                tc = state.get("settings", {}).get("timeClass", "blitz")
                if tc == "all":
                    tc = "blitz"
                cur_r = state.get("currentRatings", {}).get(tc)
                base_r = state.get("baselineRatings", {}).get(tc)
                r_diff = (cur_r - base_r) if (cur_r is not None and base_r is not None) else 0

                resp = {
                    **state,
                    "activeRating": cur_r,
                    "ratingDiff": r_diff,
                    "activeTimeClass": tc
                }
            self._send_json(resp)
            return

        if self.path == "/api/likes":
            with likes_lock:
                resp = dict(likes_state)
            self._send_json(resp)
            return

        if self.path == "/api/latest-games":
            # Returns the last 10 games from Chess.com so the user can import any missed game
            with state_lock:
                username = state.get("username", "").strip()
            if not username:
                self._send_json({"games": []})
                return

            games = fetch_latest_chess_games(username) or []
            parsed_list = []
            with state_lock:
                history_urls = {h.get("url") for h in state.get("history", [])}

            for g in reversed(games[-15:]):
                p = parse_game(g, username)
                if p:
                    p["inSession"] = p["url"] in history_urls
                    parsed_list.append(p)

            self._send_json({"games": parsed_list})
            return

        return super().do_GET()

    def do_POST(self):
        content_len = int(self.headers.get("Content-Length", 0))
        body_bytes = self.rfile.read(content_len) if content_len > 0 else b"{}"
        try:
            payload = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
        except Exception:
            payload = {}

        if self.path == "/api/reset":
            with state_lock:
                state["wins"] = 0
                state["losses"] = 0
                state["draws"] = 0
                state["streak"] = {"type": None, "count": 0}
                state["sessionStartTime"] = int(time.time())
                state["baselineRatings"] = dict(state.get("currentRatings", {}))
                if payload.get("clearHistory", False):
                    state["history"] = []
                    state["lastGame"] = None
                save_state()
            self._send_json({"success": True, "message": "Session reset to 0"})
            return

        if self.path == "/api/manual":
            with state_lock:
                if "type" in payload and "delta" in payload:
                    t = payload["type"]
                    d = int(payload["delta"])
                    if t == "win":
                        state["wins"] = max(0, state["wins"] + d)
                    elif t == "loss":
                        state["losses"] = max(0, state["losses"] + d)
                    elif t == "draw":
                        state["draws"] = max(0, state["draws"] + d)

                if "wins" in payload:
                    state["wins"] = max(0, int(payload["wins"]))
                if "losses" in payload:
                    state["losses"] = max(0, int(payload["losses"]))
                if "draws" in payload:
                    state["draws"] = max(0, int(payload["draws"]))

                save_state()
            self._send_json({"success": True, "state": state})
            return

        if self.path == "/api/settings":
            with state_lock:
                if "username" in payload:
                    new_user = payload["username"].strip()
                    if new_user.lower() != state.get("username", "").lower():
                        state["username"] = new_user
                        state["baselineRatings"] = {}
                        state["currentRatings"] = {}
                        # Don't purge history if just re-saving
                if "settings" in payload and isinstance(payload["settings"], dict):
                    state["settings"].update(payload["settings"])
                save_state()
            self._send_json({"success": True, "settings": state["settings"]})
            return

        if self.path == "/api/import-game":
            # Force import a specific game URL or the latest game
            target_url = payload.get("url")
            with state_lock:
                username = state.get("username", "").strip()

            if not username:
                self._send_json({"success": False, "message": "No username configured"})
                return

            games = fetch_latest_chess_games(username) or []
            target_game = None

            if target_url:
                for g in games:
                    if g.get("url") == target_url:
                        target_game = g
                        break
            else:
                # Latest game
                if games:
                    target_game = games[-1]

            if not target_game:
                self._send_json({"success": False, "message": "Game not found on Chess.com"})
                return

            parsed = parse_game(target_game, username)
            if not parsed:
                self._send_json({"success": False, "message": "Could not parse game"})
                return

            with state_lock:
                # Check if already in history
                if any(h.get("url") == parsed["url"] for h in state.get("history", [])):
                    self._send_json({"success": False, "message": "Game already imported in this session"})
                    return

                record_game_in_state(parsed)
                save_state()

            self._send_json({"success": True, "game": parsed})
            return

        if self.path == "/api/undo":
            with state_lock:
                if state.get("history"):
                    last = state["history"].pop()
                    outcome = last.get("outcome")
                    if outcome == "win":
                        state["wins"] = max(0, state["wins"] - 1)
                    elif outcome == "loss":
                        state["losses"] = max(0, state["losses"] - 1)
                    elif outcome == "draw":
                        state["draws"] = max(0, state["draws"] - 1)
                    state["lastGame"] = state["history"][-1] if state["history"] else None
                    save_state()
                    self._send_json({"success": True, "undone": last})
                    return
            self._send_json({"success": False, "message": "No games in history to undo"})
            return

        if self.path == "/api/test-event":
            outcome = payload.get("outcome", "win")
            with state_lock:
                test_game = {
                    "outcome": outcome,
                    "oppUsername": "TestOpponent",
                    "timeClass": state.get("settings", {}).get("timeClass", "blitz"),
                    "userRating": 1500,
                    "oppRating": 1495,
                    "ratingDiff": 8 if outcome == "win" else (-8 if outcome == "loss" else 0),
                    "url": "https://www.chess.com",
                    "endTime": int(time.time()),
                    "isTest": True
                }
                record_game_in_state(test_game)
                save_state()
            self._send_json({"success": True, "testGame": test_game})
            return

        if self.path == "/api/likes":
            with likes_lock:
                if "likes" in payload:
                    likes_state["likes"] = max(0, int(payload["likes"]))
                if "goal" in payload:
                    likes_state["goal"] = max(1, int(payload["goal"]))
                if "goalStep" in payload:
                    likes_state["goalStep"] = max(1, int(payload["goalStep"]))
                if "autoBumpGoal" in payload:
                    likes_state["autoBumpGoal"] = bool(payload["autoBumpGoal"])
                if "rewardText" in payload:
                    likes_state["rewardText"] = str(payload["rewardText"])
                if "channelHandle" in payload:
                    likes_state["channelHandle"] = str(payload["channelHandle"]).strip()
                if "trackMode" in payload:
                    likes_state["trackMode"] = str(payload["trackMode"]).strip()
                if "youtubeUrl" in payload:
                    likes_state["youtubeUrl"] = str(payload["youtubeUrl"]).strip()
                if "videoId" in payload:
                    likes_state["videoId"] = str(payload["videoId"]).strip()
                if "isLive" in payload:
                    likes_state["isLive"] = bool(payload["isLive"])
                if "apiKey" in payload:
                    likes_state["apiKey"] = str(payload["apiKey"]).strip()
                if "autoUpdate" in payload:
                    likes_state["autoUpdate"] = bool(payload["autoUpdate"])
                if "pollInterval" in payload:
                    likes_state["pollInterval"] = max(3, int(payload["pollInterval"]))
                if "settings" in payload and isinstance(payload["settings"], dict):
                    likes_state["settings"].update(payload["settings"])
                save_likes_state()
            self._send_json({"success": True, "state": likes_state})
            return

        if self.path == "/api/likes/detect":
            channel = payload.get("channel") or likes_state.get("channelHandle", "")
            api_key = payload.get("apiKey") or likes_state.get("apiKey", "")
            res = resolve_live_stream_from_channel(channel, api_key)
            if res.get("success"):
                with likes_lock:
                    if channel:
                        likes_state["channelHandle"] = res.get("handle", channel)
                    likes_state["trackMode"] = "channel"
                    likes_state["isLive"] = res.get("isLive", False)
                    likes_state["lastPolled"] = int(time.time())
                    if res.get("isLive"):
                        new_likes = res.get("likes", 0)
                        likes_state["likes"] = new_likes
                        likes_state["streamTitle"] = res.get("title", "")
                        likes_state["videoId"] = res.get("videoId", "")
                        likes_state["status"] = "live"
                        likes_state["statusMessage"] = f"LIVE NOW: {res.get('title')} ({new_likes:,} likes)"
                        likes_state["lastUpdated"] = int(time.time())
                    else:
                        likes_state["status"] = "standby"
                        likes_state["statusMessage"] = f"Waiting for {likes_state.get('channelHandle')} to go live..."
                    save_likes_state()
            self._send_json(res)
            return

        if self.path == "/api/likes/youtube":
            ident = payload.get("identifier") or payload.get("url") or ""
            ident_type = payload.get("identifierType", "raw")
            api_key = payload.get("apiKey") or likes_state.get("apiKey", "")
            res = resolve_youtube_likes(ident, ident_type, api_key)
            if res.get("success"):
                with likes_lock:
                    new_likes = res["likes"]
                    likes_state["likes"] = new_likes
                    if res.get("title"):
                        likes_state["streamTitle"] = res["title"]
                    if res.get("videoId"):
                        likes_state["videoId"] = res["videoId"]
                    likes_state["lastPolled"] = int(time.time())
                    likes_state["lastUpdated"] = int(time.time())
                    likes_state["status"] = "active"
                    likes_state["statusMessage"] = f"Live: {new_likes:,} likes"
                    if likes_state.get("autoBumpGoal", True) and new_likes >= likes_state.get("goal", 50):
                        step = likes_state.get("goalStep", 50)
                        g = likes_state.get("goal", 50)
                        while g <= new_likes:
                            g += step
                        likes_state["goal"] = g
                    save_likes_state()
            self._send_json(res)
            return

        if self.path == "/api/likes/add":
            delta = int(payload.get("delta", 1))
            with likes_lock:
                likes_state["likes"] = max(0, likes_state["likes"] + delta)
                if likes_state.get("autoBumpGoal", True) and likes_state["likes"] >= likes_state.get("goal", 50):
                    step = likes_state.get("goalStep", 50)
                    g = likes_state.get("goal", 50)
                    while g <= likes_state["likes"]:
                        g += step
                    likes_state["goal"] = g
                save_likes_state()
            self._send_json({"success": True, "likes": likes_state["likes"]})
            return

        if self.path == "/api/likes/set":
            val = int(payload.get("likes", 0))
            with likes_lock:
                likes_state["likes"] = max(0, val)
                save_likes_state()
            self._send_json({"success": True, "likes": likes_state["likes"]})
            return

        self.send_error(404, "Endpoint not found")

def free_port(port=PORT):
    """Ensure port 5050 is free by terminating any lingering previous overlay process."""
    if sys.platform != "win32":
        return
    try:
        import subprocess
        cmd = f'netstat -ano | findstr /r /c:":{port} .*LISTENING"'
        out = subprocess.check_output(cmd, shell=True).decode('utf-8', errors='ignore')
        my_pid = str(os.getpid())
        for line in out.strip().splitlines():
            parts = line.strip().split()
            if len(parts) >= 5:
                pid = parts[-1]
                if pid.isdigit() and pid != my_pid and pid != "0":
                    print(f"[Notice] Terminating previous overlay process (PID {pid}) to free port {port}...")
                    subprocess.call(f'taskkill /F /PID {pid}', shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    time.sleep(0.5)
    except Exception:
        pass

class ReusableHTTPServer(HTTPServer):
    allow_reuse_address = True

def get_server(port=PORT):
    """Creates an HTTPServer guaranteed to bind to the port on HOST."""
    if sys.platform == "win32":
        free_port(port)
    server_address = (HOST, port)
    for attempt in range(3):
        try:
            return ReusableHTTPServer(server_address, OverlayRequestHandler)
        except OSError as e:
            print(f"[Notice] Port {port} busy, retrying cleanup (attempt {attempt + 1}/3)...")
            if sys.platform == "win32":
                free_port(port)
            time.sleep(0.8)
    return ReusableHTTPServer(server_address, OverlayRequestHandler)

def run_server():
    load_state()
    load_likes_state()

    port = PORT
    httpd = get_server(port)

    t1 = threading.Thread(target=poller_thread, daemon=True)
    t1.start()

    t2 = threading.Thread(target=likes_poller_thread, daemon=True)
    t2.start()

    print("\n" + "=" * 68)
    print(f" [STREAM OVERLAY SUITE] SERVER RUNNING ON {HOST}:{port}")
    print("=" * 68)
    print(f" * Like Counter Dashboard : http://localhost:{port}/likes-control.html")
    print(f" * Like Counter OBS URL   : http://localhost:{port}/likes-overlay.html")
    print(f" * Chess Tracker Dashboard: http://localhost:{port}/control.html")
    print(f" * Chess Tracker OBS URL  : http://localhost:{port}/overlay.html")
    print("=" * 68)
    print(f" [OK] In OBS, URL is: http://localhost:{port}/likes-overlay.html")
    print(" [!] Keep this terminal OPEN or MINIMIZED while streaming.")
    print(" Press Ctrl+C to stop.\n")

    if not os.environ.get("RENDER"):
        try:
            webbrowser.open(f"http://localhost:{port}/likes-control.html")
        except Exception:
            pass

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...")
    finally:
        httpd.server_close()

if __name__ == "__main__":
    run_server()
