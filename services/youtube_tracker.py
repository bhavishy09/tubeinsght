import matplotlib
matplotlib.use('Agg')
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import time
import os
import io
import base64
from datetime import datetime
import pytz
import random
import traceback
from googleapiclient.discovery import build
from dotenv import load_dotenv

load_dotenv()

# ---------- CONFIG / DEFAULTS ----------
TIMEZONE = "Asia/Kolkata"
API_KEY = os.getenv("YOUTUBE_API_KEY")
# ---------------------------------------

def get_youtube_service():
    """Builds and returns the YouTube API service object."""
    if not API_KEY:
        print("YOUTUBE_API_KEY not found in .env file.")
        return None
    try:
        return build('youtube', 'v3', developerKey=API_KEY)
    except Exception as e:
        print("Error creating YouTube service:", e)
        return None

def fetch_video_and_channel_stats(youtube, video_id):
    """
    Fetches video and channel statistics from the YouTube API.
    Returns (views, likes, subs, channel_id).
    """
    try:
        resp = youtube.videos().list(part='snippet,statistics', id=video_id).execute()
        items = resp.get('items', [])
        if not items:
            return None, None, None, None
        
        stats = items[0].get('statistics', {})
        snippet = items[0].get('snippet', {})
        views = int(stats.get('viewCount', 0))
        likes = int(stats.get('likeCount', 0))
        channel_id = snippet.get('channelId')
        
        subs = None
        if channel_id:
            ch_resp = youtube.channels().list(part='statistics', id=channel_id).execute()
            ch_items = ch_resp.get('items', [])
            if ch_items:
                ch_stats = ch_items[0].get('statistics', {})
                subs = int(ch_stats.get('subscriberCount', 0))
        
        return views, likes, subs, channel_id
    except Exception as e:
        print("Exception while fetching from YouTube API:", e)
        traceback.print_exc()
        return None, None, None, None

def fetch_simulated_stats(video_id):
    """
    Generates simulated statistics for testing without an API key.
    """
    seed = int(time.time() // 60) + sum(ord(c) for c in video_id)
    random.seed(seed)
    views = (seed % 1000) + 100 + random.randint(0, 300)
    likes = max(0, int(views * random.uniform(0.01, 0.07)))
    subs = 500 + random.randint(0, 50)
    return views, likes, subs, "SIMULATED_CHANNEL"

def get_single_sample(video_id):
    """
    Fetches a single snapshot of statistics for polling.
    """
    youtube = get_youtube_service()
    if youtube:
        views, likes, subs, _ = fetch_video_and_channel_stats(youtube, video_id)
    else:
        views, likes, subs, _ = fetch_simulated_stats(video_id)
        
    tz = pytz.timezone(TIMEZONE)
    ts_unix = int(time.time())
    iso = datetime.fromtimestamp(ts_unix, tz).isoformat()
    
    return {
        "timestamp_unix": ts_unix,
        "iso": iso,
        "views": views,
        "likes": likes,
        "subscribers": subs
    }

def generate_plots_from_data(video_id, data_list, interval_min=1):
    """
    Generates base64 encoded plots from a list of data dictionaries.
    data_list should be like: [{"iso": "...", "views": 100, "likes": 10, "subscribers": 5}, ...]
    """
    if not data_list or len(data_list) < 2:
        print("Not enough data to plot.")
        return []

    df = pd.DataFrame(data_list)
    df['iso_dt'] = pd.to_datetime(df['iso'])
    df = df.sort_values('iso_dt')
    df['views'] = pd.to_numeric(df['views'], errors='coerce').ffill()
    df['likes'] = pd.to_numeric(df['likes'], errors='coerce').ffill()
    df['subscribers'] = pd.to_numeric(df['subscribers'], errors='coerce').ffill()

    tz = pytz.timezone(TIMEZONE)
    locator = mdates.MinuteLocator(interval=max(1, int(interval_min / 5)))
    formatter = mdates.DateFormatter('%H:%M', tz=tz)
    
    plot_files = []
    plot_configs = [
        ('views', 'Views', 'blue'),
        ('likes', 'Likes', 'orange'),
        ('subscribers', 'Subscribers', 'green')
    ]

    for column, title, color in plot_configs:
        fig, ax = plt.subplots(figsize=(10, 5))
        ax.plot(df['iso_dt'], df[column], marker='o', linestyle='-', label=title, color=color)
        ax.set_xlabel(f'Time ({TIMEZONE})')
        ax.set_ylabel('Count')
        ax.set_title(f'{title} over Time for video {video_id}')
        ax.legend()
        ax.grid(True)
        ax.xaxis.set_major_locator(locator)
        ax.xaxis.set_major_formatter(formatter)
        plt.setp(ax.get_xticklabels(), rotation=45, ha="right")
        plt.tight_layout()

        # Save to BytesIO instead of file
        img_buffer = io.BytesIO()
        try:
            plt.savefig(img_buffer, format='png')
            img_buffer.seek(0)
            base64_data = base64.b64encode(img_buffer.read()).decode('utf-8')
            plot_files.append({"type": column, "data": base64_data})
        except Exception as e:
            print(f"Could not generate base64 for {column} plot: {e}")
        
        plt.close(fig)

    return plot_files

def track_video_stats(video_id, interval_min=1, samples=5):
    """
    BACKWARDS COMPATIBILITY FUNCTION:
    This blocks using time.sleep() and is NOT recommended for Vercel,
    but we keep it for local testing if needed. It uses the new base64 system.
    """
    data_list = []
    for i in range(samples):
        sample = get_single_sample(video_id)
        data_list.append(sample)
        print(f"Sample #{i+1}/{samples} -> views: {sample['views']}, likes: {sample['likes']}, subs: {sample['subscribers']}")
        if i < samples - 1:
            time.sleep(interval_min * 60)

    return generate_plots_from_data(video_id, data_list, interval_min)
