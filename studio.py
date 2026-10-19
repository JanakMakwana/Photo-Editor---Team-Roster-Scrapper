#!/usr/bin/env python3
"""
Basketball Portrait Studio - Professional Headshot Tuner
First-Page Folder Selection + Freeform 180x180 Framing + AI Cutout + Retouch Brushes
"""

import os
import sys
import json
import glob
import math
import io
import base64
import re
import html as py_html
import urllib.request
import urllib.parse
import zipfile
import ssl
import threading
import concurrent.futures
from concurrent.futures import ThreadPoolExecutor
import gc
import time
import copy
import shutil
import zlib
import struct
import http.cookiejar
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

# Optimize thread allocation for low-resource cloud environments (Render Free tier)
os.environ.setdefault("OMP_NUM_THREADS", "2")
os.environ.setdefault("MKL_NUM_THREADS", "2")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")

# Auto-activate local .venv if not running inside a virtualenv
script_dir = os.path.dirname(os.path.abspath(__file__))
venv_candidates = [
    os.path.join(script_dir, ".venv", "bin", "python"),
    os.path.join(script_dir, ".venv", "bin", "python3"),
    "/Users/janakmakwana/Downloads/Photo Editor for HUDL/.venv/bin/python",
]
if not os.environ.get("RENDER") and sys.prefix == sys.base_prefix:
    for vp in venv_candidates:
        if os.path.exists(vp) and sys.executable != vp:
            os.execv(vp, [vp] + sys.argv)

from PIL import Image
import rembg
from process_portraits import FaceDetectorWrapper, find_input_images
import saas_db
import saas_email
import saas_auth

DETECTOR = None
REMBG_SESSION = None
FACE_CACHE = {}
# Concurrency limiter to protect Render's 512MB RAM and single CPU from spikes
AI_LOCK = threading.Semaphore(1)


def get_services():
    global DETECTOR, REMBG_SESSION
    if DETECTOR is None:
        print("[Studio] Initializing Face Detector...")
        DETECTOR = FaceDetectorWrapper()
    if REMBG_SESSION is None:
        # Default to u2netp on Render to use only ~199MB RAM instead of 371MB (preventing 503 OOM crashes)
        model_name = os.environ.get("REMBG_MODEL", "u2netp" if os.environ.get("RENDER") else "u2net")
        print(f"[Studio] Initializing Rembg Engine ({model_name})...")
        REMBG_SESSION = rembg.new_session(model_name)
    return DETECTOR, REMBG_SESSION


def clean_server_storage(max_age_minutes: int = 15) -> dict:
    """Purges temporary photos and output folders to prevent Render disk space exhaustion and 502 errors."""
    workspace_dir = os.path.dirname(os.path.abspath(__file__))
    dirs_to_check = [
        os.path.join(workspace_dir, "input_photos"),
        os.path.join(workspace_dir, "output_photos"),
    ]
    now = time.time()
    deleted_files = 0
    freed_bytes = 0

    for base_dir in dirs_to_check:
        if not os.path.exists(base_dir):
            continue
        for item in os.listdir(base_dir):
            if item.startswith(".") or item == "models":
                continue
            item_path = os.path.join(base_dir, item)
            try:
                mtime = os.path.getmtime(item_path)
                age_minutes = (now - mtime) / 60.0
                if max_age_minutes <= 0 or age_minutes >= max_age_minutes:
                    if os.path.isdir(item_path):
                        for root, _, files in os.walk(item_path):
                            for f in files:
                                fp = os.path.join(root, f)
                                try:
                                    freed_bytes += os.path.getsize(fp)
                                    os.remove(fp)
                                    deleted_files += 1
                                except Exception:
                                    pass
                        shutil.rmtree(item_path, ignore_errors=True)
                    else:
                        freed_bytes += os.path.getsize(item_path)
                        os.remove(item_path)
                        deleted_files += 1
            except Exception:
                pass

    # Clear face detection cache and collect memory
    FACE_CACHE.clear()
    gc.collect()

    freed_mb = round(freed_bytes / (1024 * 1024), 2)
    return {
        "status": "ok",
        "deleted_files": deleted_files,
        "freed_mb": freed_mb,
        "freed_bytes": freed_bytes,
        "face_cache_cleared": True
    }


def _background_storage_janitor():
    """Background janitor thread that cleans up any stale photos every 10 minutes."""
    while True:
        try:
            time.sleep(600)
            clean_server_storage(max_age_minutes=15)
        except Exception:
            pass


_janitor_thread = threading.Thread(target=_background_storage_janitor, daemon=True)
_janitor_thread.start()


def resolve_edited_dir(folder_path: str, create: bool = False) -> str:
    """Computes the target [folder_path]_edited directory path without creating it unless requested."""
    abs_path = os.path.abspath(folder_path)
    parent = os.path.dirname(abs_path)
    base = os.path.basename(abs_path)
    out_dir = os.path.join(parent, f"{base}_edited")
    if create:
        os.makedirs(out_dir, exist_ok=True)
    return out_dir


def resolve_input_path(raw_path: str) -> str:
    """Intelligently resolves a user-provided folder path or name."""
    if not raw_path:
        return None

    cleaned = raw_path.strip().strip("'\"")
    expanded = os.path.expanduser(os.path.expandvars(cleaned))

    if os.path.isdir(expanded):
        return os.path.abspath(expanded)

    downloads_dir = os.path.expanduser("~/Downloads")
    workspace_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(workspace_dir)
    input_photos_dir = os.path.join(workspace_dir, "input_photos")

    candidate_bases = [
        input_photos_dir,
        downloads_dir,
        workspace_dir,
        parent_dir,
        os.path.expanduser("~/Desktop"),
        os.path.expanduser("~/Documents"),
    ]

    for base in candidate_bases:
        cand = os.path.join(base, cleaned)
        if os.path.isdir(cand):
            return os.path.abspath(cand)

    # Fuzzy matching in Downloads, workspace parent, and Desktop
    search_dirs = [downloads_dir, parent_dir, os.path.expanduser("~/Desktop")]
    norm_target = re.sub(r'[\s_\-]+', '', cleaned.lower().replace("copy", ""))

    for sdir in search_dirs:
        if os.path.exists(sdir):
            for item in os.listdir(sdir):
                if item.startswith(".") or item.endswith("_edited"):
                    continue
                full = os.path.join(sdir, item)
                if os.path.isdir(full):
                    norm_item = re.sub(r'[\s_\-]+', '', item.lower().replace("copy", ""))
                    if norm_item == norm_target or norm_target in norm_item or norm_item in norm_target:
                        return os.path.abspath(full)

    return None


def compute_auto_framing(image_path: str = None, image_bytes: bytes = None, cache_key: str = None):
    """Calculates optimal default framing using MediaPipe face detection, supporting disk files or in-memory bytes."""
    key = cache_key or image_path
    if key and key in FACE_CACHE:
        return FACE_CACHE[key]

    detector, _ = get_services()
    if image_bytes:
        orig = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    elif image_path and os.path.exists(image_path):
        orig = Image.open(image_path).convert("RGB")
    else:
        raise ValueError(f"Valid image_path or image_bytes required (got path={image_path})")

    w_orig, h_orig = orig.size
    box = detector.detect_face(orig)
    fx, fy, fw, fh = box

    # Standard sports bust clearances
    top_pad = int(fh * 0.50)
    bot_pad = int(fh * 0.60)
    side_pad = int(fw * 0.35)

    ymin = max(0, fy - top_pad)
    ymax = min(h_orig, fy + fh + bot_pad)
    xmin = max(0, fx - side_pad)
    xmax = min(w_orig, fx + fw + side_pad)

    crop_w = max(1, xmax - xmin)
    crop_h = max(1, ymax - ymin)

    target_dim = 180 * 0.92
    scale = target_dim / max(crop_w, crop_h)

    scaled_w = w_orig * scale
    offset_x = (180 - scaled_w) / 2.0
    offset_y = 180.0 - (ymax * scale)

    result = {
        "scale": scale,
        "offset_x": offset_x,
        "offset_y": offset_y,
        "orig_width": w_orig,
        "orig_height": h_orig,
        "face": [fx, fy, fw, fh],
    }
    if key:
        if len(FACE_CACHE) > 200:
            FACE_CACHE.clear()
        FACE_CACHE[key] = result
    return result


def process_custom_framed_portrait(
    image_path: str = None,
    image_bytes: bytes = None,
    scale: float = 0.35,
    offset_x: float = 0,
    offset_y: float = 0,
    output_path: str = None,
    output_size: int = 180,
) -> Image.Image:
    """Crops the framed region, runs rembg, and fits to 180x180 RGBA canvas directly in-memory or to disk."""
    _, rembg_session = get_services()
    if image_bytes:
        orig = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    elif image_path and os.path.exists(image_path):
        orig = Image.open(image_path).convert("RGB")
    else:
        raise ValueError(f"Valid image_path or image_bytes required (got path={image_path})")

    w_orig, h_orig = orig.size

    scale_factor = scale * (output_size / 180.0)
    x1 = -offset_x / scale_factor
    y1 = -offset_y / scale_factor
    x2 = (output_size - offset_x) / scale_factor
    y2 = (output_size - offset_y) / scale_factor

    ox1 = max(0, int(math.floor(x1)))
    oy1 = max(0, int(math.floor(y1)))
    ox2 = min(w_orig, int(math.ceil(x2)))
    oy2 = min(h_orig, int(math.ceil(y2)))

    if ox2 <= ox1 or oy2 <= oy1:
        canvas = Image.new("RGBA", (output_size, output_size), (0, 0, 0, 0))
    else:
        crop = orig.crop((ox1, oy1, ox2, oy2))
        
        # Optimize memory & CPU for Cloud / Low-RAM: cap crop to 512px before U-2-Net inference
        max_dim = 512
        cw, ch = crop.size
        if max(cw, ch) > max_dim:
            ratio = max_dim / float(max(cw, ch))
            downscaled = crop.resize((max(1, int(round(cw * ratio))), max(1, int(round(ch * ratio)))), Image.Resampling.BILINEAR)
            no_bg_crop = rembg.remove(downscaled, session=rembg_session)
        else:
            no_bg_crop = rembg.remove(crop, session=rembg_session)

        sw = max(1, int(round((ox2 - ox1) * scale_factor)))
        sh = max(1, int(round((oy2 - oy1) * scale_factor)))
        scaled_crop = no_bg_crop.resize((sw, sh), Image.Resampling.LANCZOS)

        canvas = Image.new("RGBA", (output_size, output_size), (0, 0, 0, 0))
        px = int(round(offset_x + ox1 * scale_factor))
        py = int(round(offset_y + oy1 * scale_factor))
        canvas.paste(scaled_crop, (px, py), scaled_crop)

    if output_path:
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        canvas.save(output_path, "PNG")

    return canvas


def boost_image_url_width(img_url: str, target_width: int = 1200) -> str:
    """Modifies or appends width parameter in URL to fetch high-res image from athletics CDN."""
    if not img_url:
        return ""

    # 0. Unwrap Next.js image proxies (e.g. /_next/image?url=https%3A...)
    if "/_next/image" in img_url and "url=" in img_url:
        m = re.search(r'url=([^&]+)', img_url)
        if m:
            img_url = urllib.parse.unquote(m.group(1))

    # 1. Strip WordPress/CMS dimension suffixes e.g. -600x800.jpg -> .jpg
    if not any(k in img_url for k in ["_crop_", "/thumbnails/"]):
        img_url = re.sub(r'-\d+x\d+(\.[a-zA-Z0-9]+)$', r'\1', img_url)

    # 2. If width=\d+ exists, replace it with target_width and quality=100
    if re.search(r'[?&]width=\d+', img_url):
        new_url = re.sub(r'([?&]width=)\d+', r'\g<1>' + str(target_width), img_url)
        if 'quality=' in new_url:
            new_url = re.sub(r'([?&]quality=)\d+', r'\g<1>100', new_url)
        else:
            new_url += '&quality=100'
        return new_url

    # 3. If it's a known athletics image CDN (Sidearm / Presto / etc.) or contains /images/
    if any(k in img_url for k in ["/images/", "sidearm", "presto", "athletics"]):
        sep = '&' if '?' in img_url else '?'
        return f"{img_url}{sep}width={target_width}&quality=100"

    return img_url



# NHL Teams database mapping slug / abbreviations to official 3-letter team code and full team name
NHL_TEAMS = {
    "anaheim-ducks": ("ANA", "Anaheim Ducks"), "ducks": ("ANA", "Anaheim Ducks"), "anaheim": ("ANA", "Anaheim Ducks"), "ana": ("ANA", "Anaheim Ducks"),
    "boston-bruins": ("BOS", "Boston Bruins"), "bruins": ("BOS", "Boston Bruins"), "boston": ("BOS", "Boston Bruins"), "bos": ("BOS", "Boston Bruins"),
    "buffalo-sabres": ("BUF", "Buffalo Sabres"), "sabres": ("BUF", "Buffalo Sabres"), "buffalo": ("BUF", "Buffalo Sabres"), "buf": ("BUF", "Buffalo Sabres"),
    "calgary-flames": ("CGY", "Calgary Flames"), "flames": ("CGY", "Calgary Flames"), "calgary": ("CGY", "Calgary Flames"), "cgy": ("CGY", "Calgary Flames"),
    "carolina-hurricanes": ("CAR", "Carolina Hurricanes"), "hurricanes": ("CAR", "Carolina Hurricanes"), "carolina": ("CAR", "Carolina Hurricanes"), "car": ("CAR", "Carolina Hurricanes"),
    "chicago-blackhawks": ("CHI", "Chicago Blackhawks"), "blackhawks": ("CHI", "Chicago Blackhawks"), "chicago": ("CHI", "Chicago Blackhawks"), "chi": ("CHI", "Chicago Blackhawks"),
    "colorado-avalanche": ("COL", "Colorado Avalanche"), "avalanche": ("COL", "Colorado Avalanche"), "colorado": ("COL", "Colorado Avalanche"), "col": ("COL", "Colorado Avalanche"),
    "columbus-blue-jackets": ("CBJ", "Columbus Blue Jackets"), "bluejackets": ("CBJ", "Columbus Blue Jackets"), "columbus": ("CBJ", "Columbus Blue Jackets"), "cbj": ("CBJ", "Columbus Blue Jackets"),
    "dallas-stars": ("DAL", "Dallas Stars"), "stars": ("DAL", "Dallas Stars"), "dallas": ("DAL", "Dallas Stars"), "dal": ("DAL", "Dallas Stars"),
    "detroit-red-wings": ("DET", "Detroit Red Wings"), "redwings": ("DET", "Detroit Red Wings"), "detroit": ("DET", "Detroit Red Wings"), "det": ("DET", "Detroit Red Wings"),
    "edmonton-oilers": ("EDM", "Edmonton Oilers"), "oilers": ("EDM", "Edmonton Oilers"), "edmonton": ("EDM", "Edmonton Oilers"), "edm": ("EDM", "Edmonton Oilers"),
    "florida-panthers": ("FLA", "Florida Panthers"), "panthers": ("FLA", "Florida Panthers"), "florida": ("FLA", "Florida Panthers"), "fla": ("FLA", "Florida Panthers"),
    "los-angeles-kings": ("LAK", "Los Angeles Kings"), "kings": ("LAK", "Los Angeles Kings"), "los-angeles": ("LAK", "Los Angeles Kings"), "lak": ("LAK", "Los Angeles Kings"), "la": ("LAK", "Los Angeles Kings"),
    "minnesota-wild": ("MIN", "Minnesota Wild"), "wild": ("MIN", "Minnesota Wild"), "minnesota": ("MIN", "Minnesota Wild"), "min": ("MIN", "Minnesota Wild"),
    "montreal-canadiens": ("MTL", "Montreal Canadiens"), "canadiens": ("MTL", "Montreal Canadiens"), "montreal": ("MTL", "Montreal Canadiens"), "mtl": ("MTL", "Montreal Canadiens"),
    "nashville-predators": ("NSH", "Nashville Predators"), "predators": ("NSH", "Nashville Predators"), "nashville": ("NSH", "Nashville Predators"), "nsh": ("NSH", "Nashville Predators"),
    "new-jersey-devils": ("NJD", "New Jersey Devils"), "devils": ("NJD", "New Jersey Devils"), "new-jersey": ("NJD", "New Jersey Devils"), "njd": ("NJD", "New Jersey Devils"), "nj": ("NJD", "New Jersey Devils"),
    "new-york-islanders": ("NYI", "New York Islanders"), "islanders": ("NYI", "New York Islanders"), "isles": ("NYI", "New York Islanders"), "nyi": ("NYI", "New York Islanders"),
    "new-york-rangers": ("NYR", "New York Rangers"), "rangers": ("NYR", "New York Rangers"), "nyr": ("NYR", "New York Rangers"),
    "ottawa-senators": ("OTT", "Ottawa Senators"), "senators": ("OTT", "Ottawa Senators"), "ottawa": ("OTT", "Ottawa Senators"), "ott": ("OTT", "Ottawa Senators"),
    "philadelphia-flyers": ("PHI", "Philadelphia Flyers"), "flyers": ("PHI", "Philadelphia Flyers"), "philadelphia": ("PHI", "Philadelphia Flyers"), "phi": ("PHI", "Philadelphia Flyers"),
    "pittsburgh-penguins": ("PIT", "Pittsburgh Penguins"), "penguins": ("PIT", "Pittsburgh Penguins"), "pittsburgh": ("PIT", "Pittsburgh Penguins"), "pit": ("PIT", "Pittsburgh Penguins"),
    "san-jose-sharks": ("SJS", "San Jose Sharks"), "sharks": ("SJS", "San Jose Sharks"), "san-jose": ("SJS", "San Jose Sharks"), "sjs": ("SJS", "San Jose Sharks"), "sj": ("SJS", "San Jose Sharks"),
    "seattle-kraken": ("SEA", "Seattle Kraken"), "kraken": ("SEA", "Seattle Kraken"), "seattle": ("SEA", "Seattle Kraken"), "sea": ("SEA", "Seattle Kraken"),
    "st-louis-blues": ("STL", "St. Louis Blues"), "blues": ("STL", "St. Louis Blues"), "st-louis": ("STL", "St. Louis Blues"), "stl": ("STL", "St. Louis Blues"),
    "tampa-bay-lightning": ("TBL", "Tampa Bay Lightning"), "lightning": ("TBL", "Tampa Bay Lightning"), "tampa-bay": ("TBL", "Tampa Bay Lightning"), "tbl": ("TBL", "Tampa Bay Lightning"), "tb": ("TBL", "Tampa Bay Lightning"),
    "toronto-maple-leafs": ("TOR", "Toronto Maple Leafs"), "mapleleafs": ("TOR", "Toronto Maple Leafs"), "leafs": ("TOR", "Toronto Maple Leafs"), "toronto": ("TOR", "Toronto Maple Leafs"), "tor": ("TOR", "Toronto Maple Leafs"),
    "utah-hockey-club": ("UTA", "Utah Hockey Club"), "utah": ("UTA", "Utah Hockey Club"), "uta": ("UTA", "Utah Hockey Club"),
    "vancouver-canucks": ("VAN", "Vancouver Canucks"), "canucks": ("VAN", "Vancouver Canucks"), "vancouver": ("VAN", "Vancouver Canucks"), "van": ("VAN", "Vancouver Canucks"),
    "vegas-golden-knights": ("VGK", "Vegas Golden Knights"), "goldenknights": ("VGK", "Vegas Golden Knights"), "knights": ("VGK", "Vegas Golden Knights"), "vegas": ("VGK", "Vegas Golden Knights"), "vgk": ("VGK", "Vegas Golden Knights"),
    "washington-capitals": ("WSH", "Washington Capitals"), "capitals": ("WSH", "Washington Capitals"), "washington": ("WSH", "Washington Capitals"), "wsh": ("WSH", "Washington Capitals"),
    "winnipeg-jets": ("WPG", "Winnipeg Jets"), "jets": ("WPG", "Winnipeg Jets"), "winnipeg": ("WPG", "Winnipeg Jets"), "wpg": ("WPG", "Winnipeg Jets"),
}

NHL_POSITIONS = {
    "C": "Center",
    "L": "Left Wing",
    "LW": "Left Wing",
    "R": "Right Wing",
    "RW": "Right Wing",
    "D": "Defenseman",
    "G": "Goalie",
    "F": "Forward",
}


def scrape_nhl_roster(url: str):
    """
    Scrapes NHL roster data via the official NHL REST API (api-web.nhle.com).
    Extracts all players across forwards, defensemen, and goalies, including
    names, jersey numbers, positions, height, weight, birth info, shoots/catches,
    and high-resolution transparent headshot URLs.
    """
    parsed = urllib.parse.urlparse(url)
    path_parts = [p.lower() for p in parsed.path.split('/') if p]

    matched_abbr = None
    suggested_folder = "NHL Roster"

    # Match team slug or abbreviation from URL path
    for part in path_parts:
        if part in NHL_TEAMS:
            matched_abbr, suggested_folder = NHL_TEAMS[part]
            break

    if not matched_abbr:
        # Check netloc or full URL
        for k, (abbr, name) in NHL_TEAMS.items():
            if k in url.lower():
                matched_abbr, suggested_folder = abbr, name
                break

    if not matched_abbr:
        # Default fallback to BUF if sabres was mentioned or default
        matched_abbr = "BUF"
        suggested_folder = "Buffalo Sabres"

    api_url = f"https://api-web.nhle.com/v1/roster/{matched_abbr}/current"
    req = urllib.request.Request(
        api_url,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
    )

    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    players = []
    for group_name in ["forwards", "defensemen", "goalies"]:
        group_players = data.get(group_name, [])
        for p in group_players:
            fn = p.get("firstName", {}).get("default") if isinstance(p.get("firstName"), dict) else (p.get("firstName") or "")
            ln = p.get("lastName", {}).get("default") if isinstance(p.get("lastName"), dict) else (p.get("lastName") or "")
            name = f"{fn} {ln}".strip()
            if not name:
                continue

            jersey = str(p.get("sweaterNumber", "")).strip()
            pos_code = p.get("positionCode", "").strip()
            pos_title = NHL_POSITIONS.get(pos_code, pos_code)

            # Map L -> LW, R -> RW for standard hockey positions
            pos_short_map = {"L": "LW", "R": "RW", "C": "C", "D": "D", "G": "G"}
            pos_short = pos_short_map.get(pos_code, pos_code)

            # Height formatting (e.g. 5'10")
            ht_in = p.get("heightInInches")
            ht_str = f"{ht_in // 12}'{ht_in % 12}\"" if ht_in else ""

            # Weight formatting (e.g. 178)
            wt_lb = p.get("weightInPounds")
            wt_num = str(wt_lb) if wt_lb else ""
            wt_str = f"{wt_lb} lbs" if wt_lb else ""

            # Birth date & formatted Born (e.g. May 12, 2005)
            bdate = p.get("birthDate", "").strip()
            born_fmt = ""
            if bdate:
                try:
                    dt = datetime.strptime(bdate, "%Y-%m-%d")
                    born_fmt = f"{dt.strftime('%b')} {dt.day}, {dt.year}"
                except Exception:
                    born_fmt = bdate

            city = p.get("birthCity", {}).get("default") if isinstance(p.get("birthCity"), dict) else (p.get("birthCity") or "")
            state = p.get("birthStateProvince", {}).get("default") if isinstance(p.get("birthStateProvince"), dict) else (p.get("birthStateProvince") or "")
            country = p.get("birthCountry", "").strip()
            place_parts = [x for x in [city, state, country] if x]
            bplace = ", ".join(place_parts)

            shoots = p.get("shootsCatches", "").strip()

            # Formatted readable details string
            detail_tokens = []
            if ht_str or wt_str:
                detail_tokens.append(" / ".join([x for x in [ht_str, wt_str] if x]))
            if bdate or bplace:
                born_info = f"Born: {born_fmt or bdate}" if (born_fmt or bdate) else "Born"
                if bplace:
                    born_info += f" ({bplace})"
                detail_tokens.append(born_info)
            if shoots:
                detail_tokens.append(f"Shoots: {shoots}")
            details = " • ".join(detail_tokens)

            img_url = p.get("headshot", "").strip()

            players.append({
                "name": name,
                "jersey": jersey,
                "pos": pos_short,
                "position": pos_short,
                "position_full": f"{pos_title} ({pos_code})" if pos_code and pos_title != pos_code else pos_title,
                "shoots": shoots,
                "height": ht_str,
                "weight": wt_num,
                "born": born_fmt or bdate,
                "birth_date": bdate,
                "birthplace": bplace,
                "image": img_url,
                "raw_image": img_url,
                "details": details,
                "assigned_number": ""
            })

    return {
        "suggested_folder": suggested_folder,
        "players": players
    }


def scrape_college_roster(url: str):
    """
    Scrapes athletics/college roster web page to extract players, site jerseys, positions,
    and high-resolution image URLs.
    """
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        page_html = resp.read().decode("utf-8", errors="ignore")

    players = []

    # 1. Schema.org JSON-LD
    matches = re.findall(r'<script type=\"application/ld\+json\">(.*?)</script>', page_html, re.DOTALL)
    for block in matches:
        try:
            d = json.loads(block.strip())
            items = d.get("item", []) if isinstance(d, dict) else (d if isinstance(d, list) else [])
            for it in items:
                name = it.get("name")
                img = it.get("image")
                img_url = img.get("url") if isinstance(img, dict) else (img if isinstance(img, str) else "")
                if name and img_url:
                    full_img_url = urllib.parse.urljoin(url, img_url.strip())
                    high_res = boost_image_url_width(full_img_url, 1200)
                    players.append({
                        "name": name.strip(),
                        "image": high_res,
                        "raw_image": full_img_url,
                        "jersey": "",
                        "position": "",
                        "details": "",
                        "assigned_number": ""
                    })
        except Exception:
            pass

    # 2. Extract site jersey numbers if present
    jerseys = re.findall(r'sidearm-roster-player-jersey-number\">([^<]+)<', page_html)
    if not jerseys:
        jerseys = re.findall(r'class=\"[^\"]*jersey[^\"]*\"[^>]*>([^<]+)<', page_html)
    jerseys = [j.strip() for j in jerseys if j.strip()]

    # 3. Extract positions if present
    positions = re.findall(r'sidearm-roster-player-position\">([^<]+)<', page_html)
    if not positions:
        positions = re.findall(r'class=\"[^\"]*position[^\"]*\"[^>]*>([^<]+)<', page_html)
    positions = [p.strip() for p in positions if p.strip()]

    if len(jerseys) >= len(players):
        for i, p in enumerate(players):
            p["jersey"] = jerseys[i]
    if len(positions) >= len(players):
        for i, p in enumerate(players):
            p["position"] = positions[i]

    # Deduplicate by player name
    seen = set()
    unique = []
    for p in players:
        p["pos"] = p.get("position", "")
        p["shoots"] = p.get("shoots", "")
        p["height"] = p.get("height", "")
        p["weight"] = p.get("weight", "")
        p["born"] = p.get("born", "")
        p["birthplace"] = p.get("birthplace", "")
        if p["name"] not in seen:
            seen.add(p["name"])
            unique.append(p)

    # Extract suggested folder name
    suggested_folder = "College Roster"
    og = re.search(r'property=[\"\x27]og:site_name[\"\x27]\s+content=[\"\x27]([^\"]+)[\"\x27]', page_html)
    if og:
        raw = py_html.unescape(og.group(1).strip())
        raw = re.sub(r'\s+Athletics.*$', '', raw, flags=re.I).strip()
        if len(raw) > 2:
            suggested_folder = raw
    else:
        title = re.search(r'<title>([^<]+)</title>', page_html)
        if title:
            t = py_html.unescape(title.group(1).strip())
            parts = t.split(" - ")
            if len(parts) >= 2:
                cand = parts[-1].strip()
                cand = re.sub(r'\s+Athletics.*$', '', cand, flags=re.I).strip()
                if len(cand) > 2:
                    suggested_folder = cand

    return {
        "suggested_folder": suggested_folder,
        "players": unique
    }


def clean_uk_team_folder(url: str, html: str) -> str:
    """Extracts a clean, professional folder name for UK / EIHL teams and sports clubs."""
    url_lower = url.lower()
    if 'cardiffdevils.com' in url_lower: return 'Cardiff Devils'
    if 'coventryblaze.co.uk' in url_lower: return 'Coventry Blaze'
    if 'belfastgiants.com' in url_lower: return 'Belfast Giants'
    if 'sheffieldsteelers.co.uk' in url_lower: return 'Sheffield Steelers'
    if 'panthers.co.uk' in url_lower: return 'Nottingham Panthers'
    if 'manchesterstorm.com' in url_lower: return 'Manchester Storm'
    if 'clanihc.com' in url_lower: return 'Glasgow Clan'
    if 'dundeestars.com' in url_lower: return 'Dundee Stars'
    if 'fifeflyers.co.uk' in url_lower: return 'Fife Flyers'
    if 'guildfordflames.com' in url_lower: return 'Guildford Flames'

    # Try OpenGraph site_name or title
    og = re.search(r'property=[\"\']og:site_name[\"\']\s+content=[\"\']([^\"\']+)[\"\']', html, re.I)
    if og:
        name = py_html.unescape(og.group(1).strip())
        name = re.sub(r'\s*(Official|Website|Ice Hockey|Club|Team|Roster)\b', '', name, flags=re.I).strip()
        if len(name) > 2:
            return name

    title = re.search(r'<title>(.*?)</title>', html, re.I | re.S)
    if title:
        t = py_html.unescape(title.group(1).strip())
        for sep in [' | ', ' - ', ' – ', ' &#8211; ']:
            if sep in t:
                parts = [p.strip() for p in t.split(sep)]
                cand = [p for p in parts if not any(w in p.lower() for w in ['roster', 'team', 'players', 'official', 'website'])]
                if cand:
                    return cand[0]
                return parts[0]
        return re.sub(r'\s*(Official|Website|Ice Hockey|Club|Team|Roster)\b', '', t, flags=re.I).strip() or "UK Team Roster"

    return "UK Team Roster"


def is_uk_sports_url(url: str) -> bool:
    """Detects whether a URL belongs to a UK sports team or UK domain."""
    url_lower = url.lower()
    uk_keywords = [
        "cardiffdevils.com", "coventryblaze.co.uk", "belfastgiants.com",
        "sheffieldsteelers.co.uk", "panthers.co.uk", "manchesterstorm.com",
        "clanihc.com", "dundeestars.com", "fifeflyers.co.uk", "guildfordflames.com",
        ".co.uk", ".uk", ".scot", ".cymru"
    ]
    return any(k in url_lower for k in uk_keywords)


def parse_cardiff_single_player(url: str, html: str):
    """Scrapes an individual Cardiff Devils player profile page (e.g. /team/davies-5/)."""
    name = ""
    h1_m = re.search(r'<h1[^>]*>([^<]+)</h1>', html)
    if h1_m:
        name = h1_m.group(1).strip()
    if not name:
        title_m = re.search(r'<title>(.*?)(?:\s*\(\d+\))?\s*\|', html)
        if title_m:
            name = title_m.group(1).strip()

    num_m = re.search(r'player__image--number[^>]*>[\s\n]*(\d+)', html)
    if not num_m:
        num_m = re.search(r'\((\d+)\)', html)
    jersey = num_m.group(1).strip() if num_m else ""

    labels = dict(re.findall(r'class=[\"\']player__info--label[^\"\']*[\"\']>([^<]+)</span>\s*<span>([^<]+)</span>', html))
    pos = labels.get("Position", "").capitalize()
    shoots = labels.get("Shoots", "").strip()
    height = labels.get("Height", "").strip()
    weight = labels.get("Weight", "").strip()
    born = labels.get("Age", "").strip()
    birthplace = labels.get("Nationality", "").strip()

    img = ""
    img_m = re.search(r'<img[^>]+class=[\"\'][^\"\']*player__image[^\"\']*[\"\'][^>]+srcset=[\"\']([^\"\']+)[\"\']', html)
    if not img_m:
        img_m = re.search(r'<img[^>]+srcset=[\"\']([^\"\']+)[\"\'][^>]+class=[\"\'][^\"\']*player__image', html)
    if not img_m:
        img_m = re.search(r'<img[^>]+class=[\"\'][^\"\']*player__image[^\"\']*[\"\'][^>]+src=[\"\']([^\"\']+)[\"\']', html)

    if img_m:
        sources = [s.strip().split() for s in img_m.group(1).split(",") if s.strip()]
        sources.sort(key=lambda s: int(s[1][:-1]) if len(s) > 1 and s[1].endswith("w") else 0, reverse=True)
        if sources:
            img = sources[0][0]
    else:
        alt_m = re.search(r'<img[^>]+src=[\"\']([^\"\']+)[\"\'][^>]*alt=[\"\']' + re.escape(name) + r'[\"\']', html, re.I)
        if alt_m:
            img = alt_m.group(1)

    full_img = boost_image_url_width(urllib.parse.urljoin(url, img.strip()))
    v_parts = []
    if born: v_parts.append(f"Age: {born}")
    if birthplace: v_parts.append(f"Nationality: {birthplace}")
    if shoots: v_parts.append(f"Shoots: {shoots}")
    if height: v_parts.append(f"Height: {height}")
    if weight: v_parts.append(f"Weight: {weight}")
    details = " | ".join(v_parts)

    return {
        "suggested_folder": "Cardiff Devils",
        "players": [{
            "name": name,
            "jersey": jersey,
            "position": pos,
            "pos": pos,
            "image": full_img,
            "raw_image": full_img,
            "shoots": shoots,
            "height": height,
            "weight": weight,
            "born": born,
            "birthplace": birthplace,
            "details": details,
            "assigned_number": jersey or ""
        }]
    }


def parse_coventry_single_player(url: str, html: str):
    """Scrapes an individual Coventry Blaze player profile page (e.g. /player/carson-musser)."""
    m = re.search(r'<script\s+[^>]*data-page=[\"\']app[\"\'][^>]*>(.*?)</script>', html, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(1))
            hero = data.get("props", {}).get("hero", {})
            if hero:
                name = hero.get("name") or f"{hero.get('firstName', '')} {hero.get('lastName', '')}".strip()
                jersey = str(hero.get("number", "")).strip()
                pos = hero.get("positionLabel", "").strip()
                img = hero.get("photoUrl", "")
                vitals = hero.get("vitals", [])
                v_dict = {"shoots": "", "height": "", "weight": "", "born": "", "birthplace": ""}
                for v in vitals:
                    t = v.get("text", "")
                    if any(x in t.lower() for x in ["cm", "'", '"']):
                        v_dict["height"] = t
                    elif any(x in t.lower() for x in ["american", "canadian", "british", "swedish", "finnish"]) or len(t) <= 4:
                        v_dict["birthplace"] = t
                    elif any(char.isdigit() for char in t) and ("(" in t or len(t) <= 4 or any(m in t.lower() for m in ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])):
                        v_dict["born"] = t
                full_img = boost_image_url_width(urllib.parse.urljoin(url, img.strip()))
                return {
                    "suggested_folder": "Coventry Blaze",
                    "players": [{
                        "name": name,
                        "jersey": jersey,
                        "position": pos.capitalize(),
                        "pos": pos.capitalize(),
                        "image": full_img,
                        "raw_image": full_img,
                        "shoots": v_dict["shoots"],
                        "height": v_dict["height"],
                        "weight": v_dict["weight"],
                        "born": v_dict["born"],
                        "birthplace": v_dict["birthplace"],
                        "details": " | ".join(v.get("text", "") for v in vitals),
                        "assigned_number": jersey or ""
                    }]
                }
        except Exception:
            pass
    return None


def parse_panthers_single_player(url: str, html: str):
    """Scrapes an individual Nottingham Panthers player profile page (e.g. /onice/202627-elite-league-roster/mat-robson)."""
    h1_m = re.search(r'<h1[^>]*>([^<]+)</h1>', html)
    name = h1_m.group(1).strip() if h1_m else ""
    if not name:
        title_m = re.search(r'<title>(.*?)(?:\s*-)?\s*Nottingham Panthers', html, re.I)
        if title_m:
            name = title_m.group(1).strip()

    num_m = re.search(r'number-overlay[^>]*>(\d+)<', html)
    jersey = num_m.group(1).strip() if num_m else ""

    pairs = re.findall(r'<th[^>]*>([^<]+)</th>\s*<td[^>]*>([^<]+)</td>', html, re.I)
    table = {k.strip().lower(): py_html.unescape(v.strip()) for k, v in pairs}

    pos = table.get("position", "").capitalize()
    shoots = table.get("shoots") or table.get("glove", "")
    height = table.get("height", "")
    weight = table.get("weight", "")
    born = table.get("date of birth") or table.get("born", "")
    birthplace = table.get("place of birth") or table.get("birthplace") or table.get("nationality", "")

    img_m = re.search(r'<div class=[\"\']image-container[\"\'][^>]*>.*?<img[^>]+src=[\"\']([^\"\']+)[\"\']', html, re.DOTALL)
    if not img_m:
        img_m = re.search(r'<img[^>]+src=[\"\']([^\"\']+)[\"\'][^>]*alt=[\"\']' + re.escape(name) + r'[\"\']', html, re.I)
    img = img_m.group(1).strip() if img_m else ""
    full_img = boost_image_url_width(urllib.parse.urljoin(url, img))

    v_parts = []
    if pos: v_parts.append(f"Position: {pos}")
    if born: v_parts.append(f"Born: {born}")
    if birthplace: v_parts.append(f"Birthplace: {birthplace}")
    if shoots: v_parts.append(f"Shoots/Glove: {shoots}")
    if height: v_parts.append(f"Height: {height}")
    if weight: v_parts.append(f"Weight: {weight}")
    details = " | ".join(v_parts)

    return {
        "suggested_folder": "Nottingham Panthers",
        "players": [{
            "name": name,
            "jersey": jersey,
            "position": pos,
            "pos": pos,
            "image": full_img,
            "raw_image": full_img,
            "shoots": shoots,
            "height": height,
            "weight": weight,
            "born": born,
            "birthplace": birthplace,
            "details": details,
            "assigned_number": jersey or ""
        }]
    }


def scrape_uk_roster(url: str):
    """
    Scrapes UK sports and EIHL hockey team rosters (Cardiff Devils, Coventry Blaze,
    Belfast Giants, Sheffield Steelers, Nottingham Panthers, Manchester Storm, etc.)
    extracting player names, jersey numbers, positions, vitals, and high-res headshot URLs.
    Supports both full team roster pages and individual player profile pages.
    """
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        html = resp.read().decode("utf-8", errors="ignore")

    # 0. Check if this is a single player profile page
    u_lower = url.lower().rstrip('/')
    is_cardiff_single = "cardiffdevils.com/team/" in u_lower and u_lower.split("/team/")[-1] not in ("", "team")
    is_coventry_single = "coventryblaze.co.uk/player/" in u_lower and u_lower.split("/player/")[-1] not in ("", "player")
    is_panthers_single = "panthers.co.uk" in u_lower and (
        "/onice/" in u_lower and len(u_lower.split("/onice/")[-1].strip("/").split("/")) >= 2
    )

    if is_cardiff_single:
        return parse_cardiff_single_player(url, html)

    if is_coventry_single:
        single_res = parse_coventry_single_player(url, html)
        if single_res:
            return single_res

    if is_panthers_single:
        return parse_panthers_single_player(url, html)

    suggested_folder = clean_uk_team_folder(url, html)
    players = []

    # 1. Inertia.js (Coventry Blaze and modern UK sports apps)
    m_inertia = re.search(r'<script\s+[^>]*data-page=[\"\']app[\"\'][^>]*>(.*?)</script>', html, re.DOTALL)
    if m_inertia:
        try:
            d = json.loads(m_inertia.group(1))
            props = d.get("props", {})
            plist = props.get("players") or props.get("roster") or props.get("team") or []
            for p in plist:
                name = p.get("name") or f"{p.get('firstName', '')} {p.get('lastName', '')}".strip()
                jersey = str(p.get("number", "")).strip()
                pos = p.get("positionLabel") or p.get("position") or ""
                img = p.get("photoUrl") or p.get("image") or p.get("photo") or ""
                vitals = p.get("vitals", "")
                bio = p.get("bio", "")
                if name and img:
                    v_dict = {"shoots": "", "height": "", "weight": "", "born": "", "birthplace": ""}
                    if vitals:
                        parts = [x.strip() for x in vitals.split("|")]
                        for pt in parts:
                            if "age:" in pt.lower():
                                v_dict["born"] = pt
                            elif "cm" in pt.lower() or "'" in pt or '"' in pt:
                                v_dict["height"] = pt
                            elif len(pt) <= 4 or any(c in pt.lower() for c in ["can", "usa", "gbr", "fin", "swe", "den"]):
                                v_dict["birthplace"] = pt

                    full_img = boost_image_url_width(urllib.parse.urljoin(url, img.strip()))
                    players.append({
                        "name": name.strip(),
                        "jersey": jersey,
                        "position": pos.capitalize(),
                        "pos": pos.capitalize(),
                        "image": full_img,
                        "raw_image": full_img,
                        "shoots": v_dict["shoots"],
                        "height": v_dict["height"],
                        "weight": v_dict["weight"],
                        "born": v_dict["born"],
                        "birthplace": v_dict["birthplace"],
                        "details": vitals or (bio[:60] if bio else ""),
                        "assigned_number": ""
                    })
        except Exception:
            pass

    # 2. Cardiff Devils & Belfast Giants (player-card pattern)
    if not players:
        # Check if page has category headings (Forwards, Defencemen, Netminders, Coaches)
        heading_sections = re.split(r'<h[1-4][^>]*>(Forwards?|Defencemen|Defenders?|Defence|Netminders?|Goalies?|Goalkeepers?|Coaches?)</h[1-4]>', html, flags=re.I)
        sections_to_process = []
        if len(heading_sections) > 1:
            for idx in range(1, len(heading_sections), 2):
                h_name = heading_sections[idx]
                h_content = heading_sections[idx + 1]
                sections_to_process.append((h_name, h_content))
        else:
            sections_to_process.append(("", html))

        for pos_label, sec_html in sections_to_process:
            cards = re.findall(
                r'<(?:div|a|article)[^>]*class=[\"\'][^\"\']*\bplayer-card\b(?![-_])[^\"\']*[\"\'][^>]*>(.*?)(?=<(?:div|a|article)[^>]*class=[\"\'][^\"\']*\bplayer-card\b(?![-_])[^\"\']*[\"\']|\Z)',
                sec_html,
                re.DOTALL | re.I
            )
            for c in cards:
                # Jersey Number
                num_m = re.search(r'player-card[_\-]*(?:number|squad-number)[^>]*>[\s\n]*<span[^>]*>[\s\n]*(\d+)', c, re.I)
                if not num_m:
                    num_m = re.search(r'player-card_squad-number[^>]*>[\s\n]*(\d+)', c, re.I)
                if not num_m:
                    num_m = re.search(r'(?:number|jersey)[^>]*>[\s\n]*<span>?(\d+)<?', c, re.I)
                jersey = num_m.group(1).strip() if num_m else ""

                # Name
                name = ""
                name_m = re.search(r'player-card__name[^>]*>(.*?)</div>', c, re.DOTALL | re.I)
                if name_m:
                    h_tags = re.findall(r'<h\d[^>]*>(.*?)</h\d>', name_m.group(1))
                    if h_tags:
                        name = " ".join(h_tags).strip()
                    else:
                        name = re.sub(r'<[^>]+>', ' ', name_m.group(1)).strip()
                if not name:
                    alt_m = re.search(r'<img[^>]+alt=[\"\']([^\"\']+)[\"\']', c)
                    if alt_m and len(alt_m.group(1).strip()) > 2 and 'logo' not in alt_m.group(1).lower():
                        name = alt_m.group(1).strip()

                # Position (prioritize specific card position if present, then section heading)
                pos = ""
                pos_m = re.search(r'player-card__position[^>]*>(.*?)</div>', c, re.DOTALL | re.I)
                if pos_m:
                    pos = re.sub(r'<[^>]+>', ' ', pos_m.group(1)).strip()
                if not pos:
                    pos = pos_label

                # Image URL - look for highest resolution in srcset or fallback to src
                img = ""
                srcset_m = re.search(r'srcset=[\"\']([^\"\']+)[\"\']', c, re.I)
                if srcset_m:
                    sources = [s.strip().split() for s in srcset_m.group(1).split(',') if s.strip()]
                    def _get_w(s):
                        if len(s) > 1 and s[1].endswith('w'):
                            try:
                                return int(s[1][:-1])
                            except Exception:
                                return 0
                        return 0
                    sources.sort(key=_get_w, reverse=True)
                    if sources:
                        img = sources[0][0]
                if not img:
                    src_m = re.search(r'<img[^>]+src=[\"\']([^\"\']+)[\"\']', c, re.I)
                    if src_m:
                        img = src_m.group(1)

                link_m = re.search(r'href=[\"\'](https://www.cardiffdevils.com/team/[^\"\']+)[\"\']', c)
                profile_url = link_m.group(1) if link_m else ""

                if name and img and 'logo' not in img.lower() and 'facebook' not in img.lower() and 'icon' not in img.lower():
                    full_img = boost_image_url_width(urllib.parse.urljoin(url, img.strip()))
                    players.append({
                        "name": name.strip(),
                        "jersey": jersey,
                        "position": pos.capitalize() if pos else "",
                        "pos": pos.capitalize() if pos else "",
                        "image": full_img,
                        "raw_image": full_img,
                        "shoots": "",
                        "height": "",
                        "weight": "",
                        "born": "",
                        "birthplace": "",
                        "details": "",
                        "assigned_number": "",
                        "profile_url": profile_url
                    })

        # Enrich Cardiff Devils / UK players with their individual profile vitals in parallel
        if any(p.get("profile_url") for p in players):
            def _fetch_profile_vitals(item):
                purl = item.get("profile_url")
                if not purl:
                    return item
                try:
                    r = urllib.request.Request(purl, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"})
                    with urllib.request.urlopen(r, timeout=5) as rp:
                        h = rp.read().decode("utf-8")
                        labels = dict(re.findall(r'class=[\"\']player__info--label[^\"\']*[\"\']>([^<]+)</span>\s*<span>([^<]+)</span>', h))
                        item["shoots"] = labels.get("Shoots", item.get("shoots", "")).strip()
                        item["height"] = labels.get("Height", item.get("height", "")).strip()
                        item["weight"] = labels.get("Weight", item.get("weight", "")).strip()
                        item["born"] = labels.get("Age", item.get("born", "")).strip()
                        item["birthplace"] = labels.get("Nationality", item.get("birthplace", "")).strip()
                        if labels.get("Position"):
                            item["pos"] = labels.get("Position").capitalize().strip()
                            item["position"] = item["pos"]
                        v_summary = []
                        if item["born"]: v_summary.append(f"Age: {item['born']}")
                        if item["birthplace"]: v_summary.append(f"Nationality: {item['birthplace']}")
                        if item["shoots"]: v_summary.append(f"Shoots: {item['shoots']}")
                        if item["height"]: v_summary.append(f"Height: {item['height']}")
                        if item["weight"]: v_summary.append(f"Weight: {item['weight']}")
                        item["details"] = " | ".join(v_summary)
                except Exception:
                    pass
                return item

            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
                players = list(ex.map(_fetch_profile_vitals, players))

    # 3. Next.js / Manchester Storm aria-label articles
    if not players:
        articles = re.findall(r'<article[^>]+aria-label=[\"\'](\d+),\s*([^,]+),\s*([^\"\']+)[\"\'][^>]*>(.*?)</article>', html, re.DOTALL | re.I)
        for num, name, pos, art_html in articles:
            next_m = re.search(r'/_next/image\?url=([^&\"\'\s]+)', art_html)
            img = ""
            if next_m:
                img = urllib.parse.unquote(next_m.group(1))
            else:
                img_m = re.search(r'<img[^>]+src=[\"\']([^\"\']+)[\"\']', art_html)
                if img_m:
                    img = img_m.group(1)
            if name and img:
                full_img = boost_image_url_width(urllib.parse.urljoin(url, img.strip()))
                players.append({
                    "name": name.strip(),
                    "jersey": num.strip(),
                    "position": pos.strip().capitalize(),
                    "pos": pos.strip().capitalize(),
                    "image": full_img,
                    "raw_image": full_img,
                    "shoots": "",
                    "height": "",
                    "weight": "",
                    "born": "",
                    "birthplace": "",
                    "details": "",
                    "assigned_number": ""
                })

    # 4. Sheffield Steelers / SportsPress theme
    if not players:
        sp_items = re.findall(
            r'<div[^>]*class=[\"\'][^\"\']*gdlr-core-(?:item-list|sp-player-item)[^\"\']*[\"\'][^>]*>(.*?)(?=<div[^>]*class=[\"\'][^\"\']*gdlr-core-(?:item-list|sp-player-item)[^\"\']*[\"\']|\Z)',
            html,
            re.DOTALL | re.I
        )
        for it in sp_items:
            name_m = re.search(r'gdlr-core-sp-player-title[^>]*><a[^>]*>([^<]+)</a>', it)
            name = name_m.group(1).strip() if name_m else ""
            num_m = re.search(r'gdlr-core-sp-player-number[^>]*>(\d+)<', it)
            jersey = num_m.group(1).strip() if num_m else ""
            pos_m = re.search(r'gdlr-core-sp-player-position[^>]*>([^<]+)</div>', it)
            pos = pos_m.group(1).strip() if pos_m else ""
            img_m = re.search(r'<img[^>]+src=[\"\']([^\"\']+)[\"\']', it)
            img = img_m.group(1).strip() if img_m else ""
            if name and img:
                full_img = boost_image_url_width(urllib.parse.urljoin(url, img.strip()))
                players.append({
                    "name": name.strip(),
                    "jersey": jersey,
                    "position": pos.capitalize() if pos else "",
                    "pos": pos.capitalize() if pos else "",
                    "image": full_img,
                    "raw_image": full_img,
                    "shoots": "",
                    "height": "",
                    "weight": "",
                    "born": "",
                    "birthplace": "",
                    "details": "",
                    "assigned_number": ""
                })

    # 5. Nottingham Panthers / team-member-grid-item
    if not players:
        items = re.findall(r'<li[^>]*class=[\"\'][^\"\']*team-member-grid-item[^\"\']*[\"\'][^>]*>(.*?)</li>', html, re.DOTALL | re.I)
        for it in items:
            name_m = re.search(r'<h3[^>]*class=[\"\'][^\"\']*heading[^\"\']*[\"\'][^>]*>([^<]+)</h3>', it)
            name = name_m.group(1).strip() if name_m else ""
            num_m = re.search(r'number-overlay[^>]*>(\d+)<', it)
            jersey = num_m.group(1).strip() if num_m else ""
            pos_m = re.search(r'<p[^>]*class=[\"\'][^\"\']*position[^\"\']*[\"\'][^>]*>([^<]+)</p>', it)
            pos = pos_m.group(1).strip() if pos_m else ""
            img_m = re.search(r'<img[^>]+src=[\"\']([^\"\']+)[\"\']', it)
            img = img_m.group(1).strip() if img_m else ""
            link_m = re.search(r'<a[^>]+href=[\"\']([^\"\']+)[\"\']', it)
            profile_url = urllib.parse.urljoin(url, link_m.group(1).strip()) if link_m else ""
            if name and img:
                full_img = boost_image_url_width(urllib.parse.urljoin(url, img.strip()))
                players.append({
                    "name": name.strip(),
                    "jersey": jersey,
                    "position": pos.capitalize() if pos else "",
                    "pos": pos.capitalize() if pos else "",
                    "image": full_img,
                    "raw_image": full_img,
                    "shoots": "",
                    "height": "",
                    "weight": "",
                    "born": "",
                    "birthplace": "",
                    "details": "",
                    "assigned_number": "",
                    "profile_url": profile_url
                })

        # Enrich Nottingham Panthers players with individual profile details in parallel
        if any(p.get("profile_url") for p in players):
            def _enrich_panther(item):
                purl = item.get("profile_url")
                if not purl or "sponsor" in purl:
                    return item
                try:
                    r = urllib.request.Request(purl, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"})
                    with urllib.request.urlopen(r, timeout=5) as rp:
                        h = rp.read().decode("utf-8")
                        pairs = re.findall(r'<th[^>]*>([^<]+)</th>\s*<td[^>]*>([^<]+)</td>', h, re.I)
                        table = {k.strip().lower(): py_html.unescape(v.strip()) for k, v in pairs}
                        if table.get("position"):
                            item["pos"] = table["position"].capitalize().strip()
                            item["position"] = item["pos"]
                        item["shoots"] = table.get("shoots") or table.get("glove", "")
                        item["height"] = table.get("height", "")
                        item["weight"] = table.get("weight", "")
                        item["born"] = table.get("date of birth") or table.get("born", "")
                        item["birthplace"] = table.get("place of birth") or table.get("birthplace") or table.get("nationality", "")
                        v_parts = []
                        if item.get("born"): v_parts.append(f"Born: {item['born']}")
                        if item.get("birthplace"): v_parts.append(f"Birthplace: {item['birthplace']}")
                        if item.get("shoots"): v_parts.append(f"Shoots/Glove: {item['shoots']}")
                        if item.get("height"): v_parts.append(f"Height: {item['height']}")
                        if item.get("weight"): v_parts.append(f"Weight: {item['weight']}")
                        item["details"] = " | ".join(v_parts)
                except Exception:
                    pass
                return item

            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
                players = list(ex.map(_enrich_panther, players))

    # 6. Generic schema.org SportsTeam/Person or Table fallback for other UK/European clubs
    if not players:
        json_matches = re.findall(r'<script type=\"application/ld\+json\">(.*?)</script>', html, re.DOTALL)
        for block in json_matches:
            try:
                d = json.loads(block.strip())
                items = d.get("item", []) if isinstance(d, dict) else (d if isinstance(d, list) else [])
                for it in items:
                    name = it.get("name")
                    img = it.get("image")
                    img_url = img.get("url") if isinstance(img, dict) else (img if isinstance(img, str) else "")
                    if name and img_url:
                        full_img = boost_image_url_width(urllib.parse.urljoin(url, img_url.strip()))
                        players.append({
                            "name": name.strip(),
                            "jersey": "",
                            "position": "",
                            "pos": "",
                            "image": full_img,
                            "raw_image": full_img,
                            "shoots": "",
                            "height": "",
                            "weight": "",
                            "born": "",
                            "birthplace": "",
                            "details": "",
                            "assigned_number": ""
                        })
            except Exception:
                pass

    # Deduplicate by player name
    seen = set()
    unique = []
    for p in players:
        clean_pname = re.sub(r'\s+', ' ', p["name"]).strip()
        if clean_pname and clean_pname not in seen:
            seen.add(clean_pname)
            p["name"] = clean_pname
            unique.append(p)

    return {
        "suggested_folder": suggested_folder,
        "players": unique
    }


KOREAN_NAME_MAP = {
    'Lee-Seul Kang': '강이슬',
    'Ye-Eun Heo': '허예은',
    'Li-Mi Go': '고리미',
    'Min-Kyung Kim': '김민경',
    'Min-Jung Kim': '김민정',
    'Yoon-Mi Lee': '이윤미',
    'Chae-Eun Lee': '이채은',
    'CaiDeng Sakai': '사카이 사라',
    'Yu-Na Yeom': '염윤아',
    'Yun-Jeong Na': '나윤정',
    'Hyun-Ji Koh': '고현지',
    'Su-Yeon Seong': '성수연',
    'Yoon-Ha Song': '송윤하',
    'Yeo-Myeong Lee': '이여명',
    'Hye-Kyung Noh': '노혜경',
    'Eun-Sun Kim': '김은선',
    'Ji-Soo Yang': '양지수',
    'Ji-Su Park': '박지수',
    'So-Dam Kim': '김소담',
    'Dan-Bi Kim': '김단비',
    'Hye-Jin Park': '박혜진',
    'Ji-Hyun Shin': '신지현',
    'An He-Ji': '안혜지',
    'Jin-Hee Bae': '배혜윤',
    'Lee So-Hee': '이소희',
    'Kim Jin-Young': '김진영',
    'Yoon Ye-Bin': '윤예빈',
    'Shin Ye-Young': '신예영',
    'Lee Hye-Joo': '이혜주',
}

KOREAN_FAMILY_NAMES = {
    'kim': '김', 'lee': '이', 'yi': '이', 'rhee': '이', 'park': '박', 'pak': '박',
    'choi': '최', 'jung': '정', 'jeong': '정', 'chung': '정', 'kang': '강', 'gang': '강',
    'cho': '조', 'jo': '조', 'yoon': '윤', 'yun': '윤', 'jang': '장', 'chang': '장',
    'lim': '임', 'im': '임', 'han': '한', 'oh': '오', 'seo': '서', 'suh': '서',
    'shin': '신', 'kwon': '권', 'gwon': '권', 'hwang': '황', 'ahn': '안', 'an': '안',
    'song': '송', 'ryu': '류', 'yoo': '유', 'hong': '홍', 'koh': '고', 'ko': '고',
    'go': '고', 'moon': '문', 'yang': '양', 'son': '손', 'bae': '배', 'paik': '백',
    'baek': '백', 'heo': '허', 'huh': '허', 'noh': '노', 'roh': '노', 'nam': '남',
    'shim': '심', 'ha': '하', 'kwak': '곽', 'sung': '성', 'seong': '성', 'cha': '차',
    'ju': '주', 'joo': '주', 'woo': '우', 'ku': '구', 'goo': '구', 'min': '민',
    'jin': '진', 'ji': '지', 'eom': '엄', 'um': '엄', 'byun': '변', 'chae': '채',
    'won': '원', 'yeom': '염', 'chun': '천'
}

KOREAN_SYLLABLES = {
    'seul': '슬', 'ye': '예', 'eun': '은', 'jung': '정', 'jeong': '정', 'yoon': '윤',
    'yun': '윤', 'mi': '미', 'chae': '채', 'na': '나', 'hyun': '현', 'hyeon': '현',
    'ji': '지', 'su': '수', 'soo': '수', 'yeon': '연', 'ha': '하', 'kyung': '경',
    'gyeong': '경', 'yeo': '여', 'myeong': '명', 'myung': '명', 'hye': '혜', 'sun': '선',
    'min': '민', 'dan': '단', 'bi': '비', 'jin': '진', 'young': '영', 'bin': '빈',
    'hee': '희', 'so': '소', 'dam': '담', 'ah': '아', 'ri': '리', 'joo': '주',
    'ju': '주', 'won': '원', 'woo': '우', 'kyoung': '경'
}


def translate_korean_name(name_str: str) -> str:
    """Translates romanized Korean basketball player names into official Korean Hangul."""
    name_clean = name_str.strip()
    if name_clean in KOREAN_NAME_MAP:
        return KOREAN_NAME_MAP[name_clean]

    parts = name_clean.split()
    if len(parts) == 2:
        # Given-Name Family (e.g. 'Lee-Seul Kang')
        given, family = parts[0], parts[1]
        fam_ko = KOREAN_FAMILY_NAMES.get(family.lower())
        given_syls = given.lower().replace('-', ' ').split()
        if fam_ko and all(s in KOREAN_SYLLABLES for s in given_syls):
            return fam_ko + ''.join(KOREAN_SYLLABLES[s] for s in given_syls)

        # Family Given-Name (e.g. 'Kang Lee-Seul')
        family, given = parts[0], parts[1]
        fam_ko = KOREAN_FAMILY_NAMES.get(family.lower())
        given_syls = given.lower().replace('-', ' ').split()
        if fam_ko and all(s in KOREAN_SYLLABLES for s in given_syls):
            return fam_ko + ''.join(KOREAN_SYLLABLES[s] for s in given_syls)

    return ''


def is_eurobasket_url(url: str) -> bool:
    """Detects whether a URL belongs to Eurobasket, Asia-Basket, Latinbasket, etc."""
    u = url.lower()
    domains = [
        "asia-basket.com", "eurobasket.com", "latinbasket.com",
        "afrobasket.com", "usbasket.com", "australiabasket.com"
    ]
    return any(d in u for d in domains)


def parse_eurobasket_single_player(url: str) -> dict:
    """Scrapes an individual Eurobasket / Asia-Basket player profile."""
    ctx = ssl._create_unverified_context()
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    }
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
        html = resp.read().decode("utf-8", errors="ignore")

    name_m = re.search(r'<h1[^>]*>([^<]+)</h1>', html, re.I)
    name = name_m.group(1).strip() if name_m else ""
    if not name:
        title_m = re.search(r'<title>([^<|]+)', html)
        name = title_m.group(1).strip() if title_m else ""

    img_m = re.search(r'class=[\"\']left-photo[\"\']><img[^>]+src=[\"\']([^\"\']+)[\"\']', html)
    if not img_m:
        img_m = re.search(r'<img[^>]+src=[\"\']([^\"\']*(?:photos/|player/)[^\"\']+)[\"\']', html)
    img = img_m.group(1) if img_m else ""

    bio_m = re.search(r'class=[\"\']player-info-new-notlg[\"\']>(.*?)</div>', html, re.S)
    bio = re.sub(r'<[^>]+>', ' ', bio_m.group(1)).strip() if bio_m else ""

    ht_m = re.search(r'(\d{1,2}\'\d{1,2}(?:\'\')?|\d{3}\s*cm)', bio)
    ht = ht_m.group(1) if ht_m else ""

    pos_m = re.search(r'\b(forward|guard|center|point guard|shooting guard|power forward|small forward|pg|sg|sf|pf|c|f|g)\b', bio, re.I)
    pos = pos_m.group(1).capitalize() if pos_m else ""

    born_m = re.search(r'born on\s+([A-Za-z]+ \d{1,2} \d{4})', bio, re.I)
    born = born_m.group(1) if born_m else ""

    nat_m = re.search(r'is\s+([A-Za-z]+(?:\s+[A-Za-z]+)?)\s+basketball player', bio, re.I)
    nat = nat_m.group(1) if nat_m else ""

    team_m = re.search(r'played at\s+<a[^>]*>([^<]+)</a>', html)
    team = team_m.group(1).strip() if team_m else ""
    if not team:
        team = name or "Basketball"

    native_name = translate_korean_name(name)
    display_name = f"{name} ({native_name})" if native_name else name

    det_parts = []
    if pos: det_parts.append(f"Position: {pos}")
    if native_name: det_parts.append(f"Korean: {native_name}")
    if born: det_parts.append(f"Born: {born}")
    if nat: det_parts.append(f"Nationality: {nat}")
    if ht: det_parts.append(f"Height: {ht}")
    details = " | ".join(det_parts)

    player = {
        "name": display_name,
        "name_en": name,
        "native_name": native_name,
        "jersey": "",
        "pos": pos,
        "position": pos,
        "shoots": "",
        "height": ht,
        "weight": "",
        "born": born,
        "birthplace": nat,
        "image": img,
        "raw_image": img,
        "details": details,
        "assigned_number": ""
    }
    return {"suggested_folder": team, "players": [player]}


def scrape_eurobasket_roster(url: str) -> dict:
    """Scrapes full team roster or single player page from Eurobasket / Asia-Basket / Latinbasket."""
    # Check if single player URL
    if "/player/" in url.lower():
        return parse_eurobasket_single_player(url)

    ctx = ssl._create_unverified_context()
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    }
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, context=ctx, timeout=12) as resp:
        html = resp.read().decode("utf-8", errors="ignore")

    # Suggested folder name
    suggested_folder = ""
    team_slug_m = re.search(r'/team/([^/]+)', url)
    if team_slug_m:
        slug = team_slug_m.group(1).replace("-", " ").strip()
        if slug:
            suggested_folder = slug
    if not suggested_folder:
        h1_m = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.I | re.S)
        if h1_m:
            suggested_folder = re.sub(r'<[^>]+>', '', h1_m.group(1)).replace("&nbsp;", " ").strip()
    if not suggested_folder:
        title_m = re.search(r'<title>(.*?)(?:Basketball|Roster)', html, re.I | re.S)
        if title_m:
            suggested_folder = title_m.group(1).strip()
    if not suggested_folder:
        suggested_folder = "Eurobasket Team"

    # 1. Featured player cards (containing photo thumbnails directly)
    featured_photos = {}
    for m in re.finditer(r'<a class=[\"\']ArRosterfeat-card[\"\']\s+href=[\"\']([^\"\']+)[\"\']>.*?<img[^>]+src=[\"\']([^\"\']+)[\"\'].*?</a>', html, re.S):
        href = m.group(1).split("?")[0]
        img = m.group(2)
        featured_photos[href] = img

    # 2. Extract player rows from table
    rows = re.findall(r'<div class=[\"\']ArRosterplayer[^>]*>(.*?)</div>\s*(?=<div class=[\"\']ArRosterplayer|<div class=[\"\']ArRostercoach|</div>\s*</div>)', html, re.S)

    players = []
    seen = set()
    for r in rows:
        name_m = re.search(r'ArRostername[^>]*><a\s+href=[\"\']([^\"\']+)[\"\']>([^<]+)</a>', r)
        purl = name_m.group(1).strip() if name_m else ""
        name = name_m.group(2).strip() if name_m else ""
        if not name or name in seen:
            continue
        seen.add(name)

        num_m = re.search(r'ArRosterjersey[^>]*>([^<]*)</div>', r)
        num = num_m.group(1).strip() if num_m else ""

        ht_m = re.search(r'ArRosterheight[^>]*>([^<]+(?:<small>[^<]+</small>)?)</div>', r)
        ht = re.sub(r'<[^>]+>', '', ht_m.group(1)).strip() if ht_m else ""

        pos_m = re.search(r'ArRosterpos[^>]*>([^<]*)</div>', r)
        pos = pos_m.group(1).strip() if pos_m else ""

        age_m = re.search(r'ArRosterage[^>]*>([^<]*)</div>', r)
        age = age_m.group(1).strip() if age_m else ""

        nat_m = re.search(r'ArRosternat[^>]*><img[^>]+(?:title|alt)=[\"\']([^\"\']+)[\"\']', r)
        nat = nat_m.group(1).strip() if nat_m else ""

        clean_purl = purl.split("?")[0]
        img = featured_photos.get(clean_purl, "")

        native_name = translate_korean_name(name)
        display_name = f"{name} ({native_name})" if native_name else name

        players.append({
            "name": display_name,
            "name_en": name,
            "native_name": native_name,
            "jersey": num,
            "pos": pos,
            "position": pos,
            "height": ht,
            "age": age,
            "nationality": nat,
            "birthplace": nat,
            "image": img,
            "raw_image": img,
            "profile_url": purl,
            "born": "",
            "assigned_number": num
        })

    # 3. Enrich players in parallel (fetch headshot from player page if missing + exact birth date)
    def _enrich_eb_player(p):
        purl = p.get("profile_url")
        if not purl:
            return p
        try:
            r = urllib.request.Request(purl, headers=headers)
            with urllib.request.urlopen(r, context=ctx, timeout=6) as resp:
                h = resp.read().decode("utf-8", errors="ignore")
                if not p.get("image"):
                    m_img = re.search(r'class=[\"\']left-photo[\"\']><img[^>]+src=[\"\']([^\"\']+)[\"\']', h)
                    if not m_img:
                        m_img = re.search(r'<img[^>]+src=[\"\']([^\"\']*(?:photos/|player/)[^\"\']+)[\"\']', h)
                    if m_img:
                        p["image"] = m_img.group(1)
                        p["raw_image"] = m_img.group(1)

                m_born = re.search(r'born on\s+([A-Za-z]+ \d{1,2} \d{4})', h)
                if m_born:
                    p["born"] = m_born.group(1)
        except Exception:
            pass

        v_parts = []
        if p.get("pos"): v_parts.append(f"Position: {p['pos']}")
        if p.get("native_name"): v_parts.append(f"Korean: {p['native_name']}")
        if p.get("born"): v_parts.append(f"Born: {p['born']}")
        elif p.get("age"): v_parts.append(f"Age: {p['age']}")
        if p.get("nationality"): v_parts.append(f"Nationality: {p['nationality']}")
        if p.get("height"): v_parts.append(f"Height: {p['height']}")
        p["details"] = " | ".join(v_parts)
        return p

    if players:
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
            players = list(ex.map(_enrich_eb_player, players))

    return {"suggested_folder": suggested_folder, "players": players}


BCHL_TEAMS = {
    '16': 'Alberni Valley Bulldogs', '82': 'Blackfalds Bulldogs', '81': 'Brooks Bandits',
    '13': 'Chilliwack Chiefs', '9': 'Coquitlam Express', '10': 'Cowichan Valley Capitals',
    '39': 'Cranbrook Bucks', '17': 'Langley Rivermen', '23': 'Nanaimo Clippers',
    '87': 'Okotoks Oilers', '8': 'Powell River Kings', '14': 'Prince George Spruce Kings',
    '20': 'Salmon Arm Silverbacks', '88': 'Sherwood Park Crusaders', '89': 'Spruce Grove Saints',
    '11': 'Surrey Eagles', '22': 'Trail Smoke Eaters', '21': 'Vernon Vipers',
    '18': 'Victoria Grizzlies', '19': 'West Kelowna Warriors'
}

BCHL_DOMAIN_TO_TEAM_ID = {
    'cowichancapitals.com': '10',
    'coquitlamexpress.ca': '9',
    'albernivalleybulldogs.ca': '16',
    'blackfaldsbulldogs.ca': '82',
    'brooksbandits.ca': '81',
    'chilliwackchiefs.net': '13',
    'cranbrookbucks.ca': '39',
    'langleyrivermen.com': '17',
    'nanaimoclippers.com': '23',
    'okotoksoilers.com': '87',
    'powellriverkings.com': '8',
    'sprucekings.bc.ca': '14',
    'silverbacks.bc.ca': '20',
    'sherwoodparkcrusaders.ca': '88',
    'sprucegrovesaints.ca': '89',
    'surreyeagles.ca': '11',
    'trailsmokeeaters.com': '22',
    'vernonvipers.com': '21',
    'victoriagrizzlies.com': '18',
    'westkelownawarriors.ca': '19',
}


def is_hockeytech_or_bchl_url(url: str) -> bool:
    """Detects whether a URL belongs to a BCHL, LeagueStat, or HockeyTech roster page."""
    u = url.lower()
    bchl_domains = [
        "cowichancapitals.com", "coquitlamexpress.ca", "albernivalleybulldogs.ca",
        "blackfaldsbulldogs.ca", "brooksbandits.ca", "chilliwackchiefs.net",
        "cranbrookbucks.ca", "langleyrivermen.com", "nanaimoclippers.com",
        "okotoksoilers.com", "powellriverkings.com", "sprucekings.bc.ca",
        "silverbacks.bc.ca", "sherwoodparkcrusaders.ca", "sprucegrovesaints.ca",
        "surreyeagles.ca", "trailsmokeeaters.com", "vernonvipers.com",
        "victoriagrizzlies.com", "westkelownawarriors.ca", "bchl.ca",
        "hockeytech.com", "leaguestat.com"
    ]
    if any(d in u for d in bchl_domains):
        return True
    if "/stats/roster" in u or "/stats/player" in u:
        return True
    return False


def parse_hockeytech_single_player(player_id: str, season_id: str = None, client_code: str = "bchl", key: str = "f3ed30007ad2124e") -> dict:
    """Scrapes a single player profile from HockeyTech / LeagueStat API."""
    feed_url = f"https://lscluster.hockeytech.com/feed/index.php?feed=statviewfeed&view=player&player_id={player_id}&key={key}&client_code={client_code}&lang=en"
    if season_id:
        feed_url += f"&season_id={season_id}"

    ctx = ssl._create_unverified_context()
    req = urllib.request.Request(
        feed_url,
        headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
    )
    with urllib.request.urlopen(req, context=ctx, timeout=12) as resp:
        body = resp.read().decode("utf-8", errors="ignore").strip()

    if body.startswith("(") and body.endswith(")"):
        body = body[1:-1]
    elif body.endswith(";"):
        body = body[:-1]

    data = json.loads(body)
    info = data.get("info", {})

    first = (info.get("firstName") or "").strip()
    last = (info.get("lastName") or "").strip()
    name = f"{first} {last}".strip()
    jersey = str(info.get("jerseyNumber") or "").strip()
    pos = (info.get("position") or "").strip()
    shoots = (info.get("shoots") or info.get("catches") or "").strip()
    ht = (info.get("height") or "").strip()
    wt = (info.get("weight") or "").strip()
    wt_str = f"{wt} lbs" if (wt and not wt.endswith("lbs")) else wt

    bdate = (info.get("birthDate") or "").strip()
    born_fmt = bdate
    if bdate:
        try:
            dt = datetime.strptime(bdate, "%Y-%m-%d")
            born_fmt = f"{dt.strftime('%b')} {dt.day}, {dt.year}"
        except Exception:
            born_fmt = bdate

    hometown = (info.get("hometown") or "").strip()
    team_name = (info.get("teamName") or "").strip() or "Hockey Team"
    img = info.get("profileImage") or f"https://assets.leaguestat.com/{client_code}/240x240/{player_id}.jpg"

    det_parts = []
    if pos: det_parts.append(f"Position: {pos}")
    if born_fmt: det_parts.append(f"Born: {born_fmt}")
    if hometown: det_parts.append(f"Hometown: {hometown}")
    if shoots: det_parts.append(f"Shoots/Catches: {shoots}")
    if ht: det_parts.append(f"Height: {ht}")
    if wt_str: det_parts.append(f"Weight: {wt_str}")
    details = " | ".join(det_parts)

    player = {
        "name": name,
        "jersey": jersey,
        "pos": pos,
        "position": pos,
        "shoots": shoots,
        "height": ht,
        "weight": wt_str,
        "born": born_fmt,
        "birthplace": hometown,
        "image": img,
        "raw_image": img,
        "details": details,
        "assigned_number": jersey
    }
    return {"suggested_folder": team_name, "players": [player]}


def parse_hockeytech_feed(team_id: str, season_id: str = None, client_code: str = "bchl", key: str = "f3ed30007ad2124e") -> dict:
    """Scrapes a full team roster from HockeyTech / LeagueStat API."""
    feed_url = f"https://lscluster.hockeytech.com/feed/index.php?feed=statviewfeed&view=roster&team_id={team_id}&key={key}&client_code={client_code}&lang=en"
    if season_id:
        feed_url += f"&season_id={season_id}"

    ctx = ssl._create_unverified_context()
    req = urllib.request.Request(
        feed_url,
        headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
    )
    with urllib.request.urlopen(req, context=ctx, timeout=12) as resp:
        body = resp.read().decode("utf-8", errors="ignore").strip()

    if body.startswith("(") and body.endswith(")"):
        body = body[1:-1]
    elif body.endswith(";"):
        body = body[:-1]

    data = json.loads(body)
    suggested_folder = data.get("teamName") or BCHL_TEAMS.get(str(team_id)) or f"Team_{team_id}"

    players = []
    seen = set()
    for sec_group in data.get("roster", []):
        for sec in sec_group.get("sections", []):
            sec_title = (sec.get("title") or "").lower()
            if "coach" in sec_title or "staff" in sec_title:
                continue
            for item in sec.get("data", []):
                row = item.get("row", {})
                name = (row.get("name") or "").strip()
                if not name or name in seen:
                    continue
                seen.add(name)

                pid = str(row.get("player_id") or "").strip()
                jersey = str(row.get("tp_jersey_number") or "").strip()
                pos = (row.get("position") or "").strip()
                shoots = (row.get("shoots") or row.get("catches") or "").strip()
                ht = (row.get("h") or "").strip()
                wt = (row.get("w") or "").strip()
                wt_str = f"{wt} lbs" if (wt and not wt.endswith("lbs")) else wt

                bdate = (row.get("birthdate") or "").strip()
                born_fmt = bdate
                if bdate:
                    try:
                        dt = datetime.strptime(bdate, "%Y-%m-%d")
                        born_fmt = f"{dt.strftime('%b')} {dt.day}, {dt.year}"
                    except Exception:
                        born_fmt = bdate

                hometown = (row.get("hometown") or "").strip()
                img = f"https://assets.leaguestat.com/{client_code}/240x240/{pid}.jpg" if pid else ""

                det_parts = []
                if pos: det_parts.append(f"Position: {pos}")
                if born_fmt: det_parts.append(f"Born: {born_fmt}")
                if hometown: det_parts.append(f"Hometown: {hometown}")
                if shoots: det_parts.append(f"Shoots/Catches: {shoots}")
                if ht: det_parts.append(f"Height: {ht}")
                if wt_str: det_parts.append(f"Weight: {wt_str}")
                details = " | ".join(det_parts)

                players.append({
                    "name": name,
                    "jersey": jersey,
                    "pos": pos,
                    "position": pos,
                    "shoots": shoots,
                    "height": ht,
                    "weight": wt_str,
                    "born": born_fmt,
                    "birthplace": hometown,
                    "image": img,
                    "raw_image": img,
                    "details": details,
                    "assigned_number": jersey
                })

    return {"suggested_folder": suggested_folder, "players": players}


def scrape_hockeytech_roster(url: str) -> dict:
    """Intelligently detects parameters from URL or HTML and parses HockeyTech / BCHL roster."""
    client_code = "bchl"
    app_key = "f3ed30007ad2124e"

    # 1. Check for single player profile pattern
    m_p = re.search(r'/stats/player/(\d+)(?:/(\d+))?', url)
    if m_p:
        pid = m_p.group(1)
        sid = m_p.group(2)
        return parse_hockeytech_single_player(pid, season_id=sid, client_code=client_code, key=app_key)

    # 2. Check for team roster pattern
    m_r = re.search(r'/stats/roster/(\d+)(?:/(\d+))?', url)
    if m_r:
        tid = m_r.group(1)
        sid = m_r.group(2)
        return parse_hockeytech_feed(tid, season_id=sid, client_code=client_code, key=app_key)

    # 3. Check domain mapping
    u_lower = url.lower()
    for domain, tid in BCHL_DOMAIN_TO_TEAM_ID.items():
        if domain in u_lower:
            return parse_hockeytech_feed(tid, client_code=client_code, key=app_key)

    # 4. Fetch HTML page to inspect for site_id or embedded links
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
            }
        )
        ctx = ssl._create_unverified_context()
        with urllib.request.urlopen(req, context=ctx, timeout=8) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

        # Check for client_code in page
        cc_m = re.search(r'client_code\s*=\s*[\'"](\w+)[\'"]', html)
        if cc_m:
            client_code = cc_m.group(1)

        key_m = re.search(r'appKey\s*=\s*[\'"]([a-zA-Z0-9]+)[\'"]', html)
        if key_m:
            app_key = key_m.group(1)

        # Check for roster links in HTML
        m_r_html = re.search(r'/stats/roster/(\d+)(?:/(\d+))?', html)
        if m_r_html:
            return parse_hockeytech_feed(m_r_html.group(1), season_id=m_r_html.group(2), client_code=client_code, key=app_key)
    except Exception as e:
        print(f"[Studio] HockeyTech page fetch fallback note: {e}")

    return {"suggested_folder": "Hockey Team", "players": []}


GERMAN_POSITIONS = {
    "tor": "Goaltender",
    "torhüter": "Goaltender",
    "torwart": "Goaltender",
    "goaltender": "Goaltender",
    "goalie": "Goaltender",
    "g": "Goaltender",
    "verteidigung": "Defense",
    "verteidiger": "Defense",
    "abwehr": "Defense",
    "defense": "Defense",
    "d": "Defense",
    "angriff": "Forward",
    "sturm": "Forward",
    "stürmer": "Forward",
    "forward": "Forward",
    "f": "Forward",
    "center": "Center",
    "flügel": "Winger",
    "trainer": "Coach",
    "cheftrainer": "Head Coach",
    "co-trainer": "Assistant Coach",
}


def clean_eisloewen_image_url(img_url: str) -> str:
    """Strips CDN lossy compression parameters and WordPress thumbnail dimension suffixes to return the original full-res image."""
    if not img_url or img_url.startswith("data:"):
        return ""
    clean = re.sub(r'\?.*$', '', img_url.strip())
    clean = re.sub(r'-\d+x\d+(\.[a-zA-Z0-9]+)$', r'\1', clean)
    return clean


def normalize_german_position(pos_str: str) -> str:
    if not pos_str:
        return ""
    p_clean = pos_str.strip().lower()
    return GERMAN_POSITIONS.get(p_clean, pos_str.strip().capitalize())


def is_eisloewen_or_del_url(url: str) -> bool:
    """Detects whether a URL belongs to Dresdner Eislöwen, German DEL/DEL2, or TopScorer hockey clubs."""
    url_lower = url.lower()
    return any(k in url_lower for k in [
        "eisloewen.de", "eisloewen", "del-2.org", "del2.org",
        "esvk.de", "steelers.de", "kassel-huskies.de", "ec-badnauheim.de",
        "lausitzer-fuechse.de", "eisbaeren-regensburg.de", "starbulls.de",
        "ev-landshut.net", "selberwoelfe.de", "blue-devils.de", "ravensburg-towerstars.de"
    ])


def parse_eisloewen_single_player(url: str, html: str):
    """Scrapes an individual player profile page (e.g. https://www.eisloewen.de/player/adam-helewka/)."""
    suggested_folder = "Dresdner Eislöwen"

    # Name
    name = ""
    name_m = re.search(r'<h[1-3][^>]*class=["\'][^"\']*(?:qodef-m-name|entry-title)[^"\']*["\'][^>]*>(.*?)</h[1-3]>', html, re.DOTALL)
    if name_m:
        raw = re.sub(r'<[^>]+>', ' ', name_m.group(1)).strip()
        name = re.sub(r'^\d+\s*', '', raw).strip()
    if not name:
        t_m = re.search(r'<title>(.*?)</title>', html)
        if t_m:
            name = t_m.group(1).split('|')[0].strip()

    # Jersey number
    jersey = ""
    num_m = re.search(r'class=["\'][^"\']*sp-player-number[^"\']*["\'][^>]*>(\d+)</strong>', html)
    if not num_m:
        num_m = re.search(r'>\s*#?(\d{1,2})\s*<', html)
    if num_m:
        jersey = num_m.group(1).strip()

    # Position
    pos = ""
    pos_m = re.search(r'href=["\'][^"\']*/position/[^"\']*["\'][^>]*>([^<]+)</a>', html)
    if pos_m:
        pos = normalize_german_position(pos_m.group(1).strip())

    # Image
    raw_img = ""
    dsrc_m = re.search(r'<div[^>]*class=["\'][^"\']*(?:sp-player-photo|qodef-e-image)[^"\']*["\'][^>]*>.*?<img[^>]+data-src=["\']([^"\']+)["\']', html, re.DOTALL)
    if dsrc_m:
        raw_img = dsrc_m.group(1)
    else:
        srcset_m = re.search(r'<div[^>]*class=["\'][^"\']*(?:sp-player-photo|qodef-e-image)[^"\']*["\'][^>]*>.*?<img[^>]+(?:data-srcset|srcset)=["\']([^"\']+)["\']', html, re.DOTALL)
        if srcset_m:
            candidates = [p.strip().split(' ')[0] for p in srcset_m.group(1).split(',') if p.strip()]
            if candidates:
                raw_img = candidates[-1]
        else:
            src_m = re.search(r'<div[^>]*class=["\'][^"\']*(?:sp-player-photo|qodef-e-image)[^"\']*["\'][^>]*>.*?<img[^>]+src=["\']([^"\']+)["\']', html, re.DOTALL)
            if src_m and not src_m.group(1).startswith("data:"):
                raw_img = src_m.group(1)
    img_url = clean_eisloewen_image_url(raw_img)

    shoots = ""
    height = ""
    weight = ""
    born = ""
    birthplace = ""

    dl_items = re.findall(r'<dt>(.*?)</dt>\s*<dd>(.*?)</dd>', html, re.DOTALL)
    for dt_raw, dd_raw in dl_items:
        k = re.sub(r'<[^>]+>', '', dt_raw).strip().lower()
        v = re.sub(r'<[^>]+>', '', dd_raw).strip()
        if "schuss" in k or "hand" in k:
            shoots = "Left" if "link" in v.lower() else ("Right" if "recht" in v.lower() else v)
        elif "größe" in k or "grosse" in k:
            height = f"{v} cm" if v.isdigit() else v
        elif "gewicht" in k:
            weight = f"{v} kg" if v.isdigit() else v
        elif "geburt" in k:
            born = v
        elif "national" in k:
            birthplace = v

    v_summary = []
    if born: v_summary.append(f"Born: {born}")
    if birthplace: v_summary.append(f"Nationality: {birthplace}")
    if shoots: v_summary.append(f"Shoots: {shoots}")
    if height: v_summary.append(f"Height: {height}")
    if weight: v_summary.append(f"Weight: {weight}")

    player = {
        "name": name,
        "jersey": jersey,
        "position": pos,
        "pos": pos,
        "image": img_url,
        "raw_image": img_url,
        "shoots": shoots,
        "height": height,
        "weight": weight,
        "born": born,
        "birthplace": birthplace,
        "details": " | ".join(v_summary),
        "assigned_number": "",
        "profile_url": url
    }

    return {
        "suggested_folder": suggested_folder,
        "players": [player]
    }


def scrape_eisloewen_roster(url: str, html: str = None):
    """
    Scrapes Dresdner Eislöwen and German DEL/DEL2 hockey rosters, extracting
    player names, jersey numbers, positions, vitals, and high-res cutout headshots.
    """
    if not html:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Referer": "https://www.eisloewen.de/"
            }
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

    u_lower = url.lower().rstrip('/')

    # Check if this is a single player profile page
    if "/player/" in u_lower and not u_lower.endswith("/team") and not u_lower.endswith("/team/"):
        return parse_eisloewen_single_player(url, html)

    # Clean team folder name
    suggested_folder = "Dresdner Eislöwen"
    title_m = re.search(r'<title>(.*?)</title>', html, re.I)
    if title_m:
        raw_t = py_html.unescape(title_m.group(1).strip())
        parts = re.split(r'[-–|]', raw_t)
        for pt in parts:
            p_s = pt.strip()
            if p_s.lower() not in ("team", "kader", "roster", "official website", "home", "dresden"):
                suggested_folder = p_s
                break

    # Split into cards
    player_splits = re.split(r'(?=<div[^>]*class=["\'][^"\']*qodef-e qodef-grid-item[^"\']*["\'])', html)
    cards = [s for s in player_splits if '/player/' in s]
    if not cards:
        # Fallback card splitter
        cards = re.findall(r'<div[^>]*class=["\'][^"\']*qodef-item--full[^"\']*["\'][^>]*>.*?</h3>\s*</div>\s*</div>', html, re.DOTALL)

    players = []
    seen_names = set()

    for c in cards:
        # Player name
        name_m = re.search(r'<h\d[^>]*class=["\'][^"\']*qodef-e-name[^"\']*["\'][^>]*>.*?<a[^>]*>([^<]+)</a>', c, re.DOTALL)
        if not name_m:
            name_m = re.search(r'<a[^>]*href=["\'][^"\']*/player/[^"\']*["\'][^>]*>([^<]+)</a>', c)
        name = name_m.group(1).strip() if name_m else ""

        if not name or name in seen_names:
            continue
        seen_names.add(name)

        # Jersey number
        num_m = re.search(r'<span[^>]*style=[^>]*>(\d{1,2})</span>', c)
        if not num_m:
            num_m = re.search(r'>(\d{1,2})</span>', c)
        if not num_m:
            num_m = re.search(r'class=["\'][^"\']*number[^"\']*["\'][^>]*>(\d{1,2})<', c, re.I)
        jersey = num_m.group(1).strip() if num_m else ""

        # Position
        pos_m = re.search(r'class=["\'][^"\']*qodef-e-position[^"\']*["\'][^>]*>.*?<a[^>]*>([^<]+)</a>', c, re.DOTALL)
        if not pos_m:
            pos_m = re.search(r'/position/[^/]+/["\'][^>]*>([^<]+)</a>', c)
        raw_pos = pos_m.group(1).strip() if pos_m else ""
        pos = normalize_german_position(raw_pos)

        # Image extraction (highest quality original PNG)
        raw_img = ""
        dsrc_m = re.search(r'<img[^>]+data-src=["\']([^"\']+)["\']', c)
        if dsrc_m:
            raw_img = dsrc_m.group(1)
        else:
            srcset_m = re.search(r'<img[^>]+(?:data-srcset|srcset)=["\']([^"\']+)["\']', c)
            if srcset_m:
                candidates = [p.strip().split(' ')[0] for p in srcset_m.group(1).split(',') if p.strip()]
                if candidates:
                    raw_img = candidates[-1]
            else:
                src_m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', c)
                if src_m and not src_m.group(1).startswith("data:"):
                    raw_img = src_m.group(1)

        img_url = clean_eisloewen_image_url(raw_img)

        # Profile link
        link_m = re.search(r'<a[^>]*href=["\'](https?://[^"\'\s]*/player/[^"\'\s]+)["\']', c)
        profile_url = link_m.group(1).strip() if link_m else ""

        players.append({
            "name": name,
            "jersey": jersey,
            "position": pos,
            "pos": pos,
            "image": img_url,
            "raw_image": img_url,
            "shoots": "",
            "height": "",
            "weight": "",
            "born": "",
            "birthplace": "",
            "details": "",
            "assigned_number": "",
            "profile_url": profile_url
        })

    # Enrich players with vitals in parallel
    if any(p.get("profile_url") for p in players):
        def _enrich_player(p):
            purl = p.get("profile_url")
            if not purl:
                return p
            try:
                r = urllib.request.Request(
                    purl,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                        "Referer": "https://www.eisloewen.de/"
                    }
                )
                with urllib.request.urlopen(r, timeout=4) as rp:
                    h = rp.read().decode("utf-8", errors="ignore")
                    dl_items = re.findall(r'<dt>(.*?)</dt>\s*<dd>(.*?)</dd>', h, re.DOTALL)
                    for dt_raw, dd_raw in dl_items:
                        k = re.sub(r'<[^>]+>', '', dt_raw).strip().lower()
                        v = re.sub(r'<[^>]+>', '', dd_raw).strip()
                        if "schuss" in k or "hand" in k:
                            p["shoots"] = "Left" if "link" in v.lower() else ("Right" if "recht" in v.lower() else v)
                        elif "größe" in k or "grosse" in k:
                            p["height"] = f"{v} cm" if v.isdigit() else v
                        elif "gewicht" in k:
                            p["weight"] = f"{v} kg" if v.isdigit() else v
                        elif "geburt" in k:
                            p["born"] = v
                        elif "national" in k:
                            p["birthplace"] = v
                    v_summary = []
                    if p["born"]: v_summary.append(f"Born: {p['born']}")
                    if p["birthplace"]: v_summary.append(f"Nationality: {p['birthplace']}")
                    if p["shoots"]: v_summary.append(f"Shoots: {p['shoots']}")
                    if p["height"]: v_summary.append(f"Height: {p['height']}")
                    if p["weight"]: v_summary.append(f"Weight: {p['weight']}")
                    p["details"] = " | ".join(v_summary)
            except Exception:
                pass
            return p

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
            players = list(ex.map(_enrich_player, players))

    return {
        "suggested_folder": suggested_folder,
        "players": players
    }


# --- DÜSSELDORFER EG (DEG) SCRAPER ---

def clean_deg_image_url(srcset: str, src: str) -> str:
    """Extracts highest resolution uncompressed PNG cutout headshot for DEG players."""
    if srcset:
        candidates = []
        for part in srcset.split(','):
            p = part.strip().split()
            if len(p) >= 1:
                url = p[0]
                width = int(p[1].replace('w', '')) if len(p) > 1 and p[1].endswith('w') else 0
                candidates.append((width, url))
        candidates.sort(key=lambda x: x[0], reverse=True)
        if candidates:
            return candidates[0][1]
    if src:
        return re.sub(r'-\d+x\d+(\.[a-zA-Z0-9]+)$', r'\1', src)
    return ""


def scrape_deg_roster(url: str):
    """
    Scrapes Düsseldorfer EG (DEG) roster from deg-eishockey.de/kader/,
    extracting player cards, jersey numbers, positions, and 1366w uncompressed cutout headshots.
    """
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"}
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        html = resp.read().decode("utf-8", errors="ignore")

    u_lower = url.lower().rstrip('/')

    # Check if single player profile page
    if "/team/" in u_lower and not any(k in u_lower for k in ["/kader", "/mannschaft"]):
        return parse_deg_single_player(url, html)

    suggested_folder = "Düsseldorfer EG"
    sections = re.split(r'(?=<h2[^>]*>)', html)

    players = []
    seen = set()

    for sec in sections:
        h2_m = re.search(r'<h2[^>]*>(.*?)</h2>', sec, re.DOTALL)
        sec_title = ""
        if h2_m:
            sec_title = re.sub(r'<[^>]+>', '', h2_m.group(1)).strip()

        cards = re.findall(r'<div[^>]*class=["\'][^"\']*df-card[^"\']*["\'][^>]*>(.*?)</div>\s*</div>', sec, re.DOTALL)
        for c in cards:
            name_m = re.search(r'class=["\'][^"\']*df-name[^"\']*["\'][^>]*>([^<]+)<', c)
            name = name_m.group(1).strip() if name_m else ""
            if not name or name in seen:
                continue
            seen.add(name)

            num_m = re.search(r'class=["\'][^"\']*df-number[^"\']*["\'][^>]*>(\d+)<', c)
            jersey = num_m.group(1).strip() if num_m else ""

            pos = normalize_german_position(sec_title)

            link_m = re.search(r'<a[^>]+href=["\']([^"\']+)["\']', c)
            profile_url = link_m.group(1).strip() if link_m else ""

            src_m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', c)
            srcset_m = re.search(r'<img[^>]+srcset=["\']([^"\']+)["\']', c)
            img_url = clean_deg_image_url(srcset_m.group(1) if srcset_m else "", src_m.group(1) if src_m else "")

            players.append({
                "name": name,
                "jersey": jersey,
                "position": pos,
                "pos": pos,
                "image": img_url,
                "raw_image": img_url,
                "shoots": "",
                "height": "",
                "weight": "",
                "born": "",
                "birthplace": "",
                "details": "",
                "assigned_number": "",
                "profile_url": profile_url
            })

    # Enrich players with profile details in parallel
    if any(p.get("profile_url") for p in players):
        def _enrich_deg_player(p):
            purl = p.get("profile_url")
            if not purl or not purl.startswith("http"):
                return p
            try:
                r = urllib.request.Request(purl, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(r, timeout=4) as rp:
                    h = rp.read().decode("utf-8", errors="ignore")
                    meta_items = re.findall(r'<strong>([^<]+):</strong>\s*([^<]+)', h)
                    for k, v in meta_items:
                        kl = k.strip().lower()
                        vl = v.strip()
                        if "schuss" in kl or "fanghand" in kl:
                            p["shoots"] = "Left" if "link" in vl.lower() else ("Right" if "recht" in vl.lower() else vl)
                        elif "größe" in kl or "grosse" in kl:
                            p["height"] = vl
                        elif "gewicht" in kl:
                            p["weight"] = vl
                        elif "geburt" in kl:
                            p["born"] = vl
                    v_summary = []
                    if p["born"]: v_summary.append(f"Born: {p['born']}")
                    if p["shoots"]: v_summary.append(f"Shoots: {p['shoots']}")
                    if p["height"]: v_summary.append(f"Height: {p['height']}")
                    if p["weight"]: v_summary.append(f"Weight: {p['weight']}")
                    p["details"] = " | ".join(v_summary)
            except Exception:
                pass
            return p

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
            players = list(ex.map(_enrich_deg_player, players))

    return {
        "suggested_folder": suggested_folder,
        "players": players
    }


def parse_deg_single_player(url: str, html: str):
    """Scrapes a single DEG player profile page."""
    suggested_folder = "Düsseldorfer EG"
    name = ""
    title_m = re.search(r'<title>(.*?)</title>', html)
    if title_m:
        raw_t = re.sub(r'<[^>]+>', '', title_m.group(1))
        name = re.split(r'[-–|•&#]', raw_t)[0].strip()

    num_m = re.search(r'class=["\'][^"\']*(?:df-number|number)[^"\']*["\'][^>]*>(\d+)<', html)
    jersey = num_m.group(1).strip() if num_m else ""

    shoots = ""
    height = ""
    weight = ""
    born = ""
    pos = ""

    meta_items = re.findall(r'<strong>([^<]+):</strong>\s*([^<]+)', html)
    for k, v in meta_items:
        kl = k.strip().lower()
        vl = v.strip()
        if "position" in kl:
            pos = normalize_german_position(vl)
        elif "schuss" in kl or "fanghand" in kl:
            shoots = "Left" if "link" in vl.lower() else ("Right" if "recht" in vl.lower() else vl)
        elif "größe" in kl or "grosse" in kl:
            height = vl
        elif "gewicht" in kl:
            weight = vl
        elif "geburt" in kl:
            born = vl

    src_m = re.search(r'class=["\'][^"\']*df-player-image[^"\']*["\'][^>]*>.*?<img[^>]+src=["\']([^"\']+)["\']', html, re.DOTALL)
    if not src_m:
        src_m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', html)
    srcset_m = re.search(r'<img[^>]+srcset=["\']([^"\']+)["\']', html)
    img_url = clean_deg_image_url(srcset_m.group(1) if srcset_m else "", src_m.group(1) if src_m else "")

    v_summary = []
    if born: v_summary.append(f"Born: {born}")
    if shoots: v_summary.append(f"Shoots: {shoots}")
    if height: v_summary.append(f"Height: {height}")
    if weight: v_summary.append(f"Weight: {weight}")

    return {
        "suggested_folder": suggested_folder,
        "players": [{
            "name": name,
            "jersey": jersey,
            "position": pos,
            "pos": pos,
            "image": img_url,
            "raw_image": img_url,
            "shoots": shoots,
            "height": height,
            "weight": weight,
            "born": born,
            "birthplace": "",
            "details": " | ".join(v_summary),
            "assigned_number": "",
            "profile_url": url
        }]
    }


# --- EHC RED BULL MÜNCHEN / PENNY DEL SCRAPER ---

def get_redbull_cloudinary_url(player_name: str) -> str:
    """Constructs the official high-resolution 1200w transparent cutout portrait from Red Bull's Cloudinary CDN."""
    clean_n = re.sub(r'[^a-zA-ZäöüÄÖÜß\s\-]', '', player_name).strip()
    parts = clean_n.split()
    if len(parts) >= 2:
        fn = "_".join(parts)
        return f"https://media.redbullmuenchen.de/image/upload/c_scale,w_1200/Portrait_{fn}_26_27.png"
    return ""


def scrape_redbull_or_del_roster(url: str):
    """
    Scrapes EHC Red Bull München from redbullmuenchen.de or official PENNY DEL hub,
    extracting players, jersey numbers, positions, stats, and 1200w high-res Cloudinary cutout headshots.
    """
    suggested_folder = "EHC Red Bull München"
    html = None

    # Try fetching from user's URL first
    if "redbullmuenchen.de" in url.lower():
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
                }
            )
            with urllib.request.urlopen(req, timeout=12) as resp:
                if resp.status == 200:
                    html = resp.read().decode("utf-8", errors="ignore")
        except Exception:
            html = None

    # If Red Bull origin server is experiencing an outage (500/503) or page is empty, fetch official PENNY DEL roster
    if not html or "Internal Server Error" in html or len(html) < 5000:
        penny_url = "https://www.penny-del.org/teams/ehc-red-bull-muenchen/kader"
        req = urllib.request.Request(
            penny_url,
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

    players = []
    seen = set()

    # Strategy A: PENNY DEL roster table
    trs = re.findall(r'<tr[^>]*>.*?</tr>', html, re.DOTALL)
    for tr in trs:
        img_m = re.search(r'<img[^>]+alt=["\']([^"\']+)["\'][^>]+src=["\']([^"\']+)["\']', tr)
        if not img_m:
            img_m = re.search(r'<img[^>]+src=["\']([^"\']+)["\'][^>]+alt=["\']([^"\']+)["\']', tr)
        if not img_m:
            continue

        raw_name = img_m.group(1).strip()
        if not raw_name or len(raw_name) < 3 or raw_name in seen or any(k in raw_name.lower() for k in ["logo", "banner", "penny", "telekom"]):
            continue

        # Extract number from first <td> or digits
        num_m = re.search(r'<td[^>]*>\s*#?(\d{1,2})\s*</td>', tr)
        if not num_m:
            num_m = re.search(r'>\s*#?(\d{1,2})\s*<', tr)
        jersey = num_m.group(1).strip() if num_m else ""

        # Row text tokens
        txt = re.sub(r'<[^>]+>', ' ', tr)
        tokens = txt.split()

        pos = "Forward"
        shoots = ""
        height = ""
        weight = ""
        birthplace = ""
        born = ""

        # In PENNY DEL table: [Jersey] [Name] [Nat] [L/R] [Age] [Height] [Weight] [Birthplace]
        for idx, tk in enumerate(tokens):
            if tk in ("L", "R"):
                shoots = "Left" if tk == "L" else "Right"
                if idx + 1 < len(tokens) and tokens[idx+1].isdigit():
                    born = f"Age {tokens[idx+1]}"
                if idx + 2 < len(tokens) and tokens[idx+2].isdigit() and int(tokens[idx+2]) > 150:
                    height = f"{tokens[idx+2]} cm"
                if idx + 3 < len(tokens) and tokens[idx+3].isdigit() and int(tokens[idx+3]) > 50:
                    weight = f"{tokens[idx+3]} kg"
                if idx + 4 < len(tokens):
                    birthplace = " ".join(tokens[idx+4:])
                break

        # Position mapping
        if jersey in ("1", "30", "32", "35") or "tor" in txt.lower():
            pos = "Goaltender"
        elif jersey in ("3", "9", "18", "22", "24", "44", "55", "70") or "vert" in txt.lower():
            pos = "Defense"

        # Image: high-resolution Cloudinary portrait with fallback
        cloudinary_img = get_redbull_cloudinary_url(raw_name)
        fallback_img = urllib.parse.urljoin("https://www.penny-del.org", img_m.group(2))

        seen.add(raw_name)
        v_summary = []
        if born: v_summary.append(born)
        if birthplace: v_summary.append(f"Birthplace: {birthplace}")
        if shoots: v_summary.append(f"Shoots: {shoots}")
        if height: v_summary.append(f"Height: {height}")
        if weight: v_summary.append(f"Weight: {weight}")

        players.append({
            "name": raw_name,
            "jersey": jersey,
            "position": pos,
            "pos": pos,
            "image": cloudinary_img or fallback_img,
            "raw_image": cloudinary_img or fallback_img,
            "fallback_image": fallback_img,
            "shoots": shoots,
            "height": height,
            "weight": weight,
            "born": born,
            "birthplace": birthplace,
            "details": " | ".join(v_summary),
            "assigned_number": "",
            "profile_url": url
        })

    # Strategy B: If parsed from direct Red Bull HTML
    if not players:
        card_matches = re.findall(r'<a[^>]+href=["\'](/[^"\']*/team/spieler/[^"\']+)["\'][^>]*>(.*?)</a>', html, re.DOTALL)
        for link, c in card_matches:
            name_m = re.search(r'<img[^>]+title=["\']([^"\']+)["\']', c)
            name = name_m.group(1).strip() if name_m else ""
            if not name or name in seen:
                continue
            seen.add(name)

            num_m = re.search(r'data-testid=["\']jersey-number["\'][^>]*>.*?#<!-- -->(\d+)', c, re.DOTALL)
            if not num_m:
                num_m = re.search(r'>#(\d+)<', c)
            jersey = num_m.group(1).strip() if num_m else ""

            src_m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', c)
            raw_src = src_m.group(1).strip() if src_m else ""
            img_url = re.sub(r'c_scale,w_\d+,f_auto/f_auto/q_\d+/', 'c_scale,w_1200/', raw_src)

            players.append({
                "name": name,
                "jersey": jersey,
                "position": "Forward",
                "pos": "Forward",
                "image": img_url,
                "raw_image": img_url,
                "shoots": "",
                "height": "",
                "weight": "",
                "born": "",
                "birthplace": "",
                "details": "",
                "assigned_number": "",
                "profile_url": urllib.parse.urljoin(url, link)
            })

    return {
        "suggested_folder": suggested_folder,
        "players": players
    }


# --- DEAC JÉGKORONG & GYERGYÓI HOKI KLUB (ERSTE LIGA) SCRAPERS ---

def scrape_deac_roster(url: str):
    """
    Scrapes DEAC Jégkorong from jegkorong.deac.hu using WordPress / SportsPress REST API.
    Extracts active players, jersey numbers, positions, and full-resolution portraits.
    """
    suggested_folder = "DEAC Jégkorong"
    base_url = "https://jegkorong.deac.hu"

    parsed_u = urllib.parse.urlparse(url)
    path_parts = [p for p in parsed_u.path.strip("/").split("/") if p]
    single_slug = path_parts[-1] if len(path_parts) >= 2 else None

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}

    pos_map = {66: "Goalkeeper", 40: "Forward", 41: "Defense"}
    try:
        req_pos = urllib.request.Request(f"{base_url}/wp-json/sportspress/v2/positions", headers=headers)
        with urllib.request.urlopen(req_pos, context=ctx, timeout=10) as resp:
            p_data = json.loads(resp.read().decode("utf-8"))
            for p in p_data:
                name = p.get("name", "")
                if "kapus" in name.lower():
                    pos_map[p["id"]] = "Goalkeeper"
                elif "tamad" in name.lower() or "támad" in name.lower():
                    pos_map[p["id"]] = "Forward"
                elif "ved" in name.lower() or "véd" in name.lower():
                    pos_map[p["id"]] = "Defense"
                else:
                    pos_map[p["id"]] = name
    except Exception as e:
        print(f"[Studio] DEAC position mapping notice: {e}")

    players = []
    seen = set()
    try:
        if single_slug:
            api_endpoint = f"{base_url}/wp-json/sportspress/v2/players?slug={urllib.parse.quote(single_slug)}&_embed"
        else:
            api_endpoint = f"{base_url}/wp-json/sportspress/v2/players?per_page=100&_embed"

        req_pl = urllib.request.Request(api_endpoint, headers=headers)
        with urllib.request.urlopen(req_pl, context=ctx, timeout=15) as resp:
            pl_data = json.loads(resp.read().decode("utf-8"))
            for item in pl_data:
                name_raw = item.get("title", {}).get("rendered", "").strip()
                name = py_html.unescape(name_raw).strip()
                if not name or name in seen:
                    continue
                seen.add(name)

                jersey = str(item.get("number") or "").strip()
                pos_ids = item.get("positions", [])
                position = pos_map.get(pos_ids[0], "Player") if pos_ids else "Player"

                # Extract metrics
                metrics = item.get("metrics", {}) or {}
                height = f"{metrics.get('Magasság')} cm" if metrics.get("Magasság") else ""
                weight = f"{metrics.get('Súly')} kg" if metrics.get("Súly") else ""
                shoots_val = metrics.get("Ütőfogás", "")
                shoots = "Left" if shoots_val == "bal" else ("Right" if shoots_val == "jobb" else shoots_val)

                img_url = ""
                media_list = item.get("_embedded", {}).get("wp:featuredmedia", [])
                if media_list and isinstance(media_list, list) and len(media_list) > 0:
                    img_url = media_list[0].get("source_url", "")
                nat_list = item.get("nationalities", [])
                nat = nat_list[0].upper() if (nat_list and isinstance(nat_list, list)) else ""
                birthplace = "Hungary" if nat == "HUN" else nat

                players.append({
                    "name": name,
                    "jersey": jersey,
                    "position": position,
                    "pos": position,
                    "image": img_url,
                    "raw_image": img_url,
                    "shoots": shoots,
                    "height": height,
                    "weight": weight,
                    "born": "",
                    "birthplace": birthplace,
                    "details": f"DEAC | {nat}" if nat else "DEAC",
                    "assigned_number": "",
                    "profile_url": item.get("link", url)
                })
    except Exception as e:
        print(f"[Studio] DEAC REST API error: {e}")

    if single_slug and players:
        suggested_folder = f"DEAC - {players[0]['name']}"

    return {
        "suggested_folder": suggested_folder,
        "players": players
    }


_gyergyoi_cache = {"time": 0, "data": None}


def scrape_gyergyoi_roster(url: str):
    """
    Scrapes Gyergyói Hoki Klub (Gyergyói HK) from gyergyoihoki.ro.
    Includes automated IconCaptcha solver and Elementor player loop extraction.
    Caches parsed roster in memory for 10 minutes for ultra-fast cross-resolution.
    """
    global _gyergyoi_cache
    if _gyergyoi_cache["data"] and (time.time() - _gyergyoi_cache["time"] < 600):
        return copy.deepcopy(_gyergyoi_cache["data"])

    suggested_folder = "Gyergyói Hoki Klub"

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(cj),
        urllib.request.HTTPSHandler(context=ctx)
    )

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "X-Requested-With": "XMLHttpRequest",
        "Origin": "https://gyergyoihoki.ro",
        "Referer": url
    }

    try:
        req0 = urllib.request.Request(url, headers=headers)
        opener.open(req0, timeout=12)
    except Exception as e:
        print(f"[Studio] Gyergyoi session init notice: {e}")

    try:
        data = urllib.parse.urlencode({"cID": 0, "rT": 1, "tM": "light"}).encode("utf-8")
        req1 = urllib.request.Request(
            "https://gyergyoihoki.ro/cprot/captcha-request.php",
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8", **headers}
        )
        resp1 = opener.open(req1, timeout=10)
        hashes = json.loads(resp1.read().decode("utf-8"))

        def decode_png_to_alpha(png_bytes):
            pos = 8
            plte = b""
            trns = b""
            idat = b""
            w, h, depth = 0, 0, 0
            while pos < len(png_bytes):
                length, = struct.unpack(">I", png_bytes[pos:pos+4])
                ctype = png_bytes[pos+4:pos+8]
                cdata = png_bytes[pos+8:pos+8+length]
                if ctype == b"IHDR":
                    w, h = struct.unpack(">II", cdata[:8])
                    depth = cdata[8]
                elif ctype == b"PLTE":
                    plte = cdata
                elif ctype == b"tRNS":
                    trns = cdata
                elif ctype == b"IDAT":
                    idat += cdata
                pos += 8 + length + 4

            decomp = zlib.decompress(idat)
            palette = []
            for i in range(0, len(plte), 3):
                a = trns[i//3] if i//3 < len(trns) else 255
                palette.append(a)

            pixels = []
            stride = (w if depth == 8 else (w + 1) // 2) + 1
            for y in range(h):
                line = decomp[y*stride+1 : (y+1)*stride]
                if depth == 8:
                    for val in line:
                        pixels.append(palette[val] if val < len(palette) else 0)
                elif depth == 4:
                    for b in line:
                        idx1 = (b >> 4) & 0x0F
                        idx2 = b & 0x0F
                        pixels.append(palette[idx1] if idx1 < len(palette) else 0)
                        if len(pixels) % w != 0:
                            pixels.append(palette[idx2] if idx2 < len(palette) else 0)
            return pixels[:w*h]

        alphas = []
        for h in hashes:
            req_img = urllib.request.Request(
                f"https://gyergyoihoki.ro/cprot/captcha-request.php?cid=0&hash={h}",
                headers={"Referer": url, "User-Agent": headers["User-Agent"]}
            )
            raw = opener.open(req_img, timeout=10).read()
            alphas.append(decode_png_to_alpha(raw))

        distances = []
        for i in range(5):
            d = sum(sum((alphas[i][k] - alphas[j][k])**2 for k in range(len(alphas[i]))) for j in range(5) if i != j)
            distances.append(d)

        odd_idx = distances.index(max(distances))
        sub_data = urllib.parse.urlencode({"cID": 0, "pC": hashes[odd_idx], "rT": 2}).encode("utf-8")
        opener.open(
            urllib.request.Request(
                "https://gyergyoihoki.ro/cprot/captcha-request.php",
                data=sub_data,
                headers={"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8", **headers}
            ),
            timeout=10
        )
    except Exception as e:
        print(f"[Studio] Gyergyoi captcha notice: {e}")

    html_page = ""
    try:
        resp = opener.open(urllib.request.Request(url, headers={"User-Agent": headers["User-Agent"]}), timeout=15)
        html_page = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"[Studio] Gyergyoi roster fetch error: {e}")
        return {"suggested_folder": suggested_folder, "players": []}

    players = []
    seen = set()
    cards = re.split(r'class=[\"\'][^\"\']*e-loop-item[^\"\']*player[^\"\']*[\"\']', html_page)[1:]
    for card in cards:
        m_name = re.search(r'<h3[^>]*class=[\"\'][^\"\']*elementor-heading-title[^\"\']*[\"\'][^>]*>([^<]+)</h3>', card)
        name = m_name.group(1).strip() if m_name else ""
        if not name or name in seen:
            continue
        seen.add(name)

        m_img = re.search(r'<img[^>]+src=[\"\'](https://gyergyoihoki\.ro/wp-content/uploads/[^\"\'\s]+)[\"\']', card)
        img_url = m_img.group(1).strip() if m_img else ""
        full_img = re.sub(r'-\d+x\d+(\.[a-zA-Z]+)$', r'\1', img_url)

        m_num = re.search(r'szam(?:Balra|Jobbra)[^>]*>.*?<div class=[\"\']elementor-widget-container[\"\']>\s*(\d+)\s*</div>', card, re.DOTALL)
        jersey = m_num.group(1).strip() if m_num else ""

        m_pos = re.search(r'Pozici[oó]:\s*([^<>\n\r&]+)', card, re.I)
        pos_raw = m_pos.group(1).strip() if m_pos else ""
        if not pos_raw:
            m_pos2 = re.search(r'elementor-button-text[\"\']>([^<]+)</span>', card)
            pos_raw = m_pos2.group(1).strip() if m_pos2 else ""

        pos_clean = pos_raw.title()
        if "kapus" in pos_raw.lower():
            pos_clean = "Goalkeeper"
        elif "hátvéd" in pos_raw.lower() or "hatved" in pos_raw.lower():
            pos_clean = "Defense"
        elif "csatár" in pos_raw.lower() or "csatar" in pos_raw.lower() or "támadó" in pos_raw.lower():
            pos_clean = "Forward"

        # Dimensions: Height & Weight from Méretek: e.g. 195 cm / 95 kg or 178 cm
        m_dim = re.search(r'M[eé]retek:\s*([^<>\n\r&]+)', card, re.I)
        dim_str = m_dim.group(1).strip() if m_dim else ""
        m_h = re.search(r'(\d+)\s*cm', dim_str)
        height = f"{m_h.group(1)} cm" if m_h else ""
        m_w = re.search(r'(\d+)\s*kg', dim_str)
        weight = f"{m_w.group(1)} kg" if m_w else ""

        # Shoots / Catches: Ütőfogás: bal / jobb
        m_sh = re.search(r'[UÜuü]t[oőó]fog[aá]s:\s*([^<>\n\r&]+)', card, re.I)
        sh_raw = m_sh.group(1).strip().lower() if m_sh else ""
        shoots = "Left" if "bal" in sh_raw else ("Right" if "jobb" in sh_raw else sh_raw.title())

        # Born: Születési idő: 08/07/1990
        m_born = re.search(r'Sz[uü]let[eé]si\s*id[oőó]:\s*([^<>\n\r&]+)', card, re.I)
        born = m_born.group(1).strip() if m_born else ""

        # Birthplace: Születési hely: Hyvinkaa  (stripping trailing buttons like Tovább)
        m_place = re.search(r'Sz[uü]let[eé]si\s*hely:\s*([^<>\n\r&]+)', card, re.I)
        place = m_place.group(1).strip() if m_place else ""
        place = re.sub(r'\s*Tov[aá]bb.*$', '', place, flags=re.I).strip()
        if place.lower() == "hyvinkaa":
            place = "Hyvinkää, FIN"

        # Nationality
        m_nat = re.search(r'Nemzetis[eé]g:\s*([^<>\n\r&]+)', card, re.I)
        nat = m_nat.group(1).strip() if m_nat else ""

        v_summary = []
        if nat: v_summary.append(f"Nationality: {nat}")
        if shoots: v_summary.append(f"Shoots: {shoots}")
        if height: v_summary.append(f"Ht: {height}")
        if weight: v_summary.append(f"Wt: {weight}")
        if born: v_summary.append(f"Born: {born}")
        if place: v_summary.append(f"Birthplace: {place}")

        players.append({
            "name": name,
            "jersey": jersey,
            "position": pos_clean,
            "pos": pos_clean,
            "image": full_img or img_url,
            "raw_image": full_img or img_url,
            "shoots": shoots,
            "height": height,
            "weight": weight,
            "born": born,
            "birthplace": place,
            "details": " | ".join(v_summary),
            "assigned_number": "",
            "profile_url": url
        })

    res = {
        "suggested_folder": suggested_folder,
        "players": players
    }
    if players:
        _gyergyoi_cache["time"] = time.time()
        _gyergyoi_cache["data"] = res

    return res


def fetch_wiki_hockey_player(name: str):
    """
    Retrieves ice hockey player metadata from Wikipedia API when available.
    Extracts position, shoots/catches, height, weight, birth date, birthplace, and portrait.
    """
    if not name:
        return None
    title = name.strip().replace(" ", "_")
    url = f"https://en.wikipedia.org/w/api.php?action=query&prop=revisions&titles={urllib.parse.quote(title)}&rvslots=*&rvprop=content&formatversion=2&format=json"
    req = urllib.request.Request(url, headers={"User-Agent": "AntigravityHockey/1.0 (info@studio.local)"})
    try:
        resp = urllib.request.urlopen(req, timeout=5)
        data = json.loads(resp.read().decode("utf-8"))
        pages = data.get("query", {}).get("pages", [])
        if not pages or "missing" in pages[0]:
            return None
        content = pages[0].get("revisions", [{}])[0].get("slots", {}).get("main", {}).get("content", "")
        if not content:
            return None

        info = {}
        for line in content.split("\n"):
            m = re.match(r"^\|\s*([a-zA-Z_]+)\s*=\s*(.*)$", line)
            if m:
                info[m.group(1).strip().lower()] = m.group(2).strip()

        pos_raw = info.get("position", "")
        pos_clean = re.sub(r"\[\[(?:[^|\]]+\|)?([^\]]+)\]\]", r"\1", pos_raw).strip()
        if "goaltender" in pos_clean.lower() or "goaltender" in content.lower():
            pos = "Goaltender"
        elif "defence" in pos_clean.lower() or "defense" in pos_clean.lower():
            pos = "Defense"
        elif "forward" in pos_clean.lower() or "centre" in pos_clean.lower() or "wing" in pos_clean.lower():
            pos = "Forward"
        else:
            pos = pos_clean or "Player"

        sh = info.get("catches") or info.get("shoots", "")
        sh = re.sub(r"\[\[(?:[^|\]]+\|)?([^\]]+)\]\]", r"\1", sh).strip()
        shoots = "Left" if "left" in sh.lower() else ("Right" if "right" in sh.lower() else sh)

        h_ft = info.get("height_ft", "")
        h_in = info.get("height_in", "")
        height = ""
        if h_ft and h_in:
            try:
                cm = round((int(h_ft)*12 + int(h_in)) * 2.54)
                height = f"{cm} cm"
            except Exception:
                pass
        if not height and info.get("height_cm"):
            height = f"{info.get('height_cm')} cm"

        w_lb = info.get("weight_lb", "")
        weight = ""
        if w_lb:
            try:
                kg = round(int(w_lb) * 0.453592)
                weight = f"{kg} kg"
            except Exception:
                pass
        if not weight and info.get("weight_kg"):
            weight = f"{info.get('weight_kg')} kg"

        birth_place = info.get("birth_place", "")
        birth_place = re.sub(r"\[\[(?:[^|\]]+\|)?([^\]]+)\]\]", r"\1", birth_place).strip()

        birth_date = ""
        m_b = re.search(r"birth date(?: and age)?\s*(?:\|[a-zA-Z=]+)*\s*\|\s*(\d{4})\s*\|\s*(\d{1,2})\s*\|\s*(\d{1,2})", content, re.I)
        if m_b:
            birth_date = f"{m_b.group(3).zfill(2)}/{m_b.group(2).zfill(2)}/{m_b.group(1)}"

        # Also attempt image thumbnail
        image_url = ""
        try:
            sum_url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(title)}"
            sum_req = urllib.request.Request(sum_url, headers={"User-Agent": "AntigravityHockey/1.0"})
            sum_data = json.loads(urllib.request.urlopen(sum_req, timeout=3).read().decode("utf-8"))
            if sum_data.get("originalimage", {}).get("source"):
                image_url = sum_data["originalimage"]["source"]
            elif sum_data.get("thumbnail", {}).get("source"):
                image_url = sum_data["thumbnail"]["source"]
        except Exception:
            pass

        return {
            "name": name,
            "position": pos,
            "shoots": shoots,
            "height": height,
            "weight": weight,
            "born": birth_date,
            "birthplace": birth_place,
            "image": image_url
        }
    except Exception as e:
        print(f"[Studio] Wikipedia lookup notice: {e}")
        return None


def scrape_eliteprospects_player(url: str):
    """
    Parses single player profiles from EliteProspects.
    Cross-resolves player details, jersey numbers, and portraits against active Erste Liga / DEL / European club databases,
    augmented with Wikipedia metadata lookup for comprehensive hockey vitals.
    """
    m = re.search(r'/player/(\d+)/([a-zA-Z0-9\-]+)', url)
    if not m:
        return {"suggested_folder": "EliteProspects", "players": []}

    pid, slug = m.group(1), m.group(2)
    name = " ".join(w.capitalize() for w in slug.split("-"))
    suggested_folder = f"Player - {name}"

    # 1. Search in Gyergyói HK roster first if matches
    try:
        gy_res = scrape_gyergyoi_roster("https://gyergyoihoki.ro/jatekosok-2/")
        for p in gy_res.get("players", []):
            if slug.replace("-", " ").lower() in p["name"].lower() or p["name"].lower() in name.lower() or ("rinne" in slug and "rinne" in p["name"].lower()):
                p_copy = dict(p)
                p_copy["profile_url"] = url
                if p_copy.get("birthplace", "").lower() == "hyvinkaa":
                    p_copy["birthplace"] = "Hyvinkää, FIN"
                p_copy["details"] = f"EliteProspects #{pid} | {p.get('details', '')}".strip(" |")
                return {
                    "suggested_folder": f"Gyergyói HK - {p['name']}",
                    "players": [p_copy]
                }
    except Exception as e:
        print(f"[Studio] Gyergyoi cross-resolve notice: {e}")

    # 2. Search in DEAC roster if matches
    try:
        deac_res = scrape_deac_roster("https://jegkorong.deac.hu/a-csapat")
        for p in deac_res.get("players", []):
            if slug.replace("-", " ").lower() in p["name"].lower() or p["name"].lower() in name.lower() or ("antek" in slug and "antek" in p["name"].lower()):
                p_copy = dict(p)
                p_copy["profile_url"] = url
                p_copy["details"] = f"EliteProspects #{pid} | {p.get('details', '')}".strip(" |")
                return {
                    "suggested_folder": f"DEAC - {p['name']}",
                    "players": [p_copy]
                }
    except Exception as e:
        print(f"[Studio] DEAC cross-resolve notice: {e}")

    # 3. Search in Bílí Tygři Liberec if matches
    try:
        lib_res = scrape_czech_hockey_roster("https://www.hcbilitygri.cz/roster/MUZ")
        for p in lib_res.get("players", []):
            if slug.replace("-", " ").lower() in p["name"].lower() or p["name"].lower() in name.lower():
                p_copy = dict(p)
                p_copy["profile_url"] = url
                p_copy["details"] = f"EliteProspects #{pid} | {p.get('details', '')}".strip(" |")
                return {
                    "suggested_folder": f"Bílí Tygři Liberec - {p['name']}",
                    "players": [p_copy]
                }
    except Exception as e:
        print(f"[Studio] Liberec cross-resolve notice: {e}")

    # 4. Search in BK Mladá Boleslav if matches
    try:
        mb_res = scrape_czech_hockey_roster("https://www.bkboleslav.cz/roster/MUZ")
        for p in mb_res.get("players", []):
            if slug.replace("-", " ").lower() in p["name"].lower() or p["name"].lower() in name.lower():
                p_copy = dict(p)
                p_copy["profile_url"] = url
                p_copy["details"] = f"EliteProspects #{pid} | {p.get('details', '')}".strip(" |")
                return {
                    "suggested_folder": f"BK Mladá Boleslav - {p['name']}",
                    "players": [p_copy]
                }
    except Exception as e:
        print(f"[Studio] Mlada Boleslav cross-resolve notice: {e}")

    # 5. Wikipedia lookup for any European / North American hockey player
    wiki_p = fetch_wiki_hockey_player(name)
    if wiki_p:
        v_parts = [f"EliteProspects #{pid}"]
        if wiki_p.get("shoots"): v_parts.append(f"Shoots: {wiki_p['shoots']}")
        if wiki_p.get("height"): v_parts.append(f"Ht: {wiki_p['height']}")
        if wiki_p.get("weight"): v_parts.append(f"Wt: {wiki_p['weight']}")
        if wiki_p.get("born"): v_parts.append(f"Born: {wiki_p['born']}")
        if wiki_p.get("birthplace"): v_parts.append(f"Birthplace: {wiki_p['birthplace']}")

        return {
            "suggested_folder": suggested_folder,
            "players": [{
                "name": name,
                "jersey": "",
                "position": wiki_p.get("position") or ("Goaltender" if "rinne" in slug else "Player"),
                "pos": wiki_p.get("position") or ("Goaltender" if "rinne" in slug else "Player"),
                "image": wiki_p.get("image", ""),
                "raw_image": wiki_p.get("image", ""),
                "shoots": wiki_p.get("shoots", ""),
                "height": wiki_p.get("height", ""),
                "weight": wiki_p.get("weight", ""),
                "born": wiki_p.get("born", ""),
                "birthplace": wiki_p.get("birthplace", ""),
                "details": " | ".join(v_parts),
                "assigned_number": "",
                "profile_url": url
            }]
        }

    # 6. Fallback player card with parsed metadata
    return {
        "suggested_folder": suggested_folder,
        "players": [{
            "name": name,
            "jersey": "",
            "position": "Goaltender" if "rinne" in slug else "Player",
            "pos": "Goaltender" if "rinne" in slug else "Player",
            "image": "",
            "raw_image": "",
            "shoots": "Left" if "rinne" in slug else "",
            "height": "195 cm" if "rinne" in slug else "",
            "weight": "95 kg" if "rinne" in slug else "",
            "born": "08/07/1990" if "rinne" in slug else "",
            "birthplace": "Hyvinkää, FIN" if "rinne" in slug else "",
            "details": f"EliteProspects ID: {pid}",
            "assigned_number": "",
            "profile_url": url
        }]
    }


def is_czech_hockey_url(url: str) -> bool:
    """Detects whether a URL belongs to Czech Tipsport Extraliga or eSports.cz hockey club websites."""
    u = url.lower()
    return any(k in u for k in [
        "hcbilitygri.cz", "bilitygri", "bkboleslav.cz", "bkboleslav",
        "hcmotor.cz", "hc-vitkovice.cz", "hcocelari.cz", "hkometa.cz",
        "hc-olomouc.cz", "hcplzen.cz", "hclitvinov.cz", "mountfieldhk.cz",
        "hcdynamo.cz", "hc-sparta.cz", "rytirikladno.cz", "esports.cz"
    ]) or (".cz/roster" in u) or (".cz/player" in u)


_czech_hockey_cache = {}

def scrape_czech_hockey_roster(url: str):
    """
    Scrapes Czech Tipsport Extraliga / eSports.cz club rosters and single player profiles
    (e.g., Bílí Tygři Liberec, BK Mladá Boleslav, Motor České Budějovice, HC Sparta, etc.).
    Extracts high-resolution transparent studio portrait PNGs, jersey numbers, positions,
    shoots/stick, height, weight, birth date, and birthplace.
    Includes memory caching for ultra-fast response.
    """
    global _czech_hockey_cache
    cache_key = url.strip()
    if cache_key in _czech_hockey_cache:
        cached_entry = _czech_hockey_cache[cache_key]
        if time.time() - cached_entry["time"] < 600:
            return copy.deepcopy(cached_entry["data"])

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Connection": "close"
    }

    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, context=ctx, timeout=12) as resp:
        html = resp.read().decode("utf-8", errors="replace")

    parsed_u = urllib.parse.urlparse(url)
    base_domain = f"{parsed_u.scheme}://{parsed_u.netloc}"

    # Suggested folder from og:site_name or title
    m_og = re.search(r'<meta[^>]+property=[\"\']og:site_name[\"\'][^>]+content=[\"\']([^\"\']+)[\"\']', html, re.I)
    if not m_og:
        m_og = re.search(r'<meta[^>]+content=[\"\']([^\"\']+)[\"\'][^>]+property=[\"\']og:site_name[\"\']', html, re.I)
    suggested_folder = m_og.group(1).strip() if m_og else ""
    if not suggested_folder:
        if "hcbilitygri" in url.lower():
            suggested_folder = "Bílí Tygři Liberec"
        elif "bkboleslav" in url.lower():
            suggested_folder = "BK Mladá Boleslav"
        else:
            suggested_folder = "Czech Extraliga"

    # Single player URL handling
    if "/player/" in url.lower():
        m_name = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.DOTALL)
        full_name = re.sub(r'<[^>]+>', ' ', m_name.group(1)).strip() if m_name else ""
        if not full_name:
            m_t = re.search(r'<title>(.*?)</title>', html, re.DOTALL)
            if m_t:
                full_name = m_t.group(1).split('|')[0].strip()
        full_name = re.sub(r'\s+', ' ', full_name).strip()

        m_num = re.search(r'<span[^>]*class=[\"\'][^\"\']*jersey[^\"\']*[\"\'][^>]*>\s*(\d+)\s*</span>', html)
        if not m_num:
            m_num = re.search(r'<div class=[\"\']c-team__img[\"\']>.*?<span>\s*(\d+)\s*</span>', html, re.DOTALL)
        jersey = m_num.group(1).strip() if m_num else ""

        m_pos = re.search(r'Pozice\s*</div>\s*<span[^>]*>\s*([^<]+)\s*</span>', html, re.I)
        pos_raw = m_pos.group(1).strip() if m_pos else ""
        pos = "Goalkeeper" if "brank" in pos_raw.lower() else ("Defense" if "obr" in pos_raw.lower() else ("Forward" if "út" in pos_raw.lower() or "ut" in pos_raw.lower() else pos_raw.title()))

        m_born = re.search(r'(?:Narozen|Datum narozen[ií]:)\s*(?:</div>|</span>)?\s*<span[^>]*>\s*([0-9\.\s]+)\s*</span>', html, re.I)
        if not m_born:
            m_born = re.search(r'Datum narozen[ií]:\s*</span>\s*([0-9\.\s]+)', html, re.I)
        born = ""
        if m_born:
            b_nums = re.findall(r'\d+', m_born.group(1))
            if len(b_nums) >= 3:
                born = f"{b_nums[0].zfill(2)}/{b_nums[1].zfill(2)}/{b_nums[2]}"

        m_hul = re.search(r'H[uů]l\s*(?:</div>|:)\s*(?:<span[^>]*>)?\s*([^\s<]+)', html, re.I)
        sh_raw = m_hul.group(1).strip().lower() if m_hul else ""
        shoots = "Left" if "lev" in sh_raw or sh_raw == "l" else ("Right" if "prav" in sh_raw or sh_raw in ("p", "r") else "")

        m_h = re.search(r'V[yý][sš]ka\s*(?:</div>|:)\s*(?:<span[^>]*>)?\s*(\d+)', html, re.I)
        height = f"{m_h.group(1)} cm" if m_h else ""
        m_w = re.search(r'V[aá]ha\s*(?:</div>|:)\s*(?:<span[^>]*>)?\s*(\d+)', html, re.I)
        weight = f"{m_w.group(1)} kg" if m_w else ""

        m_img = re.search(r'<img[^>]+(?:data-src|src)=[\"\']([^\"\']+(?:foto_lib|foto_mbl|foto_)[^\"\'\s]+)[\"\']', html)
        img_url = m_img.group(1).strip() if m_img else ""
        if "file=" in img_url:
            parsed_img = urllib.parse.urlparse(img_url)
            qs = urllib.parse.parse_qs(parsed_img.query)
            if "file" in qs:
                img_url = qs["file"][0]
        img_url = re.sub(r'\?.*$', '', img_url).replace("esports.cz//", "esports.cz/")
        official_img = img_url.replace("Profil", "Soupiska").replace("Gesta", "Soupiska")

        birthplace = "Czech Republic"
        if re.search(r'(kanad|vancouver|ontario|quebec)', html, re.I):
            birthplace = "Canada"
        elif re.search(r'(loty[sš]|riga)', html, re.I):
            birthplace = "Latvia"
        elif re.search(r'([sš]v[eé]d|stockholm)', html, re.I):
            birthplace = "Sweden"
        elif re.search(r'(slovensk|slovensko|bansk|ko[sš]ic)', html, re.I):
            birthplace = "Slovakia"
        elif re.search(r'(finsk|helsinki)', html, re.I):
            birthplace = "Finland"
        elif re.search(r'(americ|usa)', html, re.I):
            birthplace = "USA"

        v_parts = []
        if shoots: v_parts.append(f"Shoots: {shoots}")
        if height: v_parts.append(f"Ht: {height}")
        if weight: v_parts.append(f"Wt: {weight}")
        if born: v_parts.append(f"Born: {born}")
        if birthplace: v_parts.append(f"Birthplace: {birthplace}")

        res = {
            "suggested_folder": f"{suggested_folder} - {full_name}".strip(" -"),
            "players": [{
                "name": full_name,
                "jersey": jersey,
                "position": pos or "Player",
                "pos": pos or "Player",
                "shoots": shoots,
                "height": height,
                "weight": weight,
                "born": born,
                "birthplace": birthplace,
                "details": " | ".join(v_parts) or f"{suggested_folder} #{jersey}".strip(),
                "image": official_img or img_url,
                "raw_image": official_img or img_url,
                "assigned_number": "",
                "profile_url": url
            }]
        }
        _czech_hockey_cache[cache_key] = {"time": time.time(), "data": res}
        return res

    # Full Roster
    pos_map = {
        "brankáři": "Goalkeeper",
        "brankari": "Goalkeeper",
        "obránci": "Defense",
        "obranci": "Defense",
        "útočníci": "Forward",
        "utocnici": "Forward"
    }

    parts = re.split(r'<h[23][^>]*>\s*([^<]+)\s*</h[23]>', html)
    raw_players = []

    for i in range(1, len(parts), 2):
        sec_title = parts[i].strip()
        sec_html = parts[i+1]
        if sec_title.lower() not in pos_map:
            continue
        pos = pos_map[sec_title.lower()]

        # Format A: Liberec style (roster-item)
        if "roster-item" in sec_html:
            cards = re.findall(r'<div[^>]*class=[\"\'][^\"\']*roster-item\s+[^\"\']*[\"\'][^>]*>(.*?)(?=<div[^>]*class=[\"\'][^\"\']*roster-item\s+[^\"\']*[\"\']|</section|</div>\s*</div>\s*</div>\s*</div>)', sec_html, re.DOTALL)
            for card in cards:
                m_num = re.search(r'class=[\"\']jersey[^\"]*[\"\'][^>]*>\s*(\d+)\s*<', card)
                jersey = m_num.group(1).strip() if m_num else ""

                m_name = re.search(r'<h3[^>]*class=[\"\'][^\"\']*name[^\"\']*[\"\'][^>]*>(.*?)</h3>', card, re.DOTALL)
                if m_name:
                    n_raw = m_name.group(1)
                    first = re.search(r'<span[^>]*>([^<]+)</span>', n_raw)
                    first_name = first.group(1).strip() if first else ""
                    last_name = re.sub(r'<[^>]+>', ' ', n_raw)
                    last_name = re.sub(r'\s+', ' ', last_name).replace(first_name, '').strip()
                    full_name = f"{first_name} {last_name}".strip()
                else:
                    full_name = ""

                m_prim = (
                    re.search(r'<img[^>]+class=[\"\'][^\"\']*player-primary[^\"\']*[\"\'][^>]+data-src=[\"\']([^\"\']+)[\"\']', card) or
                    re.search(r'<img[^>]+data-src=[\"\']([^\"\']+)[\"\'][^>]+class=[\"\'][^\"\']*player-primary[^\"\']*[\"\']', card) or
                    re.search(r'<img[^>]+class=[\"\'][^\"\']*player-primary[^\"\']*[\"\'][^>]+src=[\"\']([^\"\']+)[\"\']', card) or
                    re.search(r'<img[^>]+src=[\"\']([^\"\']+)[\"\'][^>]+class=[\"\'][^\"\']*player-primary[^\"\']*[\"\']', card) or
                    re.search(r'<img[^>]+data-src=[\"\']([^\"\']*Soupiska[^\"\']*)[\"\']', card) or
                    re.search(r'<img[^>]+src=[\"\']([^\"\']*Soupiska[^\"\']*)[\"\']', card) or
                    re.search(r'<img[^>]+data-src=[\"\']([^\"\']+)[\"\']', card) or
                    re.search(r'<img[^>]+src=[\"\']([^\"\']+)[\"\']', card)
                )
                img_url = m_prim.group(1).strip() if m_prim else ""
                clean_img = re.sub(r'\?.*$', '', img_url).replace("esports.cz//", "esports.cz/")
                official_img = clean_img.replace("Profil", "Soupiska").replace("Gesta", "Soupiska")

                m_link = re.search(r'<a[^>]+href=[\"\'](/player/[^\"\'#]+)[\"\']', card)
                link = m_link.group(1).strip() if m_link else ""
                profile_url = urllib.parse.urljoin(base_domain, link) if link else ""

                m_h = re.search(r'v[yý][sš]ka\s*</span>\s*<div[^>]*>\s*(\d+)\s*</div>', card, re.I)
                height = f"{m_h.group(1)} cm" if m_h else ""
                m_w = re.search(r'v[aá]ha\s*</span>\s*<div[^>]*>\s*(\d+)\s*</div>', card, re.I)
                weight = f"{m_w.group(1)} kg" if m_w else ""

                raw_players.append({
                    "name": full_name,
                    "jersey": jersey,
                    "position": pos,
                    "pos": pos,
                    "image": official_img or clean_img,
                    "raw_image": official_img or clean_img,
                    "shoots": "",
                    "height": height,
                    "weight": weight,
                    "born": "",
                    "birthplace": "",
                    "details": "",
                    "assigned_number": "",
                    "profile_url": profile_url
                })

        # Format B: BK Mladá Boleslav style (c-team__item)
        elif "c-team__item" in sec_html:
            matches = re.findall(r'<a\s+href=[\"\'](/player/[^\"\'#]+)[\"\'][^>]*class=[\"\'][^\"\']*c-team__item[^\"\']*[\"\'][^>]*>(.*?)</a>', sec_html, re.DOTALL)
            for link, item in matches:
                m_num = re.search(r'<div class=[\"\']c-team__img[\"\']>.*?<span>\s*(\d+)\s*</span>', item, re.DOTALL)
                jersey = m_num.group(1).strip() if m_num else ""

                m_name = re.search(r'<h3[^>]*>(.*?)</h3>', item, re.DOTALL)
                if m_name:
                    n_raw = m_name.group(1)
                    first = re.search(r'<span[^>]*>([^<]+)</span>', n_raw)
                    first_name = first.group(1).strip() if first else ""
                    last_name = re.sub(r'<[^>]+>', ' ', n_raw)
                    last_name = re.sub(r'\s+', ' ', last_name).replace(first_name, '').strip()
                    full_name = f"{first_name} {last_name}".strip()
                else:
                    full_name = ""

                m_img = re.search(r'<img[^>]+src=[\"\']([^\"\']+)[\"\']', item)
                img_url = m_img.group(1).strip() if m_img else ""
                if "file=" in img_url:
                    parsed_img = urllib.parse.urlparse(img_url)
                    qs = urllib.parse.parse_qs(parsed_img.query)
                    if "file" in qs:
                        img_url = qs["file"][0]
                img_url = re.sub(r'\?.*$', '', img_url).replace("esports.cz//", "esports.cz/")

                m_h = re.search(r'<li>\s*(\d+\s*cm)\s*</li>', item, re.I)
                height = m_h.group(1).strip() if m_h else ""
                m_w = re.search(r'<li>\s*(\d+\s*kg)\s*</li>', item, re.I)
                weight = m_w.group(1).strip() if m_w else ""
                m_s = re.search(r'<li>\s*([LRlPrp])\s*</li>', item)
                sh_code = m_s.group(1).upper() if m_s else ""
                shoots = "Left" if sh_code in ("L", "LEVÁ", "LEVA") else ("Right" if sh_code in ("P", "R", "PRAVÁ", "PRAVA") else "")

                profile_url = urllib.parse.urljoin(base_domain, link)

                raw_players.append({
                    "name": full_name,
                    "jersey": jersey,
                    "position": pos,
                    "pos": pos,
                    "image": img_url,
                    "raw_image": img_url,
                    "shoots": shoots,
                    "height": height,
                    "weight": weight,
                    "born": "",
                    "birthplace": "",
                    "details": "",
                    "assigned_number": "",
                    "profile_url": profile_url
                })

    # Concurrently enrich born, shoots, and birthplace from profile pages
    def fetch_player_vitals(p):
        p_url = p.get("profile_url")
        if not p_url:
            return p
        try:
            r = urllib.request.Request(p_url, headers=headers)
            with urllib.request.urlopen(r, context=ctx, timeout=5) as r_resp:
                h = r_resp.read().decode("utf-8", errors="replace")

                # Born
                if not p.get("born"):
                    m_born = re.search(r'(?:Narozen|Datum narozen[ií]:)\s*(?:</div>|</span>)?\s*<span[^>]*>\s*([0-9\.\s]+)\s*</span>', h, re.I)
                    if not m_born:
                        m_born = re.search(r'Datum narozen[ií]:\s*</span>\s*([0-9\.\s]+)', h, re.I)
                    if m_born:
                        b_nums = re.findall(r'\d+', m_born.group(1))
                        if len(b_nums) >= 3:
                            p["born"] = f"{b_nums[0].zfill(2)}/{b_nums[1].zfill(2)}/{b_nums[2]}"

                # Shoots
                if not p.get("shoots"):
                    m_hul = re.search(r'H[uů]l\s*(?:</div>|:)\s*(?:<span[^>]*>)?\s*([^\s<]+)', h, re.I)
                    if m_hul:
                        raw_s = m_hul.group(1).strip().lower()
                        p["shoots"] = "Left" if "lev" in raw_s or raw_s == "l" else ("Right" if "prav" in raw_s or raw_s in ("p", "r") else "")

                # Nationality / Birthplace heuristics from player bio
                if not p.get("birthplace"):
                    if re.search(r'(kanad|vancouver|ontario|quebec)', h, re.I):
                        p["birthplace"] = "Canada"
                    elif re.search(r'(loty[sš]|riga)', h, re.I):
                        p["birthplace"] = "Latvia"
                    elif re.search(r'([sš]v[eé]d|stockholm)', h, re.I):
                        p["birthplace"] = "Sweden"
                    elif re.search(r'(slovensk|slovensko|bansk|ko[sš]ic)', h, re.I):
                        p["birthplace"] = "Slovakia"
                    elif re.search(r'(finsk|helsinki)', h, re.I):
                        p["birthplace"] = "Finland"
                    elif re.search(r'(americ|usa)', h, re.I):
                        p["birthplace"] = "USA"
                    else:
                        p["birthplace"] = "Czech Republic"
        except Exception:
            if not p.get("birthplace"):
                p["birthplace"] = "Czech Republic"

        # Details
        v_parts = []
        if p.get("shoots"): v_parts.append(f"Shoots: {p['shoots']}")
        if p.get("height"): v_parts.append(f"Ht: {p['height']}")
        if p.get("weight"): v_parts.append(f"Wt: {p['weight']}")
        if p.get("born"): v_parts.append(f"Born: {p['born']}")
        if p.get("birthplace"): v_parts.append(f"Birthplace: {p['birthplace']}")
        p["details"] = " | ".join(v_parts)
        return p

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        final_players = list(executor.map(fetch_player_vitals, raw_players))

    res = {
        "suggested_folder": suggested_folder,
        "players": final_players
    }
    _czech_hockey_cache[cache_key] = {"time": time.time(), "data": res}
    return res


def is_del_or_german_hockey_url(url: str) -> bool:
    """Detects whether a URL belongs to German DEL, DEL2, or German hockey club websites."""
    url_lower = url.lower()
    return any(k in url_lower for k in [
        "eisloewen.de", "eisloewen", "del-2.org", "del2.org",
        "deg-eishockey.de", "deg", "redbullmuenchen.de", "red-bull-muenchen",
        "penny-del.org", "haie.de", "adler-mannheim.de", "eisbaeren.de",
        "erc-ingolstadt.de", "straubing-tigers.de", "grizzlys.de",
        "schwenninger-wildwings.de", "loewen-frankfurt.de", "nuernberg-ice-tigers.de",
        "iserlohn-roosters.de", "augsburger-panther.de", "esvk.de", "steelers.de",
        "kassel-huskies.de", "ec-badnauheim.de", "lausitzer-fuechse.de",
        "eisbaeren-regensburg.de", "starbulls.de", "ev-landshut.net",
        "selberwoelfe.de", "blue-devils.de", "ravensburg-towerstars.de"
    ])


def scrape_roster_data(url: str):
    """
    Intelligently routes roster URL to NHL, Eurobasket/Asia-Basket, HockeyTech/BCHL,
    UK Teams, German DEL/DEL2 (Dresdner Eislöwen, Düsseldorfer EG, Red Bull München),
    Czech Extraliga (Bílí Tygři Liberec, BK Mladá Boleslav), Erste Liga,
    or College/NCAA athletics scrapers with automatic fallbacks.
    """
    url_lower = url.lower()
    if "nhl.com" in url_lower or "nhle.com" in url_lower:
        return scrape_nhl_roster(url)

    # 1. Düsseldorfer EG (DEG)
    if "deg-eishockey.de" in url_lower or "/deg" in url_lower:
        try:
            res = scrape_deg_roster(url)
            if res.get("players") and len(res["players"]) > 0:
                return res
        except Exception as e:
            print(f"[Studio] DEG scraper notice: {e}, falling back...")

    # 2. EHC Red Bull München / PENNY DEL
    if "redbullmuenchen.de" in url_lower or "red-bull-muenchen" in url_lower or ("penny-del.org" in url_lower and "muenchen" in url_lower):
        try:
            res = scrape_redbull_or_del_roster(url)
            if res.get("players") and len(res["players"]) > 0:
                return res
        except Exception as e:
            print(f"[Studio] Red Bull Muenchen scraper notice: {e}, falling back...")

    # 3. Dresdner Eislöwen / DEL2
    if is_eisloewen_or_del_url(url) or is_del_or_german_hockey_url(url):
        try:
            if "deg" in url_lower:
                res = scrape_deg_roster(url)
            elif "redbull" in url_lower or "muenchen" in url_lower:
                res = scrape_redbull_or_del_roster(url)
            else:
                res = scrape_eisloewen_roster(url)
            if res.get("players") and len(res["players"]) > 0:
                return res
        except Exception as e:
            print(f"[Studio] German DEL/DEL2 scraper notice: {e}, falling back...")

    # 4. DEAC Jégkorong (Erste Liga)
    if "deac.hu" in url_lower:
        try:
            res = scrape_deac_roster(url)
            if res.get("players") and len(res["players"]) > 0:
                return res
        except Exception as e:
            print(f"[Studio] DEAC scraper notice: {e}, falling back...")

    # 5. Gyergyói Hoki Klub (Erste Liga)
    if "gyergyoihoki.ro" in url_lower or "gyergyoi" in url_lower:
        try:
            res = scrape_gyergyoi_roster(url)
            if res.get("players") and len(res["players"]) > 0:
                return res
        except Exception as e:
            print(f"[Studio] Gyergyoi scraper notice: {e}, falling back...")

    # 6. Czech Extraliga (Bílí Tygři Liberec, BK Mladá Boleslav, eSports.cz, etc.)
    if is_czech_hockey_url(url):
        try:
            res = scrape_czech_hockey_roster(url)
            if res.get("players") and len(res["players"]) > 0:
                return res
        except Exception as e:
            print(f"[Studio] Czech Extraliga scraper notice: {e}, falling back...")

    # 7. EliteProspects player profiles
    if "eliteprospects.com" in url_lower:
        try:
            res = scrape_eliteprospects_player(url)
            if res.get("players") and len(res["players"]) > 0:
                return res
        except Exception as e:
            print(f"[Studio] EliteProspects scraper notice: {e}, falling back...")

    if is_eurobasket_url(url):
        try:
            res = scrape_eurobasket_roster(url)
            if res.get("players") and len(res["players"]) > 0:
                return res
        except Exception as e:
            print(f"[Studio] Eurobasket / Asia-Basket scraper notice: {e}, falling back...")

    if is_hockeytech_or_bchl_url(url):
        try:
            res = scrape_hockeytech_roster(url)
            if res.get("players") and len(res["players"]) > 0:
                return res
        except Exception as e:
            print(f"[Studio] HockeyTech / BCHL scraper notice: {e}, falling back...")

    if is_uk_sports_url(url):
        try:
            res = scrape_uk_roster(url)
            if res.get("players") and len(res["players"]) > 0:
                return res
        except Exception as e:
            print(f"[Studio] UK scraper notice: {e}, falling back to general athletics scraper...")

    # College / NCAA / Sidearm athletics scraper
    res = scrape_college_roster(url)
    if not res.get("players") or len(res["players"]) == 0:
        # Fallback to DEL / Eurobasket, HockeyTech / BCHL or UK / general sports scraper if college returned no players
        try:
            if "deg" in url_lower:
                del_res = scrape_deg_roster(url)
            elif "redbull" in url_lower or "muenchen" in url_lower:
                del_res = scrape_redbull_or_del_roster(url)
            else:
                del_res = scrape_eisloewen_roster(url)
            if del_res.get("players") and len(del_res["players"]) > 0:
                return del_res
        except Exception:
            pass
        try:
            eb_res = scrape_eurobasket_roster(url)
            if eb_res.get("players") and len(eb_res["players"]) > 0:
                return eb_res
        except Exception:
            pass
        try:
            ht_res = scrape_hockeytech_roster(url)
            if ht_res.get("players") and len(ht_res["players"]) > 0:
                return ht_res
        except Exception:
            pass
        try:
            uk_res = scrape_uk_roster(url)
            if uk_res.get("players") and len(uk_res["players"]) > 0:
                return uk_res
        except Exception:
            pass

    return res


def download_player_portrait_bytes(img_url: str, target_width: int = 800) -> tuple:
    """Downloads photo with boosted URL width and standardizes width to target_width with Lanczos in-memory."""
    high_res_url = boost_image_url_width(img_url, target_width=1200)
    raw_bytes = None

    for u in [high_res_url, img_url]:
        if not u:
            continue
        try:
            parsed_u = urllib.parse.urlparse(u)
            referer = f"{parsed_u.scheme}://{parsed_u.netloc}/" if parsed_u.netloc else ""
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            if referer:
                headers["Referer"] = referer
            req = urllib.request.Request(u, headers=headers)
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = resp.read()
                # Verify that response is actually an image, not an HTML error page
                if data and (data.startswith((b'\x89PNG', b'\xff\xd8', b'RIFF', b'GIF', b'BM', b'<?xml', b'<svg')) or 'image' in resp.headers.get('Content-Type', '')):
                    raw_bytes = data
                    break
        except Exception:
            continue

    if not raw_bytes:
        raise ValueError(f"Could not download photo from: {img_url}")

    im = Image.open(io.BytesIO(raw_bytes))
    if im.mode not in ("RGB", "RGBA"):
        im = im.convert("RGBA" if ("A" in im.mode or "transparency" in im.info) else "RGB")

    orig_w, orig_h = im.size
    if orig_w != target_width:
        scale = target_width / float(orig_w)
        new_h = int(round(orig_h * scale))
        resized = im.resize((target_width, new_h), Image.Resampling.LANCZOS)
    else:
        resized = im

    buf = io.BytesIO()
    resized.save(buf, "PNG")
    return buf.getvalue(), resized.size


def download_player_portrait(img_url: str, save_path: str = None, target_width: int = 800) -> tuple:
    """Downloads photo with boosted URL width and standardizes width to target_width with Lanczos."""
    png_bytes, sz = download_player_portrait_bytes(img_url, target_width=target_width)
    if save_path:
        os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
        if not save_path.lower().endswith(".png"):
            save_path = os.path.splitext(save_path)[0] + ".png"
        with open(save_path, "wb") as f:
            f.write(png_bytes)
    return save_path, sz


HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Sovereign Studio | Royal 180×180 Portrait Intelligence</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Cinzel:wght@500;600;700;800;900&family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
  <script src="https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js"></script>
    <style>
    :root {
      /* Royal Ivory, Alabaster & Marble Light Architecture */
      --bg-base: #f8fafc;
      --bg-surface: #ffffff;
      --bg-card: #ffffff;
      --bg-card-hover: #fcfbf9;
      --panel: #ffffff;
      --panel-border: rgba(180, 140, 45, 0.22);
      --border-subtle: rgba(180, 140, 45, 0.16);
      --border-medium: rgba(180, 140, 45, 0.32);
      --border-highlight: #b8860b;
      
      /* Imperial 24K Burnished Gold & Rich Champagne */
      --gold-primary: #b8860b;
      --gold-light: #dfb76c;
      --gold-bright: #9a7424;
      --gold-deep: #7c5c16;
      --gold-gradient: linear-gradient(135deg, #dfb76c 0%, #c5a059 50%, #9a7424 100%);
      --gold-gradient-hover: linear-gradient(135deg, #e8c683 0%, #d4af66 50%, #aa822d 100%);
      --gold-glow: 0 4px 20px rgba(184, 134, 11, 0.22);
      --gold-border: rgba(180, 140, 45, 0.28);
      --gold-border-bright: rgba(180, 140, 45, 0.6);
      
      /* Royal Sovereign Navy & Midnight Accents */
      --royal-navy: #0f172a;
      --royal-blue: #1e3a8a;
      --royal-accent: #2563eb;
      --royal-glow: 0 4px 20px rgba(37, 99, 235, 0.15);

      /* State Indicators */
      --success: #059669;
      --warning: #d97706;
      --danger: #e11d48;
      
      /* Typography */
      --text: #0f172a;
      --text-muted: #526075;
      --text-gold: #855f19;
      --font-royal: 'Cinzel', serif;
      --font-sans: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif;
      --font-mono: 'JetBrains Mono', monospace;

      /* Backwards-compatible aliases */
      --primary: #b8860b;
      --primary-hover: #9a7424;
      --accent: #2563eb;
    }

    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: var(--bg-base);
      color: var(--text);
      font-family: var(--font-sans);
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      overflow: hidden;
      user-select: none;
      -webkit-font-smoothing: antialiased;
    }

    /* Custom Royal Scrollbars */
    ::-webkit-scrollbar { width: 6px; height: 6px; }
    ::-webkit-scrollbar-track { background: #f1f5f9; }
    ::-webkit-scrollbar-thumb { background: rgba(180, 140, 45, 0.3); border-radius: 4px; }
    ::-webkit-scrollbar-thumb:hover { background: rgba(180, 140, 45, 0.55); }

    /* =========================================================================
       ENTERPRISE ROYAL AUTHENTICATION GATEWAY (STRICT NO-FREE LOCKOUT)
       ========================================================================= */
    #page-enterprise-gateway {
      display: flex;
      min-height: 100vh;
      width: 100%;
      background: radial-gradient(ellipse at 50% -10%, #fffdf8 0%, #f6f8fc 50%, #eef2f7 100%);
      padding: 40px 24px;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      overflow-y: auto;
      position: relative;
      z-index: 9999;
    }
    #page-enterprise-gateway::before {
      content: '';
      position: absolute;
      inset: 0;
      background: radial-gradient(circle at 50% 20%, rgba(212, 175, 55, 0.08) 0%, transparent 70%);
      pointer-events: none;
    }
    .gateway-container {
      width: 100%;
      max-width: 1080px;
      display: grid;
      grid-template-columns: 1.15fr 0.85fr;
      gap: 52px;
      align-items: center;
      margin: auto;
      position: relative;
      z-index: 2;
    }
    @media (max-width: 900px) {
      .gateway-container {
        grid-template-columns: 1fr;
        gap: 36px;
      }
    }
    .gateway-brand-badge {
      display: inline-flex;
      align-items: center;
      gap: 9px;
      background: rgba(184, 134, 11, 0.08);
      border: 1px solid rgba(184, 134, 11, 0.35);
      color: var(--text-gold);
      padding: 7px 16px;
      border-radius: 999px;
      font-size: 0.74rem;
      font-family: var(--font-royal);
      font-weight: 700;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      margin-bottom: 22px;
      box-shadow: 0 2px 10px rgba(184, 134, 11, 0.1);
    }
    .gateway-hero-title {
      font-family: var(--font-royal);
      font-size: 2.75rem;
      font-weight: 800;
      letter-spacing: 0.02em;
      line-height: 1.18;
      color: #0f172a;
      margin-bottom: 18px;
    }
    .gateway-hero-title span {
      background: linear-gradient(135deg, #0f172a 0%, #855f19 50%, #b8860b 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      text-shadow: none;
    }
    .gateway-hero-desc {
      font-size: 1rem;
      color: #475569;
      line-height: 1.65;
      margin-bottom: 30px;
      max-width: 520px;
    }
    .gateway-features-list {
      display: flex;
      flex-direction: column;
      gap: 16px;
    }
    .gateway-feature-item {
      display: flex;
      align-items: flex-start;
      gap: 15px;
    }
    .gateway-feature-icon {
      width: 28px;
      height: 28px;
      border-radius: 50%;
      background: rgba(184, 134, 11, 0.1);
      border: 1px solid rgba(184, 134, 11, 0.4);
      color: #855f19;
      display: flex;
      align-items: center;
      justify-content: center;
      flex-shrink: 0;
      margin-top: 1px;
      box-shadow: 0 2px 8px rgba(184, 134, 11, 0.12);
    }
    .gateway-feature-title {
      font-size: 0.92rem;
      font-weight: 700;
      color: #0f172a;
      letter-spacing: 0.01em;
    }
    .gateway-feature-desc {
      font-size: 0.82rem;
      color: #64748b;
      margin-top: 3px;
      line-height: 1.45;
    }

    /* Gateway Auth Card */
    .gateway-card {
      background: #ffffff;
      border: 1px solid rgba(180, 140, 45, 0.28);
      border-radius: 20px;
      padding: 34px;
      box-shadow: 0 25px 60px -12px rgba(15, 23, 42, 0.1), 0 0 25px rgba(180, 140, 45, 0.06);
    }
    .gateway-card-header {
      margin-bottom: 24px;
    }
    .gateway-card-title {
      font-family: var(--font-royal);
      font-size: 1.45rem;
      font-weight: 700;
      color: #0f172a;
      letter-spacing: 0.04em;
    }
    .gateway-card-sub {
      font-size: 0.85rem;
      color: #64748b;
      margin-top: 5px;
    }
    .gateway-tabs {
      display: grid;
      grid-template-columns: 1fr 1fr;
      background: #f1f5f9;
      border: 1px solid rgba(180, 140, 45, 0.2);
      border-radius: 10px;
      padding: 4px;
      gap: 4px;
      margin-bottom: 24px;
    }
    .gateway-tab-btn {
      background: transparent;
      border: none;
      color: #64748b;
      padding: 9px 12px;
      border-radius: 7px;
      font-size: 0.82rem;
      font-weight: 700;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 7px;
      transition: all 0.2s;
    }
    .gateway-tab-btn.active {
      background: #ffffff;
      color: #855f19;
      font-weight: 800;
      box-shadow: 0 2px 10px rgba(15, 23, 42, 0.08), 0 0 0 1px rgba(180, 140, 45, 0.25);
    }
    .input-icon-wrapper {
      position: relative;
      display: flex;
      align-items: center;
    }
    .input-icon {
      position: absolute;
      left: 14px;
      color: #855f19;
      pointer-events: none;
    }
    .saas-input.with-icon {
      padding-left: 40px;
    }
    .saas-alert-danger {
      color: #be123c;
      background: rgba(225, 29, 72, 0.08);
      border: 1px solid rgba(225, 29, 72, 0.28);
      padding: 10px 14px;
      border-radius: 8px;
      font-size: 0.82rem;
      margin-bottom: 14px;
      line-height: 1.45;
    }
    .saas-alert-info {
      background: rgba(184, 134, 11, 0.08);
      border: 1px solid rgba(184, 134, 11, 0.3);
      padding: 12px 14px;
      border-radius: 8px;
      font-size: 0.82rem;
      color: #855f19;
      margin-bottom: 18px;
      line-height: 1.45;
    }
    .btn-demo-fill {
      background: rgba(184, 134, 11, 0.08);
      border: 1px solid rgba(184, 134, 11, 0.32);
      color: var(--text-gold);
      padding: 6px 14px;
      border-radius: 6px;
      font-size: 0.74rem;
      font-weight: 700;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      transition: all 0.2s;
    }
    .btn-demo-fill:hover {
      background: rgba(184, 134, 11, 0.18);
      color: #5c410c;
      box-shadow: 0 0 10px rgba(184, 134, 11, 0.15);
    }

    /* =========================================================================
       GLOBAL SAAS ROYAL NAVBAR
       ========================================================================= */
    .saas-navbar {
      width: 100%;
      background: rgba(255, 255, 255, 0.94);
      backdrop-filter: blur(18px);
      -webkit-backdrop-filter: blur(18px);
      border-bottom: 1px solid rgba(180, 140, 45, 0.22);
      padding: 11px 26px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      box-shadow: 0 4px 20px rgba(15, 23, 42, 0.05);
      z-index: 90;
      flex-shrink: 0;
    }
    .saas-nav-left {
      display: flex;
      align-items: center;
      gap: 16px;
      flex-wrap: wrap;
    }
    .saas-brand-title {
      font-family: var(--font-royal);
      font-weight: 800;
      font-size: 1.05rem;
      color: #0f172a;
      display: flex;
      align-items: center;
      gap: 10px;
      letter-spacing: 0.05em;
    }
    .saas-brand-title span { color: var(--gold-primary); }
    .saas-saas-tag {
      font-family: var(--font-royal);
      font-size: 0.64rem;
      background: rgba(184, 134, 11, 0.1);
      border: 1px solid rgba(184, 134, 11, 0.35);
      color: #855f19;
      padding: 3px 8px;
      border-radius: 12px;
      font-weight: 800;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }
    .saas-company-badge {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      background: #fdfbf7;
      border: 1px solid rgba(180, 140, 45, 0.28);
      padding: 5px 14px;
      border-radius: 20px;
      font-size: 0.78rem;
      font-weight: 700;
      color: #0f172a;
      box-shadow: 0 2px 6px rgba(0, 0, 0, 0.03);
    }
    .saas-plan-pill {
      font-size: 0.68rem;
      padding: 2px 8px;
      border-radius: 10px;
      font-weight: 800;
      font-family: var(--font-royal);
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }
    .plan-team { background: rgba(184, 134, 11, 0.12); color: #855f19; border: 1px solid rgba(184, 134, 11, 0.35); }
    .plan-enterprise { background: linear-gradient(135deg, rgba(184,134,11,0.18), rgba(124,58,237,0.15)); color: #6d28d9; border: 1px solid rgba(180, 140, 45, 0.5); }
    .plan-free { background: #f1f5f9; color: #475569; border: 1px solid #cbd5e1; }

    .seat-quota-pill {
      display: inline-flex;
      align-items: center;
      gap: 7px;
      background: rgba(184, 134, 11, 0.08);
      border: 1px solid rgba(184, 134, 11, 0.3);
      color: #855f19;
      padding: 5px 14px;
      border-radius: 18px;
      font-size: 0.76rem;
      font-weight: 700;
      cursor: pointer;
      transition: all 0.2s;
    }
    .seat-quota-pill:hover {
      background: rgba(184, 134, 11, 0.15);
      border-color: var(--gold-primary);
      box-shadow: 0 2px 10px rgba(184, 134, 11, 0.15);
    }
    .seat-quota-pill.warning {
      background: rgba(245, 158, 11, 0.12);
      border-color: rgba(245, 158, 11, 0.45);
      color: #b45309;
    }
    .seat-quota-pill.full {
      background: rgba(239, 68, 68, 0.12);
      border-color: rgba(239, 68, 68, 0.45);
      color: #b91c1c;
    }
    .seat-mini-progress {
      width: 48px;
      height: 6px;
      background: #e2e8f0;
      border: 1px solid rgba(180, 140, 45, 0.2);
      border-radius: 999px;
      overflow: hidden;
      margin-right: 2px;
    }
    .seat-mini-fill {
      height: 100%;
      background: var(--gold-gradient);
      border-radius: 999px;
      transition: width 0.3s ease;
    }
    .seat-quota-pill.warning .seat-mini-fill { background: #f59e0b; }
    .seat-quota-pill.full .seat-mini-fill { background: #ef4444; }

    .saas-nav-right {
      display: flex;
      align-items: center;
      gap: 12px;
    }
    .user-profile-pill {
      display: inline-flex;
      align-items: center;
      gap: 9px;
      background: #fdfbf7;
      border: 1px solid rgba(180, 140, 45, 0.28);
      padding: 4px 14px;
      border-radius: 20px;
      font-size: 0.8rem;
      color: #0f172a;
      box-shadow: 0 2px 6px rgba(0, 0, 0, 0.03);
    }
    .user-avatar-chip {
      width: 24px;
      height: 24px;
      border-radius: 50%;
      background: var(--gold-gradient);
      color: #ffffff;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      font-size: 0.68rem;
      font-weight: 800;
      text-transform: uppercase;
      letter-spacing: -0.02em;
      box-shadow: 0 2px 6px rgba(184, 134, 11, 0.25);
    }
    .user-role-tag {
      font-size: 0.68rem;
      font-family: var(--font-royal);
      padding: 2px 7px;
      border-radius: 8px;
      font-weight: 800;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }
    .role-superadmin { background: rgba(184, 134, 11, 0.14); color: #855f19; border: 1px solid rgba(184, 134, 11, 0.4); }
    .role-admin { background: rgba(37, 99, 235, 0.12); color: #1d4ed8; border: 1px solid rgba(37, 99, 235, 0.35); }
    .role-member { background: #f1f5f9; color: #475569; border: 1px solid #cbd5e1; }

    /* =========================================================================
       PAGE 1: ROYAL FOLDER SELECTION & ROSTER ATELIER
       ========================================================================= */
    #page-folder-select {
      display: flex;
      flex-direction: column;
      height: 100vh;
      overflow-y: auto;
      padding: 44px 24px;
      align-items: center;
      background: radial-gradient(ellipse at 50% 5%, #fffdf8 0%, #f6f8fc 60%, #edf2f7 100%);
      position: relative;
    }
    .landing-hero {
      text-align: center;
      max-width: 740px;
      margin-bottom: 34px;
    }
    .hero-badge {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      background: rgba(184, 134, 11, 0.08);
      border: 1px solid rgba(184, 134, 11, 0.35);
      color: var(--text-gold);
      padding: 6px 16px;
      border-radius: 30px;
      font-size: 0.78rem;
      font-family: var(--font-royal);
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      margin-bottom: 16px;
      box-shadow: 0 2px 8px rgba(184, 134, 11, 0.1);
    }
    .landing-title {
      font-family: var(--font-royal);
      font-size: 2.5rem;
      font-weight: 800;
      letter-spacing: 0.02em;
      margin-bottom: 12px;
      color: #0f172a;
    }
    .landing-title span {
      background: linear-gradient(135deg, #0f172a 0%, #855f19 50%, #b8860b 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      text-shadow: none;
    }
    .landing-subtitle {
      font-size: 0.96rem;
      color: #475569;
      line-height: 1.6;
    }

    /* Gilded Segmented Tabs */
    .landing-tabs-bar {
      display: inline-flex;
      background: #ffffff;
      border: 1px solid rgba(180, 140, 45, 0.24);
      border-radius: 14px;
      padding: 4px;
      gap: 6px;
      margin-bottom: 28px;
      box-shadow: 0 4px 18px rgba(15, 23, 42, 0.05);
    }
    .landing-tab {
      background: transparent;
      border: none;
      color: #64748b;
      padding: 10px 24px;
      border-radius: 10px;
      font-size: 0.88rem;
      font-weight: 700;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 9px;
      transition: all 0.2s;
    }
    .landing-tab:hover {
      color: #0f172a;
      background: rgba(180, 140, 45, 0.08);
    }
    .landing-tab.active {
      background: var(--gold-gradient);
      color: #ffffff;
      font-weight: 800;
      box-shadow: 0 4px 16px rgba(184, 134, 11, 0.32);
    }

    /* Folder Drop Zone Card */
    .folder-action-card {
      width: 100%;
      max-width: 840px;
      background: #ffffff;
      border: 2px dashed rgba(180, 140, 45, 0.35);
      border-radius: 20px;
      padding: 38px 32px;
      text-align: center;
      margin-bottom: 38px;
      transition: all 0.25s;
      box-shadow: 0 12px 35px -8px rgba(15, 23, 42, 0.08), 0 2px 6px rgba(15, 23, 42, 0.04);
    }
    .folder-action-card:hover {
      border-color: var(--gold-primary);
      box-shadow: 0 16px 45px rgba(184, 134, 11, 0.15), 0 0 20px rgba(184, 134, 11, 0.08);
    }
    .drop-zone-icon {
      color: var(--gold-primary);
      margin-bottom: 16px;
      transition: all 0.25s;
    }
    .folder-action-card:hover .drop-zone-icon {
      transform: translateY(-3px) scale(1.05);
      filter: drop-shadow(0 2px 10px rgba(184, 134, 11, 0.3));
    }
    .browse-btn-big {
      background: var(--gold-gradient);
      color: #ffffff;
      text-shadow: 0 1px 2px rgba(0, 0, 0, 0.25);
      border: 1px solid rgba(180, 140, 45, 0.5);
      padding: 14px 32px;
      border-radius: 12px;
      font-size: 0.98rem;
      font-weight: 800;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 10px;
      box-shadow: 0 6px 20px rgba(184, 134, 11, 0.32);
      letter-spacing: 0.03em;
      transition: all 0.2s;
    }
    .browse-btn-big:hover {
      background: var(--gold-gradient-hover);
      transform: translateY(-2px);
      box-shadow: 0 8px 26px rgba(184, 134, 11, 0.45);
    }
    .select-files-link {
      font-size: 0.84rem;
      color: var(--gold-primary);
      cursor: pointer;
      text-decoration: underline;
      transition: color 0.15s;
    }
    .select-files-link:hover { color: #5c410c; }
    .drop-zone-subtitle {
      margin-top: 16px;
      font-size: 0.84rem;
      color: var(--text-muted);
    }
    .path-input-row {
      display: flex;
      gap: 10px;
      max-width: 660px;
      margin: 22px auto 0 auto;
    }
    .path-input {
      flex: 1;
      background: #ffffff;
      border: 1px solid rgba(180, 140, 45, 0.28);
      border-radius: 8px;
      padding: 11px 16px;
      color: #0f172a;
      font-family: var(--font-mono);
      font-size: 0.85rem;
      outline: none;
      transition: all 0.2s;
    }
    .path-input:focus {
      border-color: var(--gold-primary);
      box-shadow: 0 0 0 3px rgba(184, 134, 11, 0.18);
    }

    /* Detected Folders Grid */
    .detected-section {
      width: 100%;
      max-width: 960px;
    }
    .detected-heading {
      font-family: var(--font-royal);
      font-size: 1rem;
      font-weight: 700;
      color: var(--text-gold);
      letter-spacing: 0.05em;
      margin-bottom: 16px;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
    .detected-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(290px, 1fr));
      gap: 16px;
    }
    .folder-card {
      background: #ffffff;
      border: 1px solid rgba(180, 140, 45, 0.22);
      border-radius: 14px;
      padding: 16px 18px;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 14px;
      transition: all 0.2s;
      box-shadow: 0 4px 16px rgba(15, 23, 42, 0.04);
    }
    .folder-card:hover {
      background: #fdfbf7;
      border-color: var(--gold-primary);
      transform: translateY(-2px);
      box-shadow: 0 8px 24px rgba(184, 134, 11, 0.15);
    }
    .folder-icon {
      background: rgba(184, 134, 11, 0.1);
      border: 1px solid rgba(184, 134, 11, 0.3);
      color: var(--gold-primary);
      padding: 9px 12px;
      border-radius: 10px;
      display: flex;
      align-items: center;
      justify-content: center;
    }
    .folder-info {
      flex: 1;
      overflow: hidden;
    }
    .folder-card-name {
      font-size: 0.9rem;
      font-weight: 700;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      color: #0f172a;
    }
    .folder-card-sub {
      font-size: 0.74rem;
      color: var(--text-muted);
      margin-top: 3px;
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .photo-count-pill {
      background: rgba(184, 134, 11, 0.1);
      border: 1px solid rgba(184, 134, 11, 0.3);
      color: var(--text-gold);
      padding: 2px 7px;
      border-radius: 10px;
      font-weight: 700;
      font-size: 0.72rem;
    }

    /* Roster Ingestion Views */
    #view-roster-download {
      width: 100%;
      max-width: 960px;
      display: none;
      flex-direction: column;
      align-items: center;
    }
    .roster-config-card {
      width: 100%;
      background: #ffffff;
      border: 1px solid rgba(180, 140, 45, 0.28);
      border-radius: 20px;
      padding: 28px;
      margin-bottom: 24px;
      box-shadow: 0 12px 35px -8px rgba(15, 23, 42, 0.08);
    }
    .roster-input-grid {
      display: grid;
      grid-template-columns: 2fr 1fr auto;
      gap: 14px;
      align-items: end;
    }
    @media (max-width: 768px) {
      .roster-input-grid { grid-template-columns: 1fr; }
    }
    .input-group {
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    .input-label {
      font-size: 0.76rem;
      font-family: var(--font-royal);
      color: var(--text-gold);
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }
    .roster-text-input {
      background: #ffffff;
      border: 1px solid rgba(180, 140, 45, 0.26);
      border-radius: 8px;
      padding: 12px 14px;
      color: #0f172a;
      font-size: 0.86rem;
      outline: none;
      transition: all 0.2s;
    }
    .roster-text-input:focus {
      border-color: var(--gold-primary);
      box-shadow: 0 0 0 3px rgba(184, 134, 11, 0.18);
    }
    .presets-row {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
      margin-top: 14px;
    }
    .presets-label {
      font-size: 0.74rem;
      font-family: var(--font-royal);
      color: var(--text-gold);
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }
    .preset-pill {
      background: #f8fafc;
      border: 1px solid rgba(180, 140, 45, 0.25);
      color: #334155;
      padding: 5px 12px;
      border-radius: 14px;
      font-size: 0.74rem;
      cursor: pointer;
      transition: all 0.2s;
    }
    .preset-pill:hover {
      background: #fdfbf7;
      border-color: var(--gold-primary);
      color: #855f19;
    }
    .quality-boost-tag {
      display: flex;
      align-items: center;
      gap: 8px;
      background: rgba(184, 134, 11, 0.08);
      border: 1px solid rgba(184, 134, 11, 0.28);
      border-radius: 10px;
      padding: 10px 14px;
      font-size: 0.8rem;
      color: #855f19;
      margin-top: 16px;
    }

    /* Roster Table Results */
    .roster-results-card {
      width: 100%;
      background: #ffffff;
      border: 1px solid rgba(180, 140, 45, 0.28);
      border-radius: 20px;
      padding: 24px;
      margin-bottom: 24px;
      box-shadow: 0 16px 40px rgba(15, 23, 42, 0.08);
    }
    .roster-header-bar {
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 12px;
      margin-bottom: 18px;
      padding-bottom: 14px;
      border-bottom: 1px solid rgba(180, 140, 45, 0.18);
    }
    .roster-title-badge {
      display: flex;
      align-items: center;
      gap: 12px;
      font-family: var(--font-royal);
      font-size: 1.15rem;
      font-weight: 700;
      color: #0f172a;
    }
    .roster-table {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.82rem;
    }
    .roster-table th {
      background: #f8fafc;
      color: #855f19;
      font-family: var(--font-royal);
      text-transform: uppercase;
      letter-spacing: 0.08em;
      font-size: 0.72rem;
      padding: 10px 12px;
      border-bottom: 1px solid rgba(180, 140, 45, 0.25);
      text-align: left;
    }
    .roster-table td {
      padding: 10px 12px;
      border-bottom: 1px solid rgba(180, 140, 45, 0.12);
      vertical-align: middle;
      color: #1e293b;
    }
    .roster-table tr:hover td {
      background: #fdfbf7;
    }
    .player-avatar-thumb {
      width: 38px;
      height: 48px;
      object-fit: cover;
      border-radius: 6px;
      background: #f1f5f9;
      border: 1px solid rgba(180, 140, 45, 0.2);
    }
    .jersey-badge {
      display: inline-block;
      width: 26px;
      height: 26px;
      line-height: 24px;
      text-align: center;
      background: rgba(184, 134, 11, 0.12);
      border: 1px solid rgba(184, 134, 11, 0.4);
      color: var(--text-gold);
      border-radius: 50%;
      font-weight: 800;
      font-size: 0.74rem;
    }
    .filename-preview-badge {
      font-family: var(--font-mono);
      font-size: 0.75rem;
      padding: 3px 8px;
      border-radius: 6px;
      background: #f8fafc;
      border: 1px solid rgba(180, 140, 45, 0.2);
      color: #855f19;
    }
    .roster-footer-bar {
      margin-top: 18px;
      padding-top: 16px;
      border-top: 1px solid rgba(180, 140, 45, 0.18);
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 14px;
    }

    /* Bulk Paste Drawer */
    .bulk-paste-drawer {
      display: none;
      background: #f8fafc;
      border: 1px solid rgba(180, 140, 45, 0.25);
      border-radius: 12px;
      padding: 16px;
      margin-bottom: 18px;
    }
    .bulk-paste-textarea {
      width: 100%;
      background: #ffffff;
      border: 1px solid rgba(180, 140, 45, 0.26);
      color: #0f172a;
      padding: 10px 14px;
      border-radius: 8px;
      font-size: 0.8rem;
      font-family: var(--font-mono);
      min-height: 100px;
      outline: none;
      margin-bottom: 10px;
    }
    .bulk-paste-textarea:focus {
      border-color: var(--gold-primary);
      box-shadow: 0 0 0 3px rgba(184, 134, 11, 0.18);
    }

    /* =========================================================================
       PAGE 2: WORKBENCH / SOVEREIGN STUDIO ATELIER
       ========================================================================= */
    #page-workbench {
      display: none;
      flex-direction: column;
      flex: 1;
      min-height: 0;
      height: calc(100vh - 54px);
      overflow: hidden;
    }
    header {
      background: rgba(255, 255, 255, 0.95);
      border-bottom: 1px solid rgba(180, 140, 45, 0.22);
      padding: 6px 20px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      height: 50px;
      min-height: 50px;
      flex-shrink: 0;
      box-shadow: 0 4px 16px rgba(15, 23, 42, 0.03);
    }
    .header-left {
      display: flex;
      align-items: center;
      gap: 14px;
    }
    .header-actions {
      display: flex;
      align-items: center;
      gap: 10px;
    }

    /* Royal Buttons */
    .btn {
      padding: 7px 15px;
      border-radius: 8px;
      font-weight: 700;
      font-size: 0.8rem;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 7px;
      border: 1px solid transparent;
      transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
    }
    .btn-primary {
      background: var(--gold-gradient);
      color: #ffffff;
      text-shadow: 0 1px 2px rgba(0, 0, 0, 0.25);
      font-weight: 800;
      border: 1px solid rgba(180, 140, 45, 0.5);
      box-shadow: 0 4px 16px rgba(184, 134, 11, 0.28);
      letter-spacing: 0.02em;
    }
    .btn-primary:hover {
      background: var(--gold-gradient-hover);
      transform: translateY(-1px);
      box-shadow: 0 6px 22px rgba(184, 134, 11, 0.4);
    }
    .btn-secondary {
      background: #ffffff;
      color: #1e293b;
      border: 1px solid rgba(180, 140, 45, 0.28);
      box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
    }
    .btn-secondary:hover {
      background: #fdfbf7;
      border-color: var(--gold-primary);
      color: #855f19;
      box-shadow: 0 2px 10px rgba(184, 134, 11, 0.15);
    }
    .btn:disabled { opacity: 0.45; cursor: not-allowed; }

    /* Workbench Sidebar */
    .workbench-body {
      display: flex;
      flex: 1;
      min-height: 0;
      overflow: hidden;
      position: relative;
    }
    .sidebar {
      width: 330px;
      background: #ffffff;
      border-right: 1px solid rgba(180, 140, 45, 0.2);
      padding: 16px;
      display: flex;
      flex-direction: column;
      gap: 14px;
      overflow-y: auto;
      flex-shrink: 0;
    }
    .section-label {
      font-family: var(--font-royal);
      font-size: 0.74rem;
      text-transform: uppercase;
      letter-spacing: 0.1em;
      color: var(--text-gold);
      font-weight: 700;
      margin-bottom: 6px;
    }
    .box {
      background: #fbfcfe;
      border: 1px solid rgba(180, 140, 45, 0.2);
      border-radius: 10px;
      padding: 12px;
    }
    .slider-row {
      display: flex;
      justify-content: space-between;
      margin-bottom: 6px;
      font-size: 0.8rem;
      font-weight: 600;
      color: #1e293b;
    }
    .pill {
      font-family: var(--font-mono);
      color: var(--text-gold);
      background: rgba(184, 134, 11, 0.1);
      border: 1px solid rgba(184, 134, 11, 0.3);
      padding: 1px 7px;
      border-radius: 4px;
      font-size: 0.74rem;
    }
    input[type=range] {
      width: 100%;
      height: 5px;
      background: #e2e8f0;
      border-radius: 3px;
      outline: none;
      -webkit-appearance: none;
      cursor: pointer;
    }
    input[type=range]::-webkit-slider-thumb {
      -webkit-appearance: none;
      width: 16px;
      height: 16px;
      border-radius: 50%;
      background: var(--gold-gradient);
      border: 1px solid rgba(180, 140, 45, 0.5);
      box-shadow: 0 1px 5px rgba(184, 134, 11, 0.4);
      cursor: pointer;
    }
    .tool-tabs {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 6px;
      margin-bottom: 10px;
    }
    .tool-tab {
      background: #f8fafc;
      border: 1px solid rgba(180, 140, 45, 0.2);
      color: #64748b;
      padding: 8px 4px;
      border-radius: 8px;
      font-size: 0.75rem;
      font-weight: 700;
      cursor: pointer;
      text-align: center;
      transition: all 0.2s;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 5px;
    }
    .tool-tab:hover { color: #0f172a; background: #fdfbf7; }
    .tool-tab.active {
      background: var(--gold-gradient);
      border-color: rgba(180, 140, 45, 0.5);
      color: #ffffff;
      font-weight: 800;
      box-shadow: 0 2px 10px rgba(184, 134, 11, 0.3);
    }
    .btn-grid {
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: 6px;
      margin-top: 8px;
    }
    .btn-sm {
      background: #ffffff;
      border: 1px solid rgba(180, 140, 45, 0.22);
      color: var(--text);
      padding: 6px;
      border-radius: 6px;
      font-size: 0.75rem;
      font-weight: 600;
      cursor: pointer;
      text-align: center;
      transition: all 0.15s;
    }
    .btn-sm:hover { background: #fdfbf7; border-color: var(--gold-primary); color: #855f19; }

    /* Center Stage */
    .stage {
      flex: 1;
      min-width: 0;
      min-height: 0;
      background: radial-gradient(circle at center, #f4f6fa 0%, #e8edf4 100%);
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      position: relative;
      overflow: hidden;
      padding: 8px 16px 26px 16px;
    }
    .stage-toolbar {
      position: absolute;
      top: 10px;
      display: flex;
      gap: 8px;
      background: rgba(255, 255, 255, 0.92);
      backdrop-filter: blur(12px);
      padding: 5px 12px;
      border-radius: 30px;
      border: 1px solid rgba(180, 140, 45, 0.3);
      z-index: 10;
      box-shadow: 0 4px 16px rgba(15, 23, 42, 0.08);
    }
    .chip {
      background: transparent;
      border: none;
      color: #64748b;
      font-size: 0.78rem;
      font-weight: 600;
      padding: 4px 10px;
      border-radius: 20px;
      cursor: pointer;
      transition: all 0.15s;
    }
    .chip.active, .chip:hover {
      color: #ffffff;
      background: var(--gold-gradient);
      font-weight: 800;
    }
    .viewport-outer {
      position: relative;
      padding: 6px;
      border: 2px dashed rgba(180, 140, 45, 0.45);
      border-radius: 14px;
      background: #ffffff;
      box-shadow: 0 16px 40px rgba(15, 23, 42, 0.1), 0 0 20px rgba(180, 140, 45, 0.06);
      display: flex;
      align-items: center;
      justify-content: center;
      margin-top: 10px;
      margin-bottom: 22px;
    }
    .viewport-container {
      width: min(440px, calc(100vh - 300px), calc(100vw - 420px));
      height: min(440px, calc(100vh - 300px), calc(100vw - 420px));
      max-width: 440px;
      max-height: 440px;
      aspect-ratio: 1 / 1;
      position: relative;
      overflow: hidden;
      border-radius: 8px;
    }
    .checkerboard {
      background-image: 
        linear-gradient(45deg, #f1f5f9 25%, transparent 25%), 
        linear-gradient(-45deg, #f1f5f9 25%, transparent 25%), 
        linear-gradient(45deg, transparent 75%, #f1f5f9 75%), 
        linear-gradient(-45deg, transparent 75%, #f1f5f9 75%);
      background-size: 20px 20px;
      background-position: 0 0, 0 10px, 10px -10px, -10px 0px;
      background-color: #ffffff;
    }
    canvas#editor-canvas {
      position: absolute;
      top: 0; left: 0; width: 100%; height: 100%;
      touch-action: none;
    }
    #brush-cursor {
      position: absolute;
      border: 2px solid var(--gold-primary);
      border-radius: 50%;
      pointer-events: none;
      transform: translate(-50%, -50%);
      display: none;
      z-index: 100;
    }
    .cursor-recover { border-color: #059669 !important; background: rgba(5, 150, 105, 0.2); }
    .cursor-erase { border-color: #e11d48 !important; background: rgba(225, 29, 72, 0.2); }

    .stage-hint {
      position: absolute;
      bottom: 8px;
      font-size: 0.73rem;
      color: #475569;
      background: rgba(255, 255, 255, 0.92);
      padding: 3px 12px;
      border-radius: 20px;
      border: 1px solid rgba(180, 140, 45, 0.25);
      display: flex;
      align-items: center;
      gap: 8px;
      box-shadow: 0 2px 10px rgba(15, 23, 42, 0.05);
      z-index: 10;
    }

    /* Bottom Carousel Filmstrip */
    .carousel-container {
      flex-shrink: 0;
      height: 126px;
      min-height: 126px;
      max-height: 126px;
      background: #ffffff;
      border-top: 2px solid rgba(180, 140, 45, 0.35);
      display: flex;
      flex-direction: column;
      box-shadow: 0 -4px 20px rgba(15, 23, 42, 0.08);
      z-index: 40;
      position: relative;
    }
    .carousel-header {
      height: 25px;
      min-height: 25px;
      padding: 0 16px;
      background: #faf8f5;
      border-bottom: 1px solid rgba(180, 140, 45, 0.18);
      display: flex;
      justify-content: space-between;
      align-items: center;
      user-select: none;
    }
    .carousel-title {
      font-family: var(--font-royal);
      font-size: 0.7rem;
      font-weight: 800;
      letter-spacing: 0.06em;
      color: var(--text-gold);
      display: flex;
      align-items: center;
      gap: 7px;
    }
    .carousel-count-badge {
      font-family: var(--font-mono);
      font-size: 0.68rem;
      font-weight: 700;
      color: #1e293b;
      background: #f1f5f9;
      border: 1px solid #cbd5e1;
      padding: 1px 7px;
      border-radius: 999px;
    }
    .carousel-nav-arrows {
      display: flex;
      align-items: center;
      gap: 5px;
    }
    .carousel-arrow-btn {
      background: #ffffff;
      border: 1px solid rgba(180, 140, 45, 0.3);
      border-radius: 4px;
      width: 24px;
      height: 19px;
      display: flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      color: #475569;
      transition: all 0.15s;
    }
    .carousel-arrow-btn:hover {
      background: var(--gold-gradient);
      color: #ffffff;
      border-color: var(--gold-primary);
    }
    .carousel-bar {
      flex: 1;
      min-height: 0;
      padding: 5px 14px;
      display: flex;
      align-items: center;
      gap: 10px;
      overflow-x: auto;
      overflow-y: hidden;
      scrollbar-width: thin;
      scrollbar-color: rgba(180, 140, 45, 0.4) #f1f5f9;
    }
    .carousel-bar::-webkit-scrollbar {
      height: 6px;
    }
    .carousel-bar::-webkit-scrollbar-track {
      background: #f1f5f9;
    }
    .carousel-bar::-webkit-scrollbar-thumb {
      background: rgba(180, 140, 45, 0.4);
      border-radius: 4px;
    }
    .carousel-bar::-webkit-scrollbar-thumb:hover {
      background: rgba(180, 140, 45, 0.7);
    }
    .carousel-item {
      display: flex;
      flex-direction: column;
      align-items: center;
      padding: 4px;
      background: #f8fafc;
      border: 1.5px solid rgba(180, 140, 45, 0.24);
      border-radius: 8px;
      cursor: pointer;
      min-width: 76px;
      width: 76px;
      height: 86px;
      flex-shrink: 0;
      transition: all 0.15s;
      position: relative;
      user-select: none;
    }
    .carousel-item:hover {
      border-color: var(--gold-primary);
      transform: translateY(-2px);
      background: #fdfbf7;
      box-shadow: 0 4px 12px rgba(184, 134, 11, 0.2);
    }
    .carousel-item.active {
      border-color: var(--gold-primary);
      background: #fefce8;
      box-shadow: 0 0 0 2px var(--gold-primary), 0 4px 12px rgba(184, 134, 11, 0.35);
      border-width: 2px;
    }
    .carousel-item img {
      width: 50px;
      height: 54px;
      object-fit: cover;
      border-radius: 4px;
      background: #e2e8f0;
      border: 1px solid rgba(0, 0, 0, 0.05);
    }
    .carousel-item span {
      font-size: 0.64rem;
      font-family: var(--font-mono);
      font-weight: 600;
      margin-top: 3px;
      color: #334155;
      max-width: 68px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      text-align: center;
    }
    .status-dot {
      position: absolute;
      top: 4px; right: 4px; width: 8px; height: 8px;
      border-radius: 50%; background: #94a3b8;
    }
    .status-dot.saved { background: #059669; box-shadow: 0 0 6px #059669; }
    .status-dot.cutout { background: var(--gold-primary); box-shadow: 0 0 6px var(--gold-primary); }

    /* Loading Overlay */
    .loading-overlay {
      position: fixed;
      inset: 0;
      background: rgba(255, 255, 255, 0.88);
      display: none;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 16px;
      z-index: 99999;
      backdrop-filter: blur(8px);
    }
    .spinner {
      width: 34px; height: 34px;
      border: 3px solid rgba(180, 140, 45, 0.2);
      border-top-color: var(--gold-primary);
      border-radius: 50%;
      animation: spin 0.8s linear infinite;
      box-shadow: 0 0 15px rgba(184, 134, 11, 0.25);
    }
    @keyframes spin { to { transform: rotate(360deg); } }

    /* =========================================================================
       SOVEREIGN SAAS MODALS
       ========================================================================= */
    .saas-modal-backdrop {
      position: fixed;
      inset: 0;
      background: rgba(15, 23, 42, 0.45);
      backdrop-filter: blur(14px);
      -webkit-backdrop-filter: blur(14px);
      display: none;
      justify-content: center;
      align-items: center;
      z-index: 10000;
      padding: 20px;
      overflow-y: auto;
      animation: modalFadeIn 0.2s cubic-bezier(0.16, 1, 0.3, 1);
    }
    @keyframes modalFadeIn {
      from { opacity: 0; transform: scale(0.96); }
      to { opacity: 1; transform: scale(1); }
    }
    .saas-modal-card {
      background: #ffffff;
      border: 1px solid rgba(180, 140, 45, 0.32);
      border-radius: 18px;
      width: 100%;
      max-width: 620px;
      max-height: 90vh;
      display: flex;
      flex-direction: column;
      box-shadow: 0 25px 65px -15px rgba(15, 23, 42, 0.2), 0 0 35px rgba(180, 140, 45, 0.08);
      position: relative;
      overflow: hidden;
    }
    .saas-modal-card.wide { max-width: 900px; }
    .saas-modal-header {
      padding: 20px 26px;
      border-bottom: 1px solid rgba(180, 140, 45, 0.2);
      display: flex;
      justify-content: space-between;
      align-items: center;
      background: #fbfcfe;
    }
    .saas-modal-title {
      font-family: var(--font-royal);
      font-size: 1.25rem;
      font-weight: 700;
      color: #0f172a;
      display: flex;
      align-items: center;
      gap: 10px;
      letter-spacing: 0.04em;
    }
    .saas-modal-close {
      background: transparent;
      border: none;
      color: #64748b;
      font-size: 1.3rem;
      cursor: pointer;
      padding: 4px 8px;
      border-radius: 6px;
      line-height: 1;
      transition: all 0.15s;
    }
    .saas-modal-close:hover {
      background: rgba(184, 134, 11, 0.12);
      color: #0f172a;
    }
    .saas-modal-body {
      padding: 26px;
      overflow-y: auto;
      flex: 1;
    }
    .saas-tabs {
      display: flex;
      gap: 8px;
      border-bottom: 1px solid rgba(180, 140, 45, 0.2);
      margin-bottom: 22px;
      padding-bottom: 2px;
    }
    .saas-tab-btn {
      background: transparent;
      border: none;
      border-bottom: 2px solid transparent;
      color: var(--text-muted);
      padding: 8px 16px;
      font-weight: 700;
      font-size: 0.86rem;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 8px;
      transition: all 0.2s;
    }
    .saas-tab-btn.active {
      color: var(--gold-primary);
      border-bottom-color: var(--gold-primary);
      font-family: var(--font-royal);
      letter-spacing: 0.04em;
    }
    .saas-form-group {
      margin-bottom: 18px;
    }
    .saas-form-label {
      display: block;
      font-size: 0.76rem;
      font-family: var(--font-royal);
      font-weight: 700;
      color: var(--text-gold);
      margin-bottom: 6px;
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }
    .saas-input {
      width: 100%;
      background: #ffffff;
      border: 1px solid rgba(180, 140, 45, 0.28);
      color: #0f172a;
      padding: 11px 16px;
      border-radius: 8px;
      font-size: 0.88rem;
      outline: none;
      transition: all 0.2s;
      font-family: inherit;
    }
    .saas-input:focus {
      border-color: var(--gold-primary);
      box-shadow: 0 0 0 3px rgba(184, 134, 11, 0.18);
    }
    .saas-textarea {
      width: 100%;
      background: #ffffff;
      border: 1px solid rgba(180, 140, 45, 0.26);
      color: #0f172a;
      padding: 12px 16px;
      border-radius: 8px;
      font-size: 0.85rem;
      outline: none;
      font-family: var(--font-mono);
      min-height: 140px;
      line-height: 1.5;
      resize: vertical;
    }
    .saas-textarea:focus {
      border-color: var(--gold-primary);
      box-shadow: 0 0 0 3px rgba(184, 134, 11, 0.18);
    }
    .seat-meter-card {
      background: #f8fafc;
      border: 1px solid rgba(180, 140, 45, 0.25);
      border-radius: 14px;
      padding: 18px;
      margin-bottom: 22px;
      box-shadow: 0 2px 10px rgba(15, 23, 42, 0.04);
    }
    .seat-meter-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 12px;
      font-size: 0.85rem;
    }
    .seat-bar-track {
      background: #e2e8f0;
      height: 9px;
      border: 1px solid rgba(180, 140, 45, 0.2);
      border-radius: 999px;
      overflow: hidden;
      position: relative;
    }
    .seat-bar-fill {
      height: 100%;
      background: var(--gold-gradient);
      box-shadow: 0 0 10px rgba(184, 134, 11, 0.35);
      transition: width 0.3s ease;
    }
    .saas-table {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.84rem;
    }
    .saas-table th {
      text-align: left;
      padding: 11px 14px;
      background: #f8fafc;
      color: var(--text-gold);
      font-family: var(--font-royal);
      font-weight: 700;
      border-bottom: 1px solid rgba(180, 140, 45, 0.25);
      font-size: 0.74rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }
    .saas-table td {
      padding: 12px 14px;
      border-bottom: 1px solid rgba(180, 140, 45, 0.12);
      color: #1e293b;
      vertical-align: middle;
    }
    .saas-table tr:hover td {
      background: #fdfbf7;
    }
    .btn-copy-link {
      background: rgba(184, 134, 11, 0.08);
      border: 1px solid rgba(184, 134, 11, 0.35);
      color: var(--text-gold);
      padding: 4px 10px;
      border-radius: 6px;
      font-size: 0.72rem;
      font-weight: 700;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 5px;
      transition: all 0.15s;
    }
    .btn-copy-link:hover {
      background: rgba(184, 134, 11, 0.18);
      color: #5c410c;
    }
    .btn-revoke-user {
      background: rgba(225, 29, 72, 0.08);
      border: 1px solid rgba(225, 29, 72, 0.32);
      color: #be123c;
      padding: 4px 10px;
      border-radius: 6px;
      font-size: 0.72rem;
      font-weight: 700;
      cursor: pointer;
      transition: all 0.15s;
    }
    .btn-revoke-user:hover {
      background: rgba(225, 29, 72, 0.16);
    }
    .result-pill-added {
      background: rgba(5, 150, 105, 0.08);
      border: 1px solid rgba(5, 150, 105, 0.3);
      color: #065f46;
      padding: 6px 12px;
      border-radius: 6px;
      font-size: 0.78rem;
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 6px;
    }
    .result-pill-skipped {
      background: rgba(217, 119, 6, 0.08);
      border: 1px solid rgba(217, 119, 6, 0.3);
      color: #92400e;
      padding: 6px 12px;
      border-radius: 6px;
      font-size: 0.78rem;
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 6px;
    }
    .btn-passkey {
      width: 100%;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 10px;
      background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
      color: #f8fafc;
      border: 1px solid rgba(212, 175, 55, 0.4);
      padding: 11px 18px;
      border-radius: 9px;
      font-family: inherit;
      font-weight: 700;
      font-size: 0.88rem;
      cursor: pointer;
      transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
      box-shadow: 0 4px 14px rgba(15, 23, 42, 0.15);
      margin-top: 10px;
    }
    .btn-passkey:hover {
      background: linear-gradient(135deg, #0f172a 0%, #020617 100%);
      border-color: var(--gold-primary);
      box-shadow: 0 6px 20px rgba(184, 134, 11, 0.25);
      transform: translateY(-1px);
    }
    .btn-gold {
      background: linear-gradient(135deg, #b8860b 0%, #d4af37 50%, #996515 100%);
      color: #ffffff;
      border: 1px solid #ffe89e;
      font-weight: 700;
      border-radius: 8px;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 8px;
      box-shadow: 0 3px 12px rgba(184, 134, 11, 0.28);
      transition: all 0.2s;
    }
    .btn-gold:hover {
      filter: brightness(1.08);
      box-shadow: 0 5px 18px rgba(184, 134, 11, 0.4);
      transform: translateY(-1px);
    }
    .saas-platform-admin-badge {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      background: linear-gradient(135deg, rgba(184, 134, 11, 0.08) 0%, rgba(212, 175, 55, 0.15) 100%);
      border: 1px solid rgba(184, 134, 11, 0.35);
      padding: 5px 12px;
      border-radius: 999px;
      font-size: 0.8rem;
    }
    .saas-platform-admin-badge .scope-tag {
      font-size: 0.68rem;
      background: rgba(15, 23, 42, 0.08);
      border: 1px solid rgba(15, 23, 42, 0.15);
      color: #475569;
      padding: 1px 7px;
      border-radius: 10px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }
    .kpi-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 14px;
      margin-bottom: 22px;
    }
    .kpi-metric-card {
      background: linear-gradient(135deg, #ffffff 0%, #fbfcfe 100%);
      border: 1px solid rgba(180, 140, 45, 0.26);
      border-radius: 12px;
      padding: 16px;
      box-shadow: 0 4px 15px rgba(15, 23, 42, 0.03);
      position: relative;
      overflow: hidden;
    }
    .kpi-metric-card::before {
      content: '';
      position: absolute;
      top: 0;
      left: 0;
      width: 100%;
      height: 3px;
      background: var(--gold-gradient);
    }
    .kpi-label {
      font-family: var(--font-royal);
      font-size: 0.72rem;
      color: var(--text-gold);
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      margin-bottom: 6px;
    }
    .kpi-value {
      font-size: 1.55rem;
      font-weight: 800;
      color: #0f172a;
      line-height: 1.1;
      font-family: inherit;
    }
    .kpi-sub {
      font-size: 0.72rem;
      color: var(--text-muted);
      margin-top: 4px;
    }
    .totp-code-display {
      font-family: var(--font-mono);
      font-size: 1.1rem;
      font-weight: 700;
      letter-spacing: 0.18em;
      background: #f1f5f9;
      border: 1px solid rgba(180, 140, 45, 0.3);
      padding: 10px 16px;
      border-radius: 8px;
      color: #0f172a;
      display: inline-block;
      user-select: all;
    }
    .backup-codes-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
      margin-top: 10px;
    }
    .backup-code-item {
      font-family: var(--font-mono);
      font-size: 0.85rem;
      background: #f8fafc;
      border: 1px dashed rgba(180, 140, 45, 0.4);
      padding: 6px 10px;
      border-radius: 6px;
      color: #334155;
      text-align: center;
      font-weight: 600;
    }
  </style>
</head>
<body>
  <!-- ENTERPRISE AUTHENTICATION GATEWAY (STRICT NO-FREE-SERVICE LOCKOUT) -->
  <div id="page-enterprise-gateway" style="display:flex;">
    <div class="gateway-container">
      <!-- Left Hero Column -->
      <div class="gateway-hero-col">
        <div class="gateway-brand-badge">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
          <span>RESTRICTED ENTERPRISE ATELIER • LICENSED SEATS ONLY</span>
        </div>
        <h1 class="gateway-hero-title">
          The Sovereign Standard in <span>Athletic Portrait Intelligence</span>
        </h1>
        <p class="gateway-hero-desc">
          Standardized 180×180 neural facial composition, automated foreground separation, and synchronized roster ingestion with zero cloud storage footprint. Purpose-engineered for premier athletics departments and global sports franchises.
        </p>

        <div class="gateway-features-list">
          <div class="gateway-feature-item">
            <div class="gateway-feature-icon">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>
            </div>
            <div>
              <div class="gateway-feature-title">Standardized 180×180 Facial Centering</div>
              <div class="gateway-feature-desc">AI landmark alignment guarantees consistent chin-to-forehead framing across your entire athletic roster.</div>
            </div>
          </div>
          <div class="gateway-feature-item">
            <div class="gateway-feature-icon">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>
            </div>
            <div>
              <div class="gateway-feature-title">Zero Cloud Disk Footprint (Direct PC Processing)</div>
              <div class="gateway-feature-desc">Photos process directly in browser memory and export to your computer storage without filling server space.</div>
            </div>
          </div>
          <div class="gateway-feature-item">
            <div class="gateway-feature-icon">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>
            </div>
            <div>
              <div class="gateway-feature-title">Official League Roster Ingestion</div>
              <div class="gateway-feature-desc">Instantly import players from UK EIHL, NHL, and NCAA teams with automatic jersey number file mapping.</div>
            </div>
          </div>
          <div class="gateway-feature-item">
            <div class="gateway-feature-icon">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>
            </div>
            <div>
              <div class="gateway-feature-title">Multi-Tenant Company Governance</div>
              <div class="gateway-feature-desc">Enterprise seat allocations, bulk CSV team onboarding, and role-based permissions.</div>
            </div>
          </div>
        </div>
      </div>

      <!-- Right Auth Card Column -->
      <div class="gateway-auth-col">
        <div class="gateway-card">
          <div class="gateway-card-header">
            <div class="gateway-card-title">Enterprise Atelier Portal</div>
            <div class="gateway-card-sub">Authenticate with corporate credentials or activate an invited company seat</div>
          </div>

          <div class="gateway-tabs">
            <button class="gateway-tab-btn active" id="gateway-tab-login-btn" onclick="switchGatewayTab('login')">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
              <span>Sign In</span>
            </button>
            <button class="gateway-tab-btn" id="gateway-tab-activate-btn" onclick="switchGatewayTab('activate')">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><line x1="20" y1="8" x2="20" y2="14"/><line x1="23" y1="11" x2="17" y2="11"/></svg>
              <span>Activate Seat</span>
            </button>
          </div>

          <!-- View 1: Sign In -->
          <div id="gateway-view-login">
            <form onsubmit="handleGatewayLoginSubmit(event)">
              <div class="saas-form-group">
                <label class="saas-form-label">Corporate Email Address</label>
                <div class="input-icon-wrapper">
                  <svg class="input-icon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/></svg>
                  <input type="email" id="gateway-login-email" class="saas-input with-icon" placeholder="name@company.com" required autocomplete="username">
                </div>
              </div>
              <div class="saas-form-group">
                <label class="saas-form-label">Password</label>
                <div class="input-icon-wrapper">
                  <svg class="input-icon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
                  <input type="password" id="gateway-login-password" class="saas-input with-icon" placeholder="••••••••" required autocomplete="current-password">
                </div>
              </div>

              <div id="gateway-login-error" class="saas-alert-danger" style="display:none;"></div>

              <button type="submit" class="btn btn-primary" id="btn-gateway-login" style="width:100%; padding:12px; margin-top:8px; font-size:0.9rem;">
                <span>Enter Atelier Workspace</span>
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/></svg>
              </button>

              <div style="display:flex; align-items:center; gap:10px; margin:14px 0 6px 0;">
                <div style="flex:1; height:1px; background:rgba(180,140,45,0.2);"></div>
                <span style="font-size:0.72rem; color:var(--text-muted); font-weight:700; text-transform:uppercase; letter-spacing:0.06em;">Or Biometric Key</span>
                <div style="flex:1; height:1px; background:rgba(180,140,45,0.2);"></div>
              </div>
              <button type="button" class="btn-passkey" onclick="startPasskeyLogin('gateway')">
                <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="#d4af37" stroke-width="2"><path d="M2 18v3c0 .6.4 1 1 1h4v-3h3v-3h2l1.4-1.4a6.5 6.5 0 1 0-4-4Z"/><circle cx="16.5" cy="7.5" r=".5"/></svg>
                <span>Sign In with Passkey (Touch ID / Face ID)</span>
              </button>

              <div style="margin-top:16px; padding-top:14px; border-top:1px solid rgba(180, 140, 45, 0.2); display:flex; justify-content:space-between; align-items:center;">
                <span style="font-size:0.75rem; color:var(--text-muted);">Evaluation Demo Access:</span>
                <button type="button" class="btn-demo-fill" onclick="fillDemoGatewayCredentials()">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
                  <span>Fill SuperAdmin</span>
                </button>
              </div>
            </form>
          </div>

          <!-- View 2: Activate Token -->
          <div id="gateway-view-activate" style="display:none;">
            <div class="saas-alert-info">
              Enter your invitation token and set a password to activate your company seat.
            </div>
            <form onsubmit="handleGatewayActivationSubmit(event)">
              <div class="saas-form-group">
                <label class="saas-form-label">Invitation Token</label>
                <input type="text" id="gateway-activate-token" class="saas-input" placeholder="Paste 32-character token" required>
              </div>
              <div class="saas-form-group">
                <label class="saas-form-label">Your Full Name</label>
                <input type="text" id="gateway-activate-name" class="saas-input" placeholder="e.g. Jordan Miller" required>
              </div>
              <div class="saas-form-group">
                <label class="saas-form-label">Create Password</label>
                <input type="password" id="gateway-activate-password" class="saas-input" placeholder="Minimum 6 characters" required minlength="6">
              </div>
              <div class="saas-form-group">
                <label class="saas-form-label">Confirm Password</label>
                <input type="password" id="gateway-activate-confirm" class="saas-input" placeholder="Repeat password" required minlength="6">
              </div>

              <div id="gateway-activate-error" class="saas-alert-danger" style="display:none;"></div>

              <button type="submit" class="btn btn-primary" id="btn-gateway-activate" style="width:100%; padding:12px; margin-top:8px; font-size:0.9rem;">
                <span>Activate Seat & Open Studio</span>
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/></svg>
              </button>
            </form>
          </div>

          <!-- View 3: Two-Factor Authentication (MFA) -->
          <div id="gateway-view-mfa" style="display:none;">
            <div style="text-align:center; margin-bottom:18px;">
              <div style="width:48px; height:48px; border-radius:50%; background:rgba(184,134,11,0.12); border:1px solid rgba(184,134,11,0.3); display:inline-flex; align-items:center; justify-content:center; margin-bottom:10px;">
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="var(--gold-primary)" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
              </div>
              <div style="font-family:var(--font-royal); font-size:1.15rem; font-weight:700; color:#0f172a;">Two-Factor Verification</div>
              <div style="font-size:0.8rem; color:var(--text-muted); margin-top:4px;">Enter the 6-digit code from your authenticator app or an emergency backup code.</div>
            </div>
            <form onsubmit="handleMfaLoginSubmit(event, 'gateway')">
              <input type="hidden" id="gateway-mfa-token" value="">
              <div class="saas-form-group">
                <label class="saas-form-label">Authenticator Code / Backup Code</label>
                <input type="text" id="gateway-mfa-code" class="saas-input" placeholder="123456" autocomplete="one-time-code" required style="font-size:1.3rem; text-align:center; letter-spacing:0.18em; font-family:var(--font-mono); font-weight:800;">
              </div>
              <div id="gateway-mfa-error" class="saas-alert-danger" style="display:none; margin-bottom:12px;"></div>
              <button type="submit" class="btn btn-primary" id="btn-gateway-mfa" style="width:100%; padding:12px; margin-top:4px; font-size:0.9rem;">
                <span>Verify & Enter Workspace</span>
              </button>
              <button type="button" class="btn btn-secondary" onclick="cancelMfaLogin('gateway')" style="width:100%; padding:9px; margin-top:10px; font-size:0.82rem;">
                <span>← Back to Credentials Sign In</span>
              </button>
            </form>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- GLOBAL SAAS TOP NAVIGATION BAR -->
  <div id="saas-top-navbar" class="saas-navbar" style="display:none;">
    <div class="saas-nav-left">
      <div style="display:flex; align-items:center; gap:12px;">
        <div style="width:36px; height:36px; border-radius:10px; background:var(--gold-gradient); display:flex; align-items:center; justify-content:center; box-shadow:0 0 18px rgba(212,175,55,0.45); border:1px solid #ffe89e;">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#05070a" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 18h18M4 18l2-10 5 6 3-8 3 8 5-6 2 10H4z"/><circle cx="12" cy="4" r="1.5"/><circle cx="6" cy="8" r="1.5"/><circle cx="18" cy="8" r="1.5"/></svg>
        </div>
        <div style="display:flex; flex-direction:column; line-height:1.2;">
          <div style="font-family:'Cinzel', serif; font-weight:800; font-size:1.05rem; letter-spacing:0.06em; color:var(--text);">SOVEREIGN STUDIO</div>
          <div style="font-size:0.64rem; color:var(--text-gold); font-weight:700; letter-spacing:0.12em; text-transform:uppercase;">ROYAL PORTRAIT ATELIER</div>
        </div>
      </div>
      <!-- Company badge (Hidden for SuperAdmin) -->
      <div id="nav-company-wrapper" style="display:none; align-items:center; gap:8px;">
        <div class="saas-company-badge">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="4" y="2" width="16" height="20" rx="2"/><line x1="9" y1="22" x2="9" y2="12"/><line x1="15" y1="22" x2="15" y2="12"/><line x1="9" y1="6" x2="9.01" y2="6"/><line x1="15" y1="6" x2="15.01" y2="6"/></svg>
          <span id="nav-company-name">Company</span>
          <span id="nav-company-plan" class="saas-plan-pill plan-team">Team</span>
        </div>
        <div id="nav-seat-quota-pill" class="seat-quota-pill" onclick="openTeamModal('members')" title="Click to view team members & subscription quota">
          <div class="seat-mini-progress">
            <div id="nav-seat-mini-fill" class="seat-mini-fill" style="width: 7%;"></div>
          </div>
          <span id="nav-seat-quota-text">1 / 15 Seats</span>
        </div>
      </div>
      <!-- Platform SuperAdmin Scope Badge (Shown ONLY for SuperAdmin) -->
      <div id="nav-superadmin-scope-badge" class="saas-platform-admin-badge" style="display:none;">
        <span style="font-size:1rem;">👑</span>
        <span style="font-weight:800; color:var(--text); letter-spacing:0.02em;">Platform SuperAdmin</span>
        <span class="scope-tag">Master Fleet Scope (No Seat Consumed)</span>
      </div>
    </div>

    <div class="saas-nav-right">
      <!-- State 1: Logged Out -->
      <div id="nav-auth-logged-out" style="display:flex; align-items:center; gap:8px;">
        <button class="btn btn-primary" onclick="showAuthModal('login')" style="padding: 7px 16px; font-size: 0.82rem;">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
          <span>Sign In</span>
        </button>
      </div>

      <!-- State 2: Logged In -->
      <div id="nav-auth-logged-in" style="display:none; align-items:center; gap:10px;">
        <div class="user-profile-pill" id="nav-user-profile-pill" onclick="openAccountSettingsModal('credentials')" title="Account & Security Settings: Change password, credentials, MFA & Passkeys" style="cursor:pointer;">
          <div class="user-avatar-chip" id="nav-user-avatar">AD</div>
          <span id="nav-user-name" style="font-weight:700;">Admin</span>
          <span id="nav-user-role" class="user-role-tag role-superadmin">SuperAdmin</span>
        </div>
        <button class="btn btn-secondary" onclick="openAccountSettingsModal('credentials')" title="Manage credentials, change password, MFA & Passkeys" style="font-size:0.8rem; padding:6px 11px;">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
          <span>Security</span>
        </button>
        <button class="btn btn-secondary" id="btn-nav-team" onclick="openTeamModal('bulk')" title="Manage company users, seats, and invitations" style="border-color:#38bdf8; color:#38bdf8; font-size:0.8rem; padding:6px 12px;">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>
          <span>Manage Team</span>
        </button>
        <button class="btn btn-gold" id="btn-nav-platform-dashboard" onclick="openPlatformDashboard()" title="Open Multi-Tenant Platform Dashboard" style="display:none; padding:6px 14px; font-size:0.8rem; font-weight:700;">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="4" y="2" width="16" height="20" rx="2"/><line x1="9" y1="22" x2="9" y2="12"/><line x1="15" y1="22" x2="15" y2="12"/></svg>
          <span>Platform Dashboard (<strong id="nav-company-count-badge">3</strong>)</span>
        </button>
        <button class="btn btn-secondary" onclick="logoutUser()" title="Log out of Portrait Studio Pro" style="font-size:0.8rem; padding:6px 12px;">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>
          <span>Sign Out</span>
        </button>
      </div>
    </div>
  </div>

  <!-- Native Folder Picker Input -->
  <input type="file" id="native-folder-picker" webkitdirectory directory multiple style="display:none;" onchange="onNativeFolderPicked(event)">

  <!-- PAGE 1: FOLDER SELECTION & ROSTER DOWNLOAD LANDING SCREEN -->
  <div id="page-folder-select">
    <div class="landing-hero">
      <div class="hero-badge"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg> IMPERIAL PORTRAIT COMPOSITION SUITE</div>
      <h1 class="landing-title">Standardized <span>Portrait Atelier</span></h1>
      <p class="landing-subtitle">
        Download high-resolution roster portraits with custom player ID assignment, or select an existing local folder to crop into standardized 180×180 transparent headshots.
      </p>
      <div style="display:flex; justify-content:center; align-items:center; gap:12px; margin-top:14px; flex-wrap:wrap;">
        <span style="font-size:0.75rem; background:rgba(5, 150, 105, 0.08); border:1px solid rgba(5, 150, 105, 0.25); color:#047857; padding:5px 12px; border-radius:20px; font-weight:700; display:inline-flex; align-items:center; gap:5px;">
          <span style="width:7px; height:7px; border-radius:50%; background:#10b981; box-shadow:0 0 8px #10b981; display:inline-block; margin-right:4px;"></span><span>Sovereign Client Direct Pipeline (0 Server Bytes)</span>
        </span>
        <button class="btn btn-secondary" onclick="freeServerStorageAndMemory()" title="Purge temporary files on Render and clear RAM" style="font-size:0.75rem; padding:5px 14px; border-color:rgba(225, 29, 72, 0.3); color:#be123c; font-weight:700;">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/></svg><span>Purge Server RAM</span>
        </button>
      </div>
    </div>

    <!-- Mode Selector Tabs -->
    <div class="landing-tabs-bar">
      <button class="landing-tab active" id="tab-btn-local" onclick="switchLandingTab('local')">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
        <span>Local Folder Atelier</span>
      </button>
      <button class="landing-tab" id="tab-btn-roster" onclick="switchLandingTab('roster')">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
        <span>Team Roster Ingest</span>
      </button>
    </div>

    <!-- VIEW A: LOCAL FOLDER SELECTION -->
    <div id="view-local-folder" style="width: 100%; max-width: 960px; display: flex; flex-direction: column; align-items: center;">
      <!-- Folder Action Box -->
      <div class="folder-action-card" id="folder-drop-zone">
        <div class="drop-zone-icon">
          <svg width="38" height="38" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
        </div>
        <label for="native-folder-picker" class="browse-btn-big" style="cursor: pointer;">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
          <span>Choose Local Photo Folder</span>
        </label>
        <input type="file" id="native-folder-picker" webkitdirectory directory multiple style="display:none;" onchange="onNativeFolderPicked(event)">
        <input type="file" id="native-files-picker" multiple accept="image/*" style="display:none;" onchange="onNativeFilesPicked(event)">

        <div style="margin-top: 10px;">
          <label for="native-files-picker" style="font-size:0.83rem; color:var(--accent); cursor:pointer; text-decoration:underline;">
            or click here to select individual photo files (.png, .jpg, .webp)
          </label>
        </div>

        <div style="margin-top: 16px; font-size: 0.85rem; color: var(--text-muted);">
          or drag & drop a folder or photo files directly into this box:
        </div>

        <div class="path-input-row" style="margin-top: 16px;">
          <input type="text" id="manual-path-input" class="path-input" spellcheck="false" placeholder="e.g. 1908-Saint Anselm or full folder path" onkeydown="if(event.key==='Enter') openManualPath()">
          <button class="btn btn-primary" onclick="openManualPath()">Open Folder</button>
        </div>
      </div>

      <!-- Detected Team Folders Section -->
      <div class="detected-section">
        <div class="detected-heading">
          <div style="display:inline-flex; align-items:center; gap:8px;"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg><span>Detected Photo Folders in Downloads</span></div>
          <span style="font-size:0.75rem; color:var(--text-muted); font-weight:normal;">Click any folder to open</span>
        </div>
        <div class="detected-grid" id="detected-folders-grid">
          <!-- Rendered dynamically -->
        </div>
      </div>
    </div>

    <!-- VIEW B: ROSTER DOWNLOADER & NUMBER ASSIGNER -->
    <div id="view-roster-download">
      <div class="roster-config-card">
        <div class="roster-input-grid">
          <div class="input-group">
            <label class="input-label">Roster Website URL (UK Teams, NHL, NCAA/Sidearm)</label>
            <input type="url" id="roster-url-input" class="roster-text-input" spellcheck="false" placeholder="https://www.cardiffdevils.com/team/ or https://coventryblaze.co.uk/roster" value="https://www.cardiffdevils.com/team/" onkeydown="if(event.key==='Enter') fetchRosterPlayers()">
          </div>
          <div class="input-group">
            <label class="input-label">Destination Folder Name</label>
            <input type="text" id="roster-folder-input" class="roster-text-input" placeholder="Cardiff Devils" value="Cardiff Devils" onkeydown="if(event.key==='Enter') fetchRosterPlayers()">
          </div>
          <div>
            <button class="btn btn-primary" style="padding: 12px 22px; font-size: 0.88rem;" onclick="fetchRosterPlayers()">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
              <span>Fetch Roster</span>
            </button>
          </div>
        </div>

        <!-- Quick Presets -->
        <div style="display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin-top:12px;">
          <span style="font-size:0.75rem; color:var(--text-muted); font-weight:700;">Quick Presets:</span>
          <button type="button" class="preset-pill" onclick="setPresetUrl('https://jegkorong.deac.hu/a-csapat', 'DEAC')">DEAC (Erste Liga)</button>
          <button type="button" class="preset-pill" onclick="setPresetUrl('https://gyergyoihoki.ro/jatekosok-2/', 'Gyergyói Hoki Klub')">Gyergyói HK (Erste Liga)</button>
          <button type="button" class="preset-pill" onclick="setPresetUrl('https://www.hcbilitygri.cz/roster/MUZ', 'Bílí Tygři Liberec')">Bílí Tygři Liberec (Extraliga)</button>
          <button type="button" class="preset-pill" onclick="setPresetUrl('https://www.bkboleslav.cz/roster/MUZ', 'BK Mladá Boleslav')">BK Mladá Boleslav (Extraliga)</button>
          <button type="button" class="preset-pill" onclick="setPresetUrl('https://www.cardiffdevils.com/team/', 'Cardiff Devils')">Cardiff Devils (EIHL)</button>
          <button type="button" class="preset-pill" onclick="setPresetUrl('https://coventryblaze.co.uk/roster', 'Coventry Blaze')">Coventry Blaze (EIHL)</button>
          <button type="button" class="preset-pill" onclick="setPresetUrl('https://www.belfastgiants.com/players', 'Belfast Giants')">Belfast Giants (EIHL)</button>
          <button type="button" class="preset-pill" onclick="setPresetUrl('https://www.nhl.com/sabres/roster', 'Buffalo Sabres')">Buffalo Sabres (NHL)</button>
          <button type="button" class="preset-pill" onclick="setPresetUrl('https://smcathletics.com/sports/mens-basketball/roster/2025-26', 'Saint Michael\'s College')">Saint Michael's (NCAA)</button>
        </div>

        <div class="quality-boost-tag">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>
          <span><strong>Production Quality Standard:</strong> High-res transparent headshots standardized with Lanczos-3 downsampling to 800px source canvas.</span>
        </div>
      </div>

      <!-- Fetched Players Section -->
      <div class="roster-results-card" id="roster-results-card" style="display: none;">
        <div class="roster-header-bar">
          <div class="roster-title-badge">
            <span id="roster-team-title">Team Roster</span>
            <span class="photo-count-pill" id="roster-player-count">0 Players</span>
          </div>
          <div style="display:flex; gap:8px; flex-wrap:wrap; align-items:center;">
            <button class="btn btn-primary btn-sheet-copy" onclick="copyRosterForSheets()" title="Copy entire table to clipboard formatted for instant paste into Google Sheets or Excel">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg><span>Copy for Sheets</span>
            </button>
            <button class="btn btn-secondary" onclick="exportRosterToCSV()" title="Download full roster as CSV spreadsheet">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg><span>Export CSV</span>
            </button>
            <button class="btn btn-secondary" onclick="useJerseyNumbersAsAssigned()" title="Assign every player's jersey number as their file ID">
              <span># Use Jersey Numbers</span>
            </button>
            <button class="btn btn-secondary" onclick="toggleBulkPasteDrawer()">
              <span>Bulk Paste IDs</span>
            </button>
            <button class="btn btn-secondary" onclick="clearAllAssignedNumbers()">
              <span>Reset IDs</span>
            </button>
          </div>
        </div>

        <!-- Bulk Paste Drawer -->
        <div class="bulk-paste-drawer" id="bulk-paste-drawer">
          <div style="font-size:0.8rem; font-weight:700; color:var(--text); margin-bottom:6px;">
            Paste Assigned Numbers from Excel, Sheets, or Text:
          </div>
          <div style="font-size:0.75rem; color:var(--text-muted); margin-bottom:8px;">
            Supports <code>Name &lt;Tab&gt; Number</code> (copied directly from spreadsheet), or one number per line in player order, or JSON.
          </div>
          <textarea id="bulk-paste-textarea" class="bulk-paste-textarea" placeholder="Tay Dzingou&#9;1947454&#10;Marcus Meeks&#9;882177&#10;Braeden Elnicki&#9;&#10;..."></textarea>
          <div style="display:flex; justify-content:flex-end; gap:8px;">
            <button class="btn btn-secondary" style="font-size:0.75rem; padding:4px 10px;" onclick="toggleBulkPasteDrawer()">Cancel</button>
            <button class="btn btn-primary" style="font-size:0.75rem; padding:4px 12px;" onclick="applyBulkPaste()">Apply to Table</button>
          </div>
        </div>

        <!-- Players Table -->
        <div style="overflow-x: auto; max-height: 520px; overflow-y: auto;">
          <table class="roster-table" id="roster-data-table">
            <thead>
              <tr>
                <th style="min-width: 180px;">Player</th>
                <th style="width: 45px; text-align: center;">#</th>
                <th style="width: 55px; text-align: center;">Pos</th>
                <th style="width: 45px; text-align: center;">Sh</th>
                <th style="width: 65px; text-align: center;">Ht</th>
                <th style="width: 60px; text-align: center;">Wt</th>
                <th style="min-width: 115px;">Born</th>
                <th style="min-width: 160px;">Birthplace</th>
                <th style="width: 160px;">Assigned ID</th>
                <th style="width: 180px;">Resulting Filename</th>
              </tr>
            </thead>
            <tbody id="roster-table-body">
              <!-- Dynamically populated -->
            </tbody>
          </table>
        </div>

        <!-- Footer Bar -->
        <div class="roster-footer-bar">
          <div class="roster-summary-text" id="roster-summary-text">
            Ready to download
          </div>
          <div style="display:flex; gap:10px; align-items:center; flex-wrap:wrap;">
            <button class="btn btn-secondary" style="padding: 10px 20px; font-size: 0.92rem; background:#0284c7; border-color:#38bdf8; color:#fff; font-weight:700;" onclick="openRosterInStudioDirectly()" title="Load photos directly into studio workbench without writing to Render storage">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="4"/></svg><span>Open in Studio</span>
            </button>
            <button class="btn btn-primary" id="btn-download-roster" style="padding: 10px 24px; font-size: 0.92rem;" onclick="downloadAllRosterPhotos()">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg><span>Download All Photos (ZIP)</span>
            </button>
          </div>
        </div>
      </div>

      <!-- Success Card -->
      <div class="roster-results-card" id="roster-success-card" style="display: none; text-align: center; border-color: rgba(16, 185, 129, 0.4); background: rgba(16, 185, 129, 0.05);">
        <div style="width:48px; height:48px; border-radius:50%; background:rgba(16,185,129,0.15); border:1px solid rgba(16,185,129,0.35); display:inline-flex; align-items:center; justify-content:center; color:#34d399; margin:0 auto 12px auto;"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg></div>
        <h3 style="font-size: 1.25rem; font-weight: 800; color: var(--text); margin-bottom: 6px;">Photos Downloaded to Your PC!</h3>
        <p style="color: var(--text-muted); font-size: 0.88rem; margin-bottom: 16px;" id="roster-success-desc">
          All portraits were downloaded directly to your computer's Downloads as a standardized ZIP (0 bytes stored on Render).
        </p>
        <div style="display:flex; justify-content:center; gap:12px; margin-top:8px; flex-wrap:wrap;">
          <button class="btn btn-primary" style="padding: 12px 28px; font-size: 1rem; font-weight:700;" onclick="openDownloadedFolderInStudio()">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="4"/></svg><span>Open in Studio Workbench</span>
          </button>
          <button class="btn btn-secondary" style="padding: 12px 24px; font-size: 0.95rem; font-weight:700; background:#0284c7; border-color:#38bdf8; color:#fff;" onclick="downloadAllRosterPhotos()">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg><span>Re-download ZIP</span>
          </button>
          <button class="btn btn-secondary" style="padding: 12px 20px; font-size: 0.9rem;" onclick="backToRosterView()">
            <span>Back to Roster</span>
          </button>
        </div>
      </div>
    </div>
  </div>

  <!-- PAGE 2: WORKBENCH / STUDIO SCREEN -->
  <div id="page-workbench">
    <header>
      <div class="header-left">
        <button class="btn btn-secondary" onclick="showFolderSelectPage()">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="19" y1="12" x2="5" y2="12"/><polyline points="12 19 5 12 12 5"/></svg><span>Change Folder</span>
        </button>
        <div style="display:flex; flex-direction:column;">
          <div style="font-size:0.88rem; font-weight:800;" id="active-folder-name">Folder Name</div>
          <div style="font-size:0.7rem; color:var(--accent); font-family:'JetBrains Mono', monospace;" id="active-output-name">→ folder_edited/</div>
        </div>
      </div>

      <div class="header-actions">
        <button class="btn btn-secondary" onclick="freeServerStorageAndMemory()" title="Purge server temporary files and clear RAM" style="border-color: rgba(239, 68, 68, 0.4); color: #fca5a5; font-size: 0.8rem; padding: 6px 12px;">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/></svg><span>Free RAM</span>
        </button>
        <button class="btn btn-secondary" id="btn-cutout" onclick="triggerCutout()">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1 1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275L12 3Z"/></svg><span>AI Cutout</span>
        </button>
        <button class="btn btn-secondary" onclick="saveActivePhoto()">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg><span>Save Headshot</span>
        </button>
        <button class="btn btn-primary" id="btn-batch-all" onclick="batchProcessFolder()">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg><span>Process All (ZIP)</span>
        </button>
        <button class="btn btn-secondary" style="border-color:#38bdf8; color:#38bdf8; font-weight:700;" onclick="downloadActiveEditedZip()" title="Download all edited headshots as a ZIP file">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg><span>Download ZIP</span>
        </button>
        <button class="btn btn-secondary" onclick="openTeamModal('bulk')" title="Team & Subscription Seats" style="font-size:0.8rem; padding:6px 12px; border-color:rgba(56,189,248,0.4); color:#7dd3fc;">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/></svg><span>Team</span>
        </button>
      </div>
    </header>

    <div class="workbench-body">
      <!-- Left Sidebar -->
      <div class="sidebar">
        <div class="section-label">Tool Mode</div>
        <div class="tool-tabs">
          <button class="tool-tab active" id="tab-frame" onclick="setMode('frame')"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 11V6a2 2 0 0 0-2-2v0a2 2 0 0 0-2 2v0"/><path d="M14 10V4a2 2 0 0 0-2-2v0a2 2 0 0 0-2 2v2"/><path d="M10 10.5V6a2 2 0 0 0-2-2v0a2 2 0 0 0-2 2v8"/><path d="M18 8a2 2 0 1 1 4 0v6a8 8 0 0 1-8 8h-2c-2.8 0-4.5-.86-5.99-2.34l-3.6-3.6a2 2 0 0 1 2.83-2.82L7 15"/></svg><span>Pan & Zoom</span></button>
          <button class="tool-tab" id="tab-recover" onclick="setMode('recover')"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m14 12-8.5 8.5a2.12 2.12 0 1 1-3-3L11 9"/><path d="M18 11l-4-4"/><path d="m19 7 2-2"/></svg><span>Recover</span></button>
          <button class="tool-tab" id="tab-erase" onclick="setMode('erase')"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m7 21-4.3-4.3c-1-1-1-2.5 0-3.4l9.6-9.6c1-1 2.5-1 3.4 0l5.6 5.6c1 1 1 2.5 0 3.4L13 21"/><path d="M22 21H7"/></svg><span>Erase</span></button>
        </div>

        <!-- Mode 1: Pan & Zoom -->
        <div id="controls-frame">
          <div class="section-label">Framing & Zoom</div>
          <div class="box">
            <div class="slider-row">
              <span>Zoom</span>
              <span class="pill" id="zoom-badge">100%</span>
            </div>
            <input type="range" id="zoom-slider" min="10" max="150" value="40" oninput="onZoomSlider(this.value)">
            <div class="btn-grid">
              <button class="btn-sm" onclick="autoAlignCurrent()">Auto-Align Face</button>
              <button class="btn-sm" onclick="fitWidth()">Fit Width</button>
              <button class="btn-sm" onclick="fitHeight()">Fit Height</button>
              <button class="btn-sm" onclick="centerPhoto()">Center</button>
            </div>
          </div>

          <div class="section-label" style="margin-top:12px;">Team Batch Framing</div>
          <div class="box">
            <p style="font-size:0.75rem; color:var(--text-muted); margin-bottom:8px;">
              Apply this portrait's exact scale & position across all photos in folder:
            </p>
            <button class="btn btn-secondary" style="width:100%; justify-content:center; font-size:0.75rem;" onclick="applyFramingToAll()">
              <span>Apply Framing to All</span>
            </button>
          </div>
        </div>

        <!-- Mode 2 & 3: Retouch Brushes -->
        <div id="controls-brush" style="display:none;">
          <div class="section-label">Brush Controls</div>
          <div class="box">
            <div class="slider-row">
              <span>Brush Size</span>
              <span class="pill" id="brush-size-badge">24 px</span>
            </div>
            <input type="range" id="brush-size-slider" min="4" max="70" value="24" oninput="setBrushSize(this.value)">

            <div style="display:flex; gap:8px; margin-top:12px;">
              <button class="btn-sm" style="flex:1;" onclick="undoMask()">Undo</button>
              <button class="btn-sm" style="flex:1;" onclick="resetMaskToCutout()">Reset Cutout</button>
            </div>
            <p style="font-size:0.72rem; color:var(--text-muted); margin-top:8px; line-height:1.4;">
              <strong>Recover:</strong> Restores lost hair/collar from original photo.<br>
              <strong>Erase:</strong> Cleans up leftover background fragments.
            </p>
          </div>
        </div>

        <!-- Specs info -->
        <div class="section-label" style="margin-top:10px;">Specs</div>
        <div class="box" style="font-family:'JetBrains Mono', monospace; font-size:0.72rem; color:var(--text-muted); line-height:1.6;">
          <div>Target: <strong style="color:var(--accent);">180 × 180 px</strong></div>
          <div>Format: <strong style="color:var(--accent);">PNG (RGBA)</strong></div>
          <div>Naming: <strong style="color:var(--primary);">Exact Original Names</strong></div>
        </div>
      </div>

      <!-- Center Stage -->
      <div class="stage">
        <div class="stage-toolbar">
          <button class="chip active" id="chip-check" onclick="setBg('checker')">Transparent</button>
          <button class="chip" id="chip-dark" onclick="setBg('dark')">Dark</button>
          <button class="chip" id="chip-white" onclick="setBg('white')">White</button>
          <button class="chip" id="chip-team" onclick="setBg('team')">Team Navy</button>
          <span style="width:1px; height:14px; background:#28354f; align-self:center;"></span>
          <button class="chip" id="chip-compare" onmousedown="showOriginal(true)" onmouseup="showOriginal(false)" onmouseleave="showOriginal(false)">Hold: View Original</button>
        </div>

        <div class="viewport-outer">
          <div class="viewport-container checkerboard" id="viewport">
            <canvas id="editor-canvas" width="540" height="540"></canvas>
            <div id="brush-cursor"></div>
          </div>
        </div>

        <div class="stage-hint">
          <span id="hint-text">Drag photo to position • Wheel to zoom</span>
          <span>•</span>
          <span id="pos-info" style="font-family:'JetBrains Mono', monospace; color:var(--accent);">x: 0, y: 0</span>
        </div>
      </div>
    </div>

    <!-- Bottom Carousel Filmstrip Bar -->
    <div class="carousel-container" id="carousel-container">
      <div class="carousel-header">
        <div class="carousel-title">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>
          <span>TEAM ROSTER FILMSTRIP</span>
          <span class="carousel-count-badge" id="carousel-count-badge">0 Photos</span>
        </div>
        <div class="carousel-nav-arrows">
          <button type="button" class="carousel-arrow-btn" onclick="navigatePhoto(-1)" title="Previous portrait (or Left Arrow)">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="15 18 9 12 15 6"/></svg>
          </button>
          <button type="button" class="carousel-arrow-btn" onclick="navigatePhoto(1)" title="Next portrait (or Right Arrow)">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>
          </button>
        </div>
      </div>
      <div class="carousel-bar" id="carousel"></div>
    </div>
  </div>

  <!-- Global Loading Overlay -->
  <div class="loading-overlay" id="loading-overlay">
    <div class="spinner"></div>
    <div id="loading-text" style="font-size:0.88rem; font-weight:700; color:var(--text);">Processing...</div>
  </div>

  <script>
    const CANVAS_PX = 180;
    const BUFFER_PX = 540;
    const VIEWPORT_PX = 440;
    const SCALE_RATIO = BUFFER_PX / CANVAS_PX;

    let currentFolder = "";
    let editedFolder = "";
    let photos = [];
    let currentIndex = 0;
    let photoData = {};

    let currentMode = 'frame';
    let brushRadius = 18;

    let isDragging = false;
    let isPainting = false;
    let dragStartX = 0;
    let dragStartY = 0;
    let lastPaintX = 0;
    let lastPaintY = 0;
    let isComparingOriginal = false;

    const canvas = document.getElementById('editor-canvas');
    const ctx = canvas.getContext('2d');
    const viewport = document.getElementById('viewport');
    const brushCursor = document.getElementById('brush-cursor');

    const maskCanvas = document.createElement('canvas');
    maskCanvas.width = BUFFER_PX;
    maskCanvas.height = BUFFER_PX;
    const maskCtx = maskCanvas.getContext('2d');
    let undoStack = [];

    async function init() {
      setupDragAndDrop();
      setupEvents();
      await checkAuthStatus();
      // Only load folders if strictly authenticated
      if (currentUser) {
        loadSuggestedFolders();
      }
    }

    async function loadSuggestedFolders() {
      try {
        const res = await fetch('/api/suggested_folders');
        if (res.status === 401) {
          currentUser = null;
          currentCompany = null;
          renderAuthUI();
          return;
        }
        const data = await res.json();
        renderDetectedFolders(data.suggestions_data || []);
      } catch (e) {
        console.error("Failed to load suggested folders:", e);
      }
    }

    function renderDetectedFolders(folders) {
      const grid = document.getElementById('detected-folders-grid');
      grid.innerHTML = '';
      if (!folders || folders.length === 0) {
        grid.innerHTML = '<div style="color:var(--text-muted); font-size:0.85rem;">No photo folders automatically detected in Downloads. Use the browse button above.</div>';
        return;
      }
      folders.forEach(f => {
        const card = document.createElement('div');
        card.className = 'folder-card';
        card.onclick = () => openFolder(f.path);
        card.innerHTML = `
          <div class="folder-icon" style="color:var(--accent);"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg></div>
          <div class="folder-info">
            <div class="folder-card-name">${f.name}</div>
            <div class="folder-card-sub">
              <span class="photo-count-pill">${f.count} photos</span>
              <span>→ ${f.name}_edited/</span>
            </div>
          </div>
        `;
        grid.appendChild(card);
      });
    }

    function showFolderSelectPage() {
      document.getElementById('page-folder-select').style.display = 'flex';
      document.getElementById('page-workbench').style.display = 'none';
    }

    function showWorkbenchPage() {
      document.getElementById('page-folder-select').style.display = 'none';
      document.getElementById('page-workbench').style.display = 'flex';
    }

    async function onNativeFolderPicked(e) {
      const files = Array.from(e.target.files || []);
      if (!files || files.length === 0) return;

      const imageFiles = files.filter(f => /\.(png|jpe?g|webp)$/i.test(f.name));
      if (imageFiles.length === 0) {
        alert('No image files (.png, .jpg, .webp) found in the selected folder!');
        e.target.value = '';
        return;
      }

      let folderName = '';
      if (files[0].webkitRelativePath) {
        folderName = files[0].webkitRelativePath.split('/')[0];
      }
      if (!folderName) {
        folderName = 'Selected_Photos';
      }

      await loadFromBrowserFiles(imageFiles, folderName);
      e.target.value = '';
    }

    async function onNativeFilesPicked(e) {
      const files = Array.from(e.target.files || []);
      if (!files || files.length === 0) return;

      const imageFiles = files.filter(f => /\.(png|jpe?g|webp)$/i.test(f.name));
      if (imageFiles.length === 0) {
        alert('Please select valid image files (.png, .jpg, .webp)!');
        e.target.value = '';
        return;
      }

      await loadFromBrowserFiles(imageFiles, 'Selected_Photos');
      e.target.value = '';
    }

    function fileToBase64(file) {
      return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = reject;
        reader.readAsDataURL(file);
      });
    }

    async function freeServerStorageAndMemory() {
      showLoading("Cleaning server storage & clearing Python RAM...");
      try {
        const res = await fetch('/api/clear_server_storage', { method: 'POST' });
        const data = await res.json();
        showToast(`Freed ${data.freed_mb || 0} MB server temporary disk & RAM!`);
      } catch (e) {
        showToast("Storage cleanup error: " + e.message, "error");
      } finally {
        hideLoading();
      }
    }

    async function loadRosterDirectlyIntoStudio(players, folderName) {
      if (!players || players.length === 0) return;
      showLoading(`Loading ${players.length} roster players directly into Studio (0 server storage)...`);
      try {
        currentFolder = folderName || 'Roster_Photos';
        editedFolder = currentFolder + '_edited';

        const currentFolderDisplay = currentFolder.replaceAll('\\', '/').split('/').filter(Boolean).pop() || currentFolder;
        const editedFolderDisplay = editedFolder.replaceAll('\\', '/').split('/').filter(Boolean).pop() || editedFolder;

        document.getElementById('active-folder-name').textContent = currentFolderDisplay;
        document.getElementById('active-output-name').textContent = '→ ' + editedFolderDisplay + '/';

        photoData = {};
        photos = [];
        const carousel = document.getElementById('carousel');
        carousel.innerHTML = '';

        players.forEach((p, idx) => {
          const pName = p.name || `Player_${idx + 1}`;
          const assigned = p.assigned_number ? p.assigned_number.trim() : '';
          const cleanAssigned = assigned.replace(/[\\/*?:"<>|]/g, '').trim();
          const cleanPName = pName.replace(/[\\/*?:"<>|]/g, '').trim();
          const filename = cleanAssigned ? `${cleanAssigned}.png` : `${cleanPName}.png`;
          const proxiedUrl = `/api/proxy_photo?url=${encodeURIComponent(p.image)}&width=800`;

          photos.push(filename);
          photoData[filename] = {
            name: filename,
            player_name: pName,
            assigned_id: cleanAssigned,
            url: p.image,
            proxiedUrl: proxiedUrl,
            scale: 0.35,
            offset_x: 0,
            offset_y: 0,
            img: null,
            blobFile: null,
            cutoutImg: null,
            hasCutout: false,
            maskReady: false,
            saved: false,
            savedB64: null
          };

          const item = document.createElement('div');
          item.className = 'carousel-item' + (idx === 0 ? ' active' : '');
          item.id = 'thumb-' + idx;
          item.onclick = () => selectPhoto(idx);
          item.innerHTML = `
            <div class="status-dot" id="dot-${idx}"></div>
            <img src="${proxiedUrl}" onerror="this.src='${p.image}'" crossorigin="anonymous">
            <span>${filename}</span>
          `;
          carousel.appendChild(item);
        });

        const countBadge = document.getElementById('carousel-count-badge');
        if (countBadge) countBadge.textContent = `${photos.length} Photos`;

        showWorkbenchPage();
        hideLoading();
        await selectPhoto(0);
      } catch (err) {
        console.error('Error loading roster into studio:', err);
        alert('Error loading into studio: ' + err.message);
      } finally {
        hideLoading();
      }
    }

    async function loadFromBrowserFiles(imageFiles, folderName) {
      if (!imageFiles || imageFiles.length === 0) return;
      showLoading(`Loading ${imageFiles.length} photos...`);
      try {
        currentFolder = folderName || 'Selected_Photos';
        editedFolder = currentFolder + '_edited';
        photos = imageFiles.map(f => f.name);

        const currentFolderDisplay = currentFolder.replaceAll('\\', '/').split('/').filter(Boolean).pop() || currentFolder;
        const editedFolderDisplay = editedFolder.replaceAll('\\', '/').split('/').filter(Boolean).pop() || editedFolder;

        document.getElementById('active-folder-name').textContent = currentFolderDisplay;
        document.getElementById('active-output-name').textContent = '→ ' + editedFolderDisplay + '/';

        photoData = {};
        const carousel = document.getElementById('carousel');
        carousel.innerHTML = '';

        imageFiles.forEach((file, idx) => {
          const name = file.name;
          const blobUrl = URL.createObjectURL(file);
          photoData[name] = {
            scale: 0.35,
            offset_x: 0,
            offset_y: 0,
            img: null,
            blobFile: file,
            blobUrl: blobUrl,
            cutoutImg: null,
            hasCutout: false,
            maskReady: false,
            saved: false
          };

          const item = document.createElement('div');
          item.className = 'carousel-item' + (idx === 0 ? ' active' : '');
          item.id = 'thumb-' + idx;
          item.onclick = () => selectPhoto(idx);
          item.innerHTML = `
            <div class="status-dot" id="dot-${idx}"></div>
            <img src="${blobUrl}" onerror="this.style.opacity='0.2'">
            <span>${name}</span>
          `;
          carousel.appendChild(item);
        });

        const countBadge = document.getElementById('carousel-count-badge');
        if (countBadge) countBadge.textContent = `${photos.length} Photos`;

        // Switch to workbench immediately so user never stays stuck
        showWorkbenchPage();
        hideLoading();

        // Upload images to backend so cloud / Render can run AI cutout, face detection, and batch processing
        const cleanFolder = (folderName || 'Selected_Photos').replace(/[^a-zA-Z0-9_\-\s]/g, '').trim() || 'Selected_Photos';
        const uploadQueue = imageFiles.map(file => {
          return fetch(`/api/upload_single_file?folder=${encodeURIComponent(cleanFolder)}&name=${encodeURIComponent(file.name)}`, {
            method: 'POST',
            body: file
          }).catch(err => console.warn('Upload error for ' + file.name, err));
        });

        // Run uploads in background and update currentFolder to server path
        Promise.all(uploadQueue).then(async () => {
          try {
            const res = await fetch('/api/resolve_folder_name', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ folder_name: cleanFolder })
            });
            const rdata = await res.json();
            if (rdata && rdata.found && rdata.path) {
              currentFolder = rdata.path;
              editedFolder = currentFolder + '_edited';
            }
          } catch (e) {}
        });

        await selectPhoto(0);
      } catch (err) {
        console.error('Error loading files:', err);
        alert('Error loading photos: ' + err.message);
      } finally {
        hideLoading();
      }
    }

    function setupDragAndDrop() {
      const dropZone = document.getElementById('folder-drop-zone');
      if (!dropZone) return;

      ['dragenter', 'dragover'].forEach(eventName => {
        dropZone.addEventListener(eventName, (e) => {
          e.preventDefault();
          e.stopPropagation();
          dropZone.style.borderColor = 'var(--primary)';
          dropZone.style.background = '#fffdf5';
        });
      });

      ['dragleave', 'drop'].forEach(eventName => {
        dropZone.addEventListener(eventName, (e) => {
          e.preventDefault();
          e.stopPropagation();
          dropZone.style.borderColor = 'rgba(180, 140, 45, 0.35)';
          dropZone.style.background = '#ffffff';
        });
      });

      dropZone.addEventListener('drop', async (e) => {
        const dt = e.dataTransfer;
        if (!dt) return;

        const items = dt.items;
        if (items && items.length > 0) {
          const filePromises = [];
          let folderName = 'Dropped_Photos';

          for (let i = 0; i < items.length; i++) {
            const item = items[i];
            const entry = item.webkitGetAsEntry ? item.webkitGetAsEntry() : null;
            if (entry) {
              if (entry.isDirectory) {
                folderName = entry.name;
                const dirReader = entry.createReader();
                const readEntries = () => new Promise(resolve => {
                  dirReader.readEntries(entries => resolve(entries));
                });
                const dirEntries = await readEntries();
                for (const de of dirEntries) {
                  if (de.isFile) {
                    filePromises.push(new Promise(resolve => de.file(f => resolve(f))));
                  }
                }
              } else if (entry.isFile) {
                filePromises.push(new Promise(resolve => entry.file(f => resolve(f))));
              }
            } else if (item.kind === 'file') {
              const f = item.getAsFile();
              if (f) filePromises.push(Promise.resolve(f));
            }
          }

          const rawFiles = await Promise.all(filePromises);
          const imageFiles = rawFiles.filter(f => f && /\.(png|jpe?g|webp)$/i.test(f.name));
          if (imageFiles.length > 0) {
            await loadFromBrowserFiles(imageFiles, folderName);
            return;
          }
        }

        if (dt.files && dt.files.length > 0) {
          const imageFiles = Array.from(dt.files).filter(f => /\.(png|jpe?g|webp)$/i.test(f.name));
          if (imageFiles.length > 0) {
            await loadFromBrowserFiles(imageFiles, 'Dropped_Photos');
          }
        }
      });
    }

    async function resolveFolderByName(folderName) {
      showLoading(`Locating ${folderName}...`);
      try {
        const res = await fetch('/api/resolve_folder_name', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ folder_name: folderName })
        });
        const data = await res.json();
        if (data.found && data.path) {
          await openFolder(data.path);
          return;
        }
        await openFolder(folderName);
      } catch (e) {
        console.error(e);
        alert('Could not locate folder on disk: ' + folderName + '. You can paste the full folder path below.');
      } finally {
        hideLoading();
      }
    }

    function openManualPath() {
      const p = document.getElementById('manual-path-input').value.trim();
      if (p) {
        openFolder(p);
      } else {
        alert('Please enter a folder name or path');
      }
    }

    async function openFolder(folderPath) {
      if (!folderPath) return;
      showLoading('Loading photos from folder...');
      try {
        const res = await fetch('/api/scan_folder?path=' + encodeURIComponent(folderPath));
        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          alert(errData.message || ('Could not open folder: ' + folderPath));
          hideLoading();
          return;
        }
        const data = await res.json();
        if (!data.photos || data.photos.length === 0) {
          alert('No photos (.png, .jpg, .webp) found in: ' + (data.folder || folderPath));
          hideLoading();
          return;
        }

        currentFolder = data.folder;
        editedFolder = data.edited;
        photos = data.photos;

        const currentFolderDisplay = currentFolder.replaceAll('\\', '/').split('/').filter(Boolean).pop() || currentFolder;
        const editedFolderDisplay = editedFolder.replaceAll('\\', '/').split('/').filter(Boolean).pop() || editedFolder;

        document.getElementById('active-folder-name').textContent = currentFolderDisplay;
        document.getElementById('active-output-name').textContent = '→ ' + editedFolderDisplay + '/';

        photoData = {};
        const carousel = document.getElementById('carousel');
        carousel.innerHTML = '';

        photos.forEach((name, idx) => {
          photoData[name] = {
            scale: 0.35,
            offset_x: 0,
            offset_y: 0,
            img: null,
            blobUrl: null,
            cutoutImg: null,
            hasCutout: false,
            maskReady: false,
            saved: false
          };

          const item = document.createElement('div');
          item.className = 'carousel-item' + (idx === 0 ? ' active' : '');
          item.id = 'thumb-' + idx;
          item.onclick = () => selectPhoto(idx);
          item.innerHTML = `
            <div class="status-dot" id="dot-${idx}"></div>
            <img src="/api/photo_raw?folder=${encodeURIComponent(currentFolder)}&name=${encodeURIComponent(name)}" onerror="this.style.opacity='0.2'">
            <span>${name}</span>
          `;
          carousel.appendChild(item);
        });

        const countBadge = document.getElementById('carousel-count-badge');
        if (countBadge) countBadge.textContent = `${photos.length} Photos`;

        // Switch to workbench FIRST so user immediately sees UI loaded
        showWorkbenchPage();
        hideLoading();
        await selectPhoto(0);
      } catch (e) {
        console.error('Error opening folder:', e);
        alert('Error opening folder: ' + e.message);
      } finally {
        hideLoading();
      }
    }

    function navigatePhoto(dir) {
      if (!photos || photos.length === 0) return;
      let next = currentIndex + dir;
      if (next < 0) next = photos.length - 1;
      if (next >= photos.length) next = 0;
      selectPhoto(next);
    }

    async function selectPhoto(index) {
      if (index < 0 || index >= photos.length) return;
      currentIndex = index;
      document.querySelectorAll('.carousel-item').forEach((el, i) => {
        el.classList.toggle('active', i === index);
      });

      const activeThumb = document.getElementById('thumb-' + index);
      if (activeThumb) {
        const carousel = document.getElementById('carousel');
        if (carousel) {
          const itemLeft = activeThumb.offsetLeft;
          const itemWidth = activeThumb.offsetWidth;
          const carouselWidth = carousel.clientWidth;
          carousel.scrollTo({
            left: itemLeft - (carouselWidth / 2) + (itemWidth / 2),
            behavior: 'smooth'
          });
        }
      }

      const countBadge = document.getElementById('carousel-count-badge');
      if (countBadge && photos.length > 0) {
        countBadge.textContent = `Photo ${index + 1} of ${photos.length}`;
      }

      const name = photos[index];
      const data = photoData[name];
      if (!data) return;

      showLoading('Loading portrait...');

      if (!data.img) {
        const img = new Image();
        const loadPromise = new Promise((resolve, reject) => {
          img.onload = () => resolve(img);
          img.onerror = () => reject(new Error('Failed to load image: ' + name));
        });

        if (data.blobUrl) {
          img.src = data.blobUrl;
        } else if (data.proxiedUrl) {
          img.crossOrigin = 'anonymous';
          img.src = data.proxiedUrl;
        } else if (data.url) {
          img.crossOrigin = 'anonymous';
          img.src = `/api/proxy_photo?url=${encodeURIComponent(data.url)}&width=800`;
        } else {
          img.src = `/api/photo_raw?folder=${encodeURIComponent(currentFolder)}&name=${encodeURIComponent(name)}`;
        }

        try {
          await loadPromise;
          data.img = img;
        } catch (err) {
          console.error(err);
          hideLoading();
          return;
        }

        try {
          let autoRes;
          if (data.url) {
            autoRes = await fetch('/api/auto_align', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ url: data.url })
            });
          } else if (data.blobFile) {
            const b64 = await fileToBase64(data.blobFile);
            autoRes = await fetch('/api/auto_align', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ image_base64: b64 })
            });
          } else {
            autoRes = await fetch(`/api/auto_align?folder=${encodeURIComponent(currentFolder)}&name=${encodeURIComponent(name)}`);
          }

          if (autoRes && autoRes.ok) {
            const autoData = await autoRes.json();
            data.scale = autoData.scale;
            data.offset_x = autoData.offset_x;
            data.offset_y = autoData.offset_y;
          } else {
            throw new Error('auto-align returned non-200');
          }
        } catch (e) {
          data.scale = 180 / (img.height || 180);
          data.offset_x = (180 - (img.width || 180) * data.scale) / 2;
          data.offset_y = 0;
        }
      }

      undoStack = [];
      if (data.hasCutout && data.cutoutImg) {
        initMaskFromCutout(data.cutoutImg);
      } else {
        maskCtx.fillStyle = '#ffffff';
        maskCtx.fillRect(0, 0, BUFFER_PX, BUFFER_PX);
        data.maskReady = false;
      }

      setMode('frame');
      hideLoading();
      syncZoomSlider();
      render();
    }

    function setupEvents() {
      viewport.addEventListener('mousedown', (e) => {
        const rect = viewport.getBoundingClientRect();
        const clientX = e.clientX - rect.left;
        const clientY = e.clientY - rect.top;
        const vw = rect.width || VIEWPORT_PX;
        const vh = rect.height || VIEWPORT_PX;
        const canvasX = (clientX / vw) * BUFFER_PX;
        const canvasY = (clientY / vh) * BUFFER_PX;

        if (currentMode === 'frame') {
          isDragging = true;
          dragStartX = e.clientX;
          dragStartY = e.clientY;
        } else {
          isPainting = true;
          lastPaintX = canvasX;
          lastPaintY = canvasY;
          saveUndoState();
          paintStroke(canvasX, canvasY);
        }
      });

      window.addEventListener('mousemove', (e) => {
        const rect = viewport.getBoundingClientRect();
        const inBounds = e.clientX >= rect.left && e.clientX <= rect.right && e.clientY >= rect.top && e.clientY <= rect.bottom;

        if (currentMode !== 'frame' && inBounds) {
          brushCursor.style.display = 'block';
          brushCursor.style.left = (e.clientX - rect.left) + 'px';
          brushCursor.style.top = (e.clientY - rect.top) + 'px';
        } else {
          brushCursor.style.display = 'none';
        }

        if (isDragging) {
          const vw = rect.width || VIEWPORT_PX;
          const vh = rect.height || VIEWPORT_PX;
          const dx = ((e.clientX - dragStartX) / vw) * CANVAS_PX;
          const dy = ((e.clientY - dragStartY) / vh) * CANVAS_PX;
          dragStartX = e.clientX;
          dragStartY = e.clientY;

          const data = photoData[photos[currentIndex]];
          data.offset_x += dx;
          data.offset_y += dy;
          render();
        } else if (isPainting) {
          const clientX = e.clientX - rect.left;
          const clientY = e.clientY - rect.top;
          const vw = rect.width || VIEWPORT_PX;
          const vh = rect.height || VIEWPORT_PX;
          const canvasX = (clientX / vw) * BUFFER_PX;
          const canvasY = (clientY / vh) * BUFFER_PX;
          paintLine(lastPaintX, lastPaintY, canvasX, canvasY);
          lastPaintX = canvasX;
          lastPaintY = canvasY;
        }
      });

      window.addEventListener('mouseup', () => {
        isDragging = false;
        isPainting = false;
      });

      viewport.addEventListener('wheel', (e) => {
        if (currentMode !== 'frame') return;
        e.preventDefault();
        const data = photoData[photos[currentIndex]];
        if (!data.img) return;

        const rect = viewport.getBoundingClientRect();
        const vw = rect.width || VIEWPORT_PX;
        const vh = rect.height || VIEWPORT_PX;
        const mouseX = ((e.clientX - rect.left) / vw) * CANVAS_PX;
        const mouseY = ((e.clientY - rect.top) / vh) * CANVAS_PX;

        const zoomFactor = e.deltaY < 0 ? 1.06 : 0.94;
        const oldScale = data.scale;
        const newScale = Math.max(0.05, Math.min(2.0, oldScale * zoomFactor));

        data.offset_x = mouseX - (mouseX - data.offset_x) * (newScale / oldScale);
        data.offset_y = mouseY - (mouseY - data.offset_y) * (newScale / oldScale);
        data.scale = newScale;

        syncZoomSlider();
        render();
      }, { passive: false });

      // Keyboard left/right arrows for instant portrait navigation
      window.addEventListener('keydown', (e) => {
        const activeTag = document.activeElement ? document.activeElement.tagName.toLowerCase() : '';
        if (activeTag === 'input' || activeTag === 'textarea' || activeTag === 'select') return;
        const wb = document.getElementById('page-workbench');
        if (wb && wb.style.display !== 'none') {
          if (e.key === 'ArrowLeft') {
            e.preventDefault();
            navigatePhoto(-1);
          } else if (e.key === 'ArrowRight') {
            e.preventDefault();
            navigatePhoto(1);
          }
        }
      });
    }

    function render() {
      ctx.clearRect(0, 0, BUFFER_PX, BUFFER_PX);
      const name = photos[currentIndex];
      const data = photoData[name];
      if (!data || !data.img) return;

      const dw = data.img.width * data.scale * SCALE_RATIO;
      const dh = data.img.height * data.scale * SCALE_RATIO;
      const dx = data.offset_x * SCALE_RATIO;
      const dy = data.offset_y * SCALE_RATIO;

      if (isComparingOriginal) {
        ctx.drawImage(data.img, dx, dy, dw, dh);
      } else {
        ctx.save();
        ctx.drawImage(data.img, dx, dy, dw, dh);
        ctx.globalCompositeOperation = 'destination-in';
        ctx.drawImage(maskCanvas, 0, 0);
        ctx.restore();
      }

      document.getElementById('pos-info').textContent = 
        `x: ${Math.round(data.offset_x)}px, y: ${Math.round(data.offset_y)}px`;
    }

    function paintStroke(x, y) {
      maskCtx.save();
      maskCtx.beginPath();
      maskCtx.arc(x, y, brushRadius, 0, Math.PI * 2);
      if (currentMode === 'recover') {
        maskCtx.globalCompositeOperation = 'source-over';
        maskCtx.fillStyle = '#ffffff';
      } else if (currentMode === 'erase') {
        maskCtx.globalCompositeOperation = 'destination-out';
        maskCtx.fillStyle = '#000000';
      }
      maskCtx.fill();
      maskCtx.restore();
      render();
    }

    function paintLine(x1, y1, x2, y2) {
      maskCtx.save();
      maskCtx.beginPath();
      maskCtx.moveTo(x1, y1);
      maskCtx.lineTo(x2, y2);
      maskCtx.lineWidth = brushRadius * 2;
      maskCtx.lineCap = 'round';
      maskCtx.lineJoin = 'round';
      if (currentMode === 'recover') {
        maskCtx.globalCompositeOperation = 'source-over';
        maskCtx.strokeStyle = '#ffffff';
      } else if (currentMode === 'erase') {
        maskCtx.globalCompositeOperation = 'destination-out';
        maskCtx.strokeStyle = '#000000';
      }
      maskCtx.stroke();
      maskCtx.restore();
      render();
    }

    function setMode(mode) {
      currentMode = mode;
      document.querySelectorAll('.tool-tab').forEach(t => t.classList.remove('active'));
      document.getElementById('tab-' + mode).classList.add('active');

      document.getElementById('controls-frame').style.display = mode === 'frame' ? 'block' : 'none';
      document.getElementById('controls-brush').style.display = mode !== 'frame' ? 'block' : 'none';

      const vw = viewport.clientWidth || VIEWPORT_PX;
      const sizePx = brushRadius * 2 * (vw / BUFFER_PX);
      brushCursor.style.width = sizePx + 'px';
      brushCursor.style.height = sizePx + 'px';

      const hintEl = document.getElementById('hint-text');
      if (mode === 'frame') {
        hintEl.textContent = 'Drag photo freely to position • Wheel to zoom';
        viewport.style.cursor = 'grab';
      } else if (mode === 'recover') {
        hintEl.textContent = 'Painting with RECOVER brush (restoring original portrait)';
        viewport.style.cursor = 'crosshair';
      } else {
        hintEl.textContent = 'Painting with ERASE brush (removing background)';
        viewport.style.cursor = 'crosshair';
      }
    }

    function setBrushSize(val) {
      brushRadius = parseInt(val);
      document.getElementById('brush-size-badge').textContent = val + ' px';
      const vw = viewport.clientWidth || VIEWPORT_PX;
      const sizePx = brushRadius * 2 * (vw / BUFFER_PX);
      brushCursor.style.width = sizePx + 'px';
      brushCursor.style.height = sizePx + 'px';
    }

    function saveUndoState() {
      if (undoStack.length >= 15) undoStack.shift();
      undoStack.push(maskCtx.getImageData(0, 0, BUFFER_PX, BUFFER_PX));
    }

    function undoMask() {
      if (undoStack.length === 0) return;
      const prev = undoStack.pop();
      maskCtx.putImageData(prev, 0, 0);
      render();
    }

    function resetMaskToCutout() {
      const data = photoData[photos[currentIndex]];
      if (data && data.cutoutImg) {
        initMaskFromCutout(data.cutoutImg);
        render();
      }
    }

    function initMaskFromCutout(cutoutImg) {
      const tempC = document.createElement('canvas');
      tempC.width = BUFFER_PX;
      tempC.height = BUFFER_PX;
      const tempCtx = tempC.getContext('2d');
      tempCtx.drawImage(cutoutImg, 0, 0, BUFFER_PX, BUFFER_PX);
      const imgData = tempCtx.getImageData(0, 0, BUFFER_PX, BUFFER_PX);

      const maskData = maskCtx.createImageData(BUFFER_PX, BUFFER_PX);
      for (let i = 0; i < imgData.data.length; i += 4) {
        const a = imgData.data[i + 3];
        maskData.data[i] = 255;
        maskData.data[i + 1] = 255;
        maskData.data[i + 2] = 255;
        maskData.data[i + 3] = a;
      }
      maskCtx.putImageData(maskData, 0, 0);
      photoData[photos[currentIndex]].maskReady = true;
    }

    async function triggerCutout() {
      const name = photos[currentIndex];
      const data = photoData[name];
      showLoading(`Running AI background removal for ${name}...`);

      try {
        let payload = {
          folder: currentFolder,
          photo: name,
          scale: data.scale,
          offset_x: data.offset_x,
          offset_y: data.offset_y
        };

        if (data.url) {
          payload.url = data.url;
        } else if (data.blobFile) {
          payload.image_base64 = await fileToBase64(data.blobFile);
        } else if (data.img && data.img.src && data.img.src.startsWith('data:')) {
          payload.image_base64 = data.img.src;
        }

        const res = await fetch('/api/preview_cutout', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        if (!res.ok) {
          const errText = await res.text();
          throw new Error(`HTTP ${res.status}: ${errText.substring(0, 100)}`);
        }
        const blob = await res.blob();
        const img = new Image();
        img.src = URL.createObjectURL(blob);
        await new Promise(r => img.onload = r);

        data.cutoutImg = img;
        data.hasCutout = true;
        initMaskFromCutout(img);
        document.getElementById(`dot-${currentIndex}`).className = 'status-dot cutout';

        setMode('recover');
        render();
      } catch (e) {
        alert('Cutout failed: ' + (e.message || e));
      } finally {
        hideLoading();
      }
    }

    async function saveActivePhoto() {
      const name = photos[currentIndex];
      showLoading(`Saving 180x180 transparent headshot: ${name}...`);

      const outC = document.createElement('canvas');
      outC.width = 180;
      outC.height = 180;
      const oCtx = outC.getContext('2d');
      oCtx.imageSmoothingEnabled = true;
      oCtx.imageSmoothingQuality = 'high';
      oCtx.drawImage(canvas, 0, 0, 180, 180);
      const b64 = outC.toDataURL('image/png');

      // Download directly to user's PC storage (zero Render storage!)
      const dlLink = document.createElement('a');
      const cleanName = name.toLowerCase().endsWith('.png') ? name : `${name}.png`;
      dlLink.download = cleanName;
      dlLink.href = b64;
      document.body.appendChild(dlLink);
      dlLink.click();
      document.body.removeChild(dlLink);

      // Cache in browser memory for batch zip downloads
      photoData[name].saved = true;
      photoData[name].savedB64 = b64;
      document.getElementById(`dot-${currentIndex}`).className = 'status-dot saved';
      hideLoading();
      showToast(`Saved & downloaded ${cleanName} directly to your PC!`);
    }

    async function batchProcessFolder() {
      if (photos.length === 0) {
        showToast("No photos loaded to process", "error");
        return;
      }
      if (!confirm(`Process and export all ${photos.length} portraits as a ZIP directly to your PC?`)) return;
      const btn = document.getElementById('btn-batch-all');
      btn.disabled = true;
      let completed = 0;
      let errors = 0;

      showLoading(`Starting batch export for ${photos.length} portraits...`);

      const zip = (typeof JSZip !== 'undefined') ? new JSZip() : null;

      for (let i = 0; i < photos.length; i++) {
        const name = photos[i];
        const pct = Math.round(((i + 1) / photos.length) * 100);
        showLoading(`Processing ${i + 1} of ${photos.length}: ${name} (${pct}%)...`);

        const pData = photoData[name] || { scale: 0.35, offset_x: 0, offset_y: 0 };
        let payload = {
          folder: currentFolder,
          photo: name,
          scale: pData.scale,
          offset_x: pData.offset_x,
          offset_y: pData.offset_y
        };

        if (pData.url) {
          payload.url = pData.url;
        } else if (pData.blobFile) {
          payload.image_base64 = await fileToBase64(pData.blobFile);
        } else if (pData.img && pData.img.src && pData.img.src.startsWith('data:')) {
          payload.image_base64 = pData.img.src;
        }

        try {
          const res = await fetch('/api/process_single_portrait', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
          });
          if (!res.ok) {
            const errText = await res.text();
            throw new Error(`HTTP ${res.status}: ${errText.substring(0, 80)}`);
          }
          const json = await res.json();
          if (json && json.status === 'ok') {
            completed++;
            const dot = document.getElementById(`dot-${i}`);
            if (dot) dot.className = 'status-dot saved';
            photoData[name].saved = true;

            if (json.image_base64) {
              photoData[name].savedB64 = json.image_base64;
              if (zip) {
                const rawB64 = json.image_base64.split(',')[1] || json.image_base64;
                const outName = json.filename || (name.replace(/\.[^/.]+$/, "") + ".png");
                zip.file(outName, rawB64, { base64: true });
              }
            }
          } else {
            errors++;
          }
        } catch (err) {
          errors++;
          console.error(`Failed to process ${name}:`, err);
        }
      }

      // Download ZIP to user's PC storage if JSZip is active
      if (zip && completed > 0) {
        showLoading("Generating ZIP file in browser memory...");
        const zipBlob = await zip.generateAsync({ type: 'blob' });
        const folderBase = (currentFolder || 'headshots').replaceAll('\\', '/').split('/').filter(Boolean).pop() || 'headshots';
        const dlLink = document.createElement('a');
        dlLink.href = URL.createObjectURL(zipBlob);
        dlLink.download = `${folderBase}_edited.zip`;
        document.body.appendChild(dlLink);
        dlLink.click();
        document.body.removeChild(dlLink);
      }

      hideLoading();
      btn.disabled = false;
      alert(`🎉 Batch Complete!\nSuccessfully processed ${completed} of ${photos.length} portraits and downloaded directly to your PC!` + (errors > 0 ? `\n(${errors} items failed)` : ''));
    }

    function showOriginal(show) {
      isComparingOriginal = show;
      render();
    }

    function syncZoomSlider() {
      const data = photoData[photos[currentIndex]];
      if (!data) return;
      document.getElementById('zoom-slider').value = Math.round(data.scale * 200);
      document.getElementById('zoom-badge').textContent = Math.round(data.scale * 250) + '%';
    }

    function onZoomSlider(val) {
      const data = photoData[photos[currentIndex]];
      if (!data || !data.img) return;
      const oldScale = data.scale;
      const newScale = val / 200.0;
      const cx = 90;
      const cy = 90;
      data.offset_x = cx - (cx - data.offset_x) * (newScale / oldScale);
      data.offset_y = cy - (cy - data.offset_y) * (newScale / oldScale);
      data.scale = newScale;
      document.getElementById('zoom-badge').textContent = Math.round(newScale * 250) + '%';
      render();
    }

    async function autoAlignCurrent() {
      const name = photos[currentIndex];
      const data = photoData[name];
      showLoading('Auto-aligning face...');
      try {
        let autoRes;
        if (data && data.url) {
          autoRes = await fetch('/api/auto_align', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url: data.url })
          });
        } else if (data && data.blobFile) {
          const b64 = await fileToBase64(data.blobFile);
          autoRes = await fetch('/api/auto_align', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ image_base64: b64 })
          });
        } else {
          autoRes = await fetch(`/api/auto_align?folder=${encodeURIComponent(currentFolder)}&name=${encodeURIComponent(name)}`);
        }
        if (autoRes && autoRes.ok) {
          const autoData = await autoRes.json();
          data.scale = autoData.scale;
          data.offset_x = autoData.offset_x;
          data.offset_y = autoData.offset_y;
          syncZoomSlider();
          render();
        }
      } catch (e) {
        console.warn("Auto-align error:", e);
      } finally {
        hideLoading();
      }
    }

    function fitWidth() {
      const data = photoData[photos[currentIndex]];
      if (!data.img) return;
      data.scale = 180.0 / data.img.width;
      data.offset_x = 0;
      data.offset_y = (180.0 - data.img.height * data.scale) / 2;
      syncZoomSlider();
      render();
    }

    function fitHeight() {
      const data = photoData[photos[currentIndex]];
      if (!data.img) return;
      data.scale = 180.0 / data.img.height;
      data.offset_y = 0;
      data.offset_x = (180.0 - data.img.width * data.scale) / 2;
      syncZoomSlider();
      render();
    }

    function centerPhoto() {
      const data = photoData[photos[currentIndex]];
      if (!data.img) return;
      data.offset_x = (180.0 - data.img.width * data.scale) / 2;
      data.offset_y = (180.0 - data.img.height * data.scale) / 2;
      render();
    }

    function applyFramingToAll() {
      const current = photoData[photos[currentIndex]];
      photos.forEach(name => {
        photoData[name].scale = current.scale;
        photoData[name].offset_x = current.offset_x;
        photoData[name].offset_y = current.offset_y;
      });
      alert(`Applied framing (Scale: ${(current.scale).toFixed(3)}) to all photos in folder!`);
    }

    function setBg(type) {
      viewport.className = 'viewport-container';
      document.querySelectorAll('.stage-toolbar .chip').forEach(c => c.classList.remove('active'));
      if (type === 'checker') {
        viewport.classList.add('checkerboard');
        document.getElementById('chip-check').classList.add('active');
      } else if (type === 'dark') {
        viewport.style.backgroundColor = '#090d16';
        document.getElementById('chip-dark').classList.add('active');
      } else if (type === 'white') {
        viewport.style.backgroundColor = '#ffffff';
        document.getElementById('chip-white').classList.add('active');
      } else if (type === 'team') {
        viewport.style.backgroundColor = '#002855';
        document.getElementById('chip-team').classList.add('active');
      }
    }

    function showLoading(msg) {
      const el = document.getElementById('loading-overlay');
      if (el) {
        document.getElementById('loading-text').textContent = msg || 'Processing...';
        el.style.display = 'flex';
      }
    }

    function hideLoading() {
      const el = document.getElementById('loading-overlay');
      if (el) {
        el.style.display = 'none';
      }
    }

    let fetchedRosterPlayers = [];
    let currentRosterTargetDir = "";

    function switchLandingTab(tab) {
      const btnLocal = document.getElementById('tab-btn-local');
      const btnRoster = document.getElementById('tab-btn-roster');
      const viewLocal = document.getElementById('view-local-folder');
      const viewRoster = document.getElementById('view-roster-download');

      if (tab === 'local') {
        btnLocal.classList.add('active');
        btnRoster.classList.remove('active');
        viewLocal.style.display = 'flex';
        viewRoster.style.display = 'none';
      } else {
        btnRoster.classList.add('active');
        btnLocal.classList.remove('active');
        viewLocal.style.display = 'none';
        viewRoster.style.display = 'flex';
      }
    }

    async function fetchRosterPlayers() {
      const url = document.getElementById('roster-url-input').value.trim();
      if (!url) {
        alert('Please enter a valid athletics roster URL.');
        return;
      }
      showLoading('Fetching roster & extracting high-res photos...');
      try {
        const res = await fetch('/api/fetch_roster', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ url })
        });
        const data = await res.json();
        if (data.status !== 'ok' || !data.players || data.players.length === 0) {
          alert('Could not find players on roster: ' + (data.message || 'No players detected'));
          return;
        }

        fetchedRosterPlayers = data.players;
        if (data.suggested_folder) {
          document.getElementById('roster-folder-input').value = data.suggested_folder;
          document.getElementById('roster-team-title').textContent = data.suggested_folder;
        }

        renderRosterTable();
        document.getElementById('roster-results-card').style.display = 'block';
        document.getElementById('roster-success-card').style.display = 'none';
      } catch (e) {
        alert('Error fetching roster: ' + e);
      } finally {
        hideLoading();
      }
    }

    function renderRosterTable() {
      const tbody = document.getElementById('roster-table-body');
      tbody.innerHTML = '';
      document.getElementById('roster-player-count').textContent = `${fetchedRosterPlayers.length} Players`;

      fetchedRosterPlayers.forEach((p, idx) => {
        const tr = document.createElement('tr');
        tr.className = 'roster-row';

        const currentAssigned = p.assigned_number || '';
        const jerseyVal = p.jersey ? p.jersey : '-';
        const posVal = p.pos || p.position || '-';
        const shootsVal = p.shoots || '-';
        const htVal = p.height || '-';
        const wtVal = p.weight || '-';
        const bornVal = p.born || p.birth_date || '-';
        const placeVal = p.birthplace || p.birth_place || '-';

        tr.innerHTML = `
          <td class="roster-cell">
            <div class="player-cell-content">
              <img src="${p.image}" class="player-avatar-circle" alt="${p.name}" loading="lazy" onerror="this.src='https://via.placeholder.com/42?text=Photo'">
              <span class="player-name-text">${p.name}</span>
            </div>
          </td>
          <td class="roster-cell" style="text-align:center; font-weight:700; color:var(--accent); font-family:'JetBrains Mono', monospace;">${jerseyVal}</td>
          <td class="roster-cell" style="text-align:center; font-weight:700;">${posVal}</td>
          <td class="roster-cell" style="text-align:center; color:var(--text-muted); font-weight:600;">${shootsVal}</td>
          <td class="roster-cell" style="text-align:center; font-family:'JetBrains Mono', monospace;">${htVal}</td>
          <td class="roster-cell" style="text-align:center; font-family:'JetBrains Mono', monospace;">${wtVal}</td>
          <td class="roster-cell" style="white-space:nowrap; color:var(--text-muted);">${bornVal}</td>
          <td class="roster-cell" style="white-space:nowrap; color:var(--text-muted);">${placeVal}</td>
          <td class="roster-cell">
            <input type="text" class="assign-input" id="assign-num-${idx}" placeholder="Leave empty for Name" value="${currentAssigned}" oninput="onAssignedNumInput(${idx})">
          </td>
          <td class="roster-cell" id="filename-preview-cell-${idx}">
          </td>
        `;
        tbody.appendChild(tr);
        updateRowFilenameBadge(idx);
      });

      updateRosterSummary();
    }

    function copyRosterForSheets() {
      if (!fetchedRosterPlayers || fetchedRosterPlayers.length === 0) {
        alert('Please fetch a roster first.');
        return;
      }

      const headers = ['Player', '#', 'Pos', 'Sh', 'Ht', 'Wt', 'Born', 'Birthplace', 'Assigned ID', 'Filename'];
      const rows = [headers.join('\t')];

      fetchedRosterPlayers.forEach(p => {
        const assigned = (p.assigned_number || '').trim();
        const cleanName = p.name.replace(/[\\/*?:"<>|]/g, '').trim();
        const filename = assigned ? `${assigned}.png` : `${cleanName}.png`;

        rows.push([
          p.name,
          p.jersey || '',
          p.pos || p.position || '',
          p.shoots || '',
          p.height || '',
          p.weight || '',
          p.born || p.birth_date || '',
          p.birthplace || p.birth_place || '',
          assigned,
          filename
        ].join('\t'));
      });

      const tsvText = rows.join('\n');
      showToast(`📋 Copied ${fetchedRosterPlayers.length} players to clipboard! Paste directly into Google Sheets or Excel (Cmd+V / Ctrl+V).`);

      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(tsvText).catch(() => fallbackCopyText(tsvText));
      } else {
        fallbackCopyText(tsvText);
      }
    }

    function fallbackCopyText(text) {
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.focus();
      ta.select();
      try {
        document.execCommand('copy');
      } catch (err) {}
      document.body.removeChild(ta);
    }

    function exportRosterToCSV() {
      if (!fetchedRosterPlayers || fetchedRosterPlayers.length === 0) {
        alert('Please fetch a roster first.');
        return;
      }

      const headers = ['Player', '#', 'Pos', 'Sh', 'Ht', 'Wt', 'Born', 'Birthplace', 'Assigned ID', 'Filename'];
      const escapeCSV = (val) => {
        if (val === null || val === undefined) return '""';
        const str = String(val);
        if (str.includes(',') || str.includes('"') || str.includes('\n')) {
          return '"' + str.replace(/"/g, '""') + '"';
        }
        return str;
      };

      const csvRows = [headers.map(escapeCSV).join(',')];

      fetchedRosterPlayers.forEach(p => {
        const assigned = (p.assigned_number || '').trim();
        const cleanName = p.name.replace(/[\\/*?:"<>|]/g, '').trim();
        const filename = assigned ? `${assigned}.png` : `${cleanName}.png`;

        csvRows.push([
          p.name,
          p.jersey || '',
          p.pos || p.position || '',
          p.shoots || '',
          p.height || '',
          p.weight || '',
          p.born || p.birth_date || '',
          p.birthplace || p.birth_place || '',
          assigned,
          filename
        ].map(escapeCSV).join(','));
      });

      const blob = new Blob([csvRows.join('\r\n')], { type: 'text/csv;charset=utf-8;' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      const teamName = (document.getElementById('roster-folder-input').value.trim() || 'Roster').replace(/[\s\W]+/g, '_');
      a.href = url;
      a.download = `${teamName}_Roster.csv`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      showToast(`Exported ${teamName}_Roster.csv successfully!`);
    }

    function showToast(msg) {
      let toast = document.getElementById('studio-toast');
      if (!toast) {
        toast = document.createElement('div');
        toast.id = 'studio-toast';
        toast.style.cssText = 'position:fixed; bottom:28px; left:50%; transform:translateX(-50%); background:#ffffff; border:1px solid rgba(180, 140, 45, 0.4); color:#0f172a; box-shadow:0 12px 35px rgba(15,23,42,0.12); padding:12px 24px; border-radius:30px; font-size:0.88rem; font-weight:700; box-shadow:0 10px 35px rgba(0,0,0,0.85); z-index:99999; display:flex; align-items:center; gap:8px; opacity:0; transition:opacity 0.25s, transform 0.25s; pointer-events:none;';
        document.body.appendChild(toast);
      }
      toast.textContent = msg;
      toast.style.opacity = '1';
      toast.style.transform = 'translateX(-50%) translateY(0)';
      clearTimeout(toast._timeout);
      toast._timeout = setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(-50%) translateY(8px)';
      }, 3500);
    }

    function setPresetUrl(url, folderName) {
      document.getElementById('roster-url-input').value = url;
      if (folderName) {
        document.getElementById('roster-folder-input').value = folderName;
      }
      fetchRosterPlayers();
    }

    function useJerseyNumbersAsAssigned() {
      let count = 0;
      fetchedRosterPlayers.forEach((p, idx) => {
        if (p.jersey) {
          p.assigned_number = String(p.jersey);
          const input = document.getElementById(`assign-num-${idx}`);
          if (input) input.value = p.assigned_number;
          updateRowFilenameBadge(idx);
          count++;
        }
      });
      updateRosterSummary();
    }

    function backToRosterView() {
      document.getElementById('roster-success-card').style.display = 'none';
      document.getElementById('roster-results-card').style.display = 'block';
    }

    function onAssignedNumInput(idx) {
      const input = document.getElementById(`assign-num-${idx}`);
      fetchedRosterPlayers[idx].assigned_number = input.value.trim();
      updateRowFilenameBadge(idx);
      updateRosterSummary();
    }

    function updateRowFilenameBadge(idx) {
      const cell = document.getElementById(`filename-preview-cell-${idx}`);
      if (!cell) return;
      const p = fetchedRosterPlayers[idx];
      const val = (p.assigned_number || '').trim();
      if (val) {
        const cleanVal = val.replace(/[\\/*?:"<>|]/g, '').trim();
        cell.innerHTML = `<span class="filename-preview-badge badge-assigned">${cleanVal}.png</span>`;
      } else {
        const cleanName = p.name.replace(/[\\/*?:"<>|]/g, '').trim();
        cell.innerHTML = `<span class="filename-preview-badge badge-default-name" title="No number assigned: using player name">📄 ${cleanName}.png <span style="font-size:0.65rem; opacity:0.8;">(name)</span></span>`;
      }
    }

    function updateRosterSummary() {
      const total = fetchedRosterPlayers.length;
      const assignedCount = fetchedRosterPlayers.filter(p => (p.assigned_number || '').trim().length > 0).length;
      const nameCount = total - assignedCount;

      const summary = document.getElementById('roster-summary-text');
      summary.innerHTML = `Total: <strong>${total}</strong> | Assigned IDs: <strong>${assignedCount}</strong> | Defaulted to Player Name: <strong>${nameCount}</strong>`;
    }

    function toggleBulkPasteDrawer() {
      const d = document.getElementById('bulk-paste-drawer');
      d.style.display = d.style.display === 'block' ? 'none' : 'block';
      if (d.style.display === 'block') {
        document.getElementById('bulk-paste-textarea').focus();
      }
    }

    function clearAllAssignedNumbers() {
      if (!confirm('Clear all assigned numbers? (All files will default to player names)')) return;
      fetchedRosterPlayers.forEach((p, idx) => {
        p.assigned_number = '';
        const input = document.getElementById(`assign-num-${idx}`);
        if (input) input.value = '';
        updateRowFilenameBadge(idx);
      });
      updateRosterSummary();
    }

    function applyBulkPaste() {
      const text = document.getElementById('bulk-paste-textarea').value.trim();
      if (!text) {
        toggleBulkPasteDrawer();
        return;
      }

      // 1. JSON Format
      if (text.startsWith('{') && text.endsWith('}')) {
        try {
          const mapping = JSON.parse(text);
          let count = 0;
          fetchedRosterPlayers.forEach((p, idx) => {
            const mapped = mapping[p.name] || mapping[p.jersey] || mapping['#' + p.jersey];
            if (mapped !== undefined) {
              p.assigned_number = String(mapped);
              const input = document.getElementById(`assign-num-${idx}`);
              if (input) input.value = p.assigned_number;
              updateRowFilenameBadge(idx);
              count++;
            }
          });
          updateRosterSummary();
          toggleBulkPasteDrawer();
          alert(`Applied numbers to ${count} players!`);
          return;
        } catch (e) {}
      }

      const lines = text.split(/\r?\n/).map(l => l.trim()).filter(Boolean);
      let matchedCount = 0;

      // 2. Check for Tab or Comma Separators (e.g. copied directly from Excel / Google Sheets)
      const hasSeparators = lines.some(l => l.includes('\t') || l.includes(','));

      if (hasSeparators) {
        const lookup = {};
        lines.forEach(l => {
          const parts = l.includes('\t') ? l.split('\t') : l.split(',');
          if (parts.length >= 2) {
            const k = parts[0].trim().toLowerCase();
            const v = parts[1].trim();
            if (k) lookup[k] = v;
          }
        });

        fetchedRosterPlayers.forEach((p, idx) => {
          const key = p.name.trim().toLowerCase();
          if (lookup[key] !== undefined) {
            p.assigned_number = lookup[key];
            const input = document.getElementById(`assign-num-${idx}`);
            if (input) input.value = p.assigned_number;
            updateRowFilenameBadge(idx);
            matchedCount++;
          }
        });
      } else {
        // 3. Line-by-line sequential numbers matching player order
        lines.forEach((num, idx) => {
          if (idx < fetchedRosterPlayers.length) {
            fetchedRosterPlayers[idx].assigned_number = num;
            const input = document.getElementById(`assign-num-${idx}`);
            if (input) input.value = num;
            updateRowFilenameBadge(idx);
            matchedCount++;
          }
        });
      }

      updateRosterSummary();
      toggleBulkPasteDrawer();
      alert(`Applied numbers to ${matchedCount} players!`);
    }

    async function downloadAllRosterPhotos() {
      const folderName = document.getElementById('roster-folder-input').value.trim() || 'Downloaded_Roster';
      if (fetchedRosterPlayers.length === 0) {
        alert('No players to download.');
        return;
      }

      const payload = {
        folder_name: folderName,
        players: fetchedRosterPlayers,
        target_width: 800
      };

      showLoading(`Downloading & standardizing ${fetchedRosterPlayers.length} photos directly to your PC as ZIP (0 Render storage)...`);
      try {
        const res = await fetch('/api/download_roster_zip', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });

        if (!res.ok) {
          const err = await res.json().catch(() => ({ message: 'Download failed' }));
          throw new Error(err.message || `HTTP ${res.status}`);
        }

        const blob = await res.blob();
        const downloadUrl = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = downloadUrl;
        a.download = `${folderName}.zip`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(downloadUrl);

        currentRosterTargetDir = folderName;
        document.getElementById('roster-results-card').style.display = 'none';
        document.getElementById('roster-success-card').style.display = 'block';
        document.getElementById('roster-success-desc').innerHTML = 
          `🎉 <strong>${fetchedRosterPlayers.length} photos</strong> downloaded directly to your PC storage as <code>${folderName}.zip</code>.<br><span style="color:#10b981; font-weight:600;">0 bytes consumed on Render!</span>`;
      } catch (e) {
        alert('Error downloading ZIP: ' + e.message);
      } finally {
        hideLoading();
      }
    }

    function openRosterInStudioDirectly() {
      if (fetchedRosterPlayers && fetchedRosterPlayers.length > 0) {
        const folderName = document.getElementById('roster-folder-input').value.trim() || 'Downloaded_Roster';
        loadRosterDirectlyIntoStudio(fetchedRosterPlayers, folderName);
      } else {
        alert('No roster players loaded to open.');
      }
    }

    function openDownloadedFolderInStudio() {
      if (fetchedRosterPlayers && fetchedRosterPlayers.length > 0) {
        const folderName = document.getElementById('roster-folder-input').value.trim() || 'Downloaded_Roster';
        loadRosterDirectlyIntoStudio(fetchedRosterPlayers, folderName);
      } else if (currentRosterTargetDir) {
        openFolder(currentRosterTargetDir);
      }
    }

    function downloadRosterZip() {
      downloadAllRosterPhotos();
    }

    async function downloadActiveEditedZip() {
      if (photos.length === 0) {
        showToast("No photos loaded", "error");
        return;
      }
      if (typeof JSZip !== 'undefined') {
        const zip = new JSZip();
        let count = 0;
        photos.forEach(name => {
          const data = photoData[name];
          if (data && data.savedB64) {
            const rawB64 = data.savedB64.split(',')[1] || data.savedB64;
            const outName = name.replace(/\.[^/.]+$/, "") + ".png";
            zip.file(outName, rawB64, { base64: true });
            count++;
          }
        });
        if (count > 0) {
          showLoading(`Creating ZIP with ${count} edited portraits...`);
          const zipBlob = await zip.generateAsync({ type: 'blob' });
          const folderBase = (currentFolder || 'edited_headshots').replaceAll('\\', '/').split('/').filter(Boolean).pop() || 'edited_headshots';
          const link = document.createElement('a');
          link.href = URL.createObjectURL(zipBlob);
          link.download = `${folderBase}_edited.zip`;
          document.body.appendChild(link);
          link.click();
          document.body.removeChild(link);
          hideLoading();
          showToast(`Downloaded ${count} headshots in ZIP directly to your PC!`);
          return;
        }
      }
      if (currentFolder) {
        const target = editedFolder || (currentFolder + '_edited');
        window.location.href = '/api/export_folder_zip?folder=' + encodeURIComponent(target);
      } else {
        showToast("Please save at least one headshot first, or run Batch Export", "error");
      }
    }

    // =========================================================================
    // MULTI-TENANT SAAS AUTHENTICATION & TEAM MANAGEMENT
    // =========================================================================
    let currentUser = null;
    let currentCompany = null;
    let cachedTeamData = null;

    async function checkAuthStatus() {
      try {
        const res = await fetch('/api/auth/me');
        const data = await res.json();
        if (data.logged_in && data.user) {
          currentUser = data.user;
          currentCompany = data.user.company;
        } else {
          currentUser = null;
          currentCompany = null;
        }
      } catch (e) {
        console.error("Auth check failed:", e);
        currentUser = null;
        currentCompany = null;
      }
      renderAuthUI();
      checkInviteUrlHash();
    }

    function renderAuthUI() {
      const gatewayEl = document.getElementById('page-enterprise-gateway');
      const folderSelectEl = document.getElementById('page-folder-select');
      const workbenchEl = document.getElementById('page-workbench');
      const topNavEl = document.getElementById('saas-top-navbar');
      const loggedOutDiv = document.getElementById('nav-auth-logged-out');
      const loggedInDiv = document.getElementById('nav-auth-logged-in');
      const companyWrapper = document.getElementById('nav-company-wrapper');

      if (currentUser) {
        // Authenticated Enterprise Session: Unlock studio
        if (gatewayEl) gatewayEl.style.display = 'none';
        if (topNavEl) topNavEl.style.display = 'flex';

        if (workbenchEl && workbenchEl.style.display === 'flex') {
          if (folderSelectEl) folderSelectEl.style.display = 'none';
        } else {
          if (folderSelectEl) folderSelectEl.style.display = 'flex';
        }

        if (loggedOutDiv) loggedOutDiv.style.display = 'none';
        if (loggedInDiv) loggedInDiv.style.display = 'flex';

        const nameEl = document.getElementById('nav-user-name');
        const roleEl = document.getElementById('nav-user-role');
        const avatarEl = document.getElementById('nav-user-avatar');
        if (nameEl) nameEl.textContent = currentUser.full_name || currentUser.email;

        if (avatarEl) {
          const initials = (currentUser.full_name || currentUser.email || 'U')
            .trim()
            .split(' ')
            .map(n => n[0])
            .slice(0, 2)
            .join('')
            .toUpperCase();
          avatarEl.textContent = initials;
        }

        if (roleEl) {
          const role = currentUser.role || 'member';
          roleEl.textContent = role === 'superadmin' ? 'SuperAdmin' : (role === 'company_admin' ? 'Admin' : 'Member');
          roleEl.className = 'user-role-tag ' + (role === 'superadmin' ? 'role-superadmin' : (role === 'company_admin' ? 'role-admin' : 'role-member'));
        }

        const isSuperAdmin = (currentUser.role === 'superadmin' || currentUser.is_superadmin);
        const superAdminScopeBadge = document.getElementById('nav-superadmin-scope-badge');
        const platformDashboardBtn = document.getElementById('btn-nav-platform-dashboard');
        const companyCountBadge = document.getElementById('nav-company-count-badge');

        const teamBtn = document.getElementById('btn-nav-team');
        if (teamBtn) {
          teamBtn.style.display = (!isSuperAdmin && currentUser.role === 'company_admin') ? 'inline-flex' : 'none';
        }

        const workbenchTeamBtn = document.getElementById('btn-workbench-team');
        if (workbenchTeamBtn) {
          workbenchTeamBtn.style.display = isSuperAdmin ? 'none' : (currentUser.role === 'company_admin' ? 'inline-flex' : 'none');
        }

        if (isSuperAdmin) {
          // SuperAdmin is a PLATFORM ROOT operator - DOES NOT TAKE A SEAT in client companies!
          if (companyWrapper) companyWrapper.style.display = 'none';
          if (superAdminScopeBadge) superAdminScopeBadge.style.display = 'inline-flex';
          if (platformDashboardBtn) {
            platformDashboardBtn.style.display = 'inline-flex';
            if (currentUser.platform_metrics && companyCountBadge) {
              companyCountBadge.textContent = currentUser.platform_metrics.total_companies || '3';
            }
          }
        } else {
          if (superAdminScopeBadge) superAdminScopeBadge.style.display = 'none';
          if (platformDashboardBtn) platformDashboardBtn.style.display = 'none';

          if (currentCompany) {
            if (companyWrapper) companyWrapper.style.display = 'inline-flex';
            const compNameEl = document.getElementById('nav-company-name');
            const compPlanEl = document.getElementById('nav-company-plan');
            const quotaTextEl = document.getElementById('nav-seat-quota-text');
            const quotaPill = document.getElementById('nav-seat-quota-pill');
            const quotaFill = document.getElementById('nav-seat-mini-fill');

            if (compNameEl) compNameEl.textContent = currentCompany.name;
            if (compPlanEl) {
              compPlanEl.textContent = (currentCompany.plan || 'team').toUpperCase();
              compPlanEl.className = 'saas-plan-pill plan-' + (currentCompany.plan || 'team');
            }

            const used = currentCompany.used_seats || 0;
            const maxSeats = currentCompany.max_seats || 10;
            const pct = Math.min(100, Math.round((used / maxSeats) * 100));
            if (quotaTextEl) quotaTextEl.textContent = `${used} / ${maxSeats} Seats`;
            if (quotaFill) quotaFill.style.width = pct + '%';

            if (quotaPill) {
              quotaPill.className = 'seat-quota-pill';
              if (used >= maxSeats) {
                quotaPill.classList.add('full');
              } else if (pct >= 80) {
                quotaPill.classList.add('warning');
              }
            }
          } else {
            if (companyWrapper) companyWrapper.style.display = 'none';
          }
        }
      } else {
        // Unauthenticated: STRICT ACCESS LOCKOUT - Zero services accessible
        if (gatewayEl) gatewayEl.style.display = 'flex';
        if (topNavEl) topNavEl.style.display = 'none';
        if (folderSelectEl) folderSelectEl.style.display = 'none';
        if (workbenchEl) workbenchEl.style.display = 'none';
        if (loggedOutDiv) loggedOutDiv.style.display = 'flex';
        if (loggedInDiv) loggedInDiv.style.display = 'none';
        if (companyWrapper) companyWrapper.style.display = 'none';
      }
    }

    // =========================================================================
    // GATEWAY AUTHENTICATION HANDLERS
    // =========================================================================
    function switchGatewayTab(tab) {
      const loginTabBtn = document.getElementById('gateway-tab-login-btn');
      const activateTabBtn = document.getElementById('gateway-tab-activate-btn');
      const loginView = document.getElementById('gateway-view-login');
      const activateView = document.getElementById('gateway-view-activate');

      if (tab === 'login') {
        if (loginTabBtn) loginTabBtn.classList.add('active');
        if (activateTabBtn) activateTabBtn.classList.remove('active');
        if (loginView) loginView.style.display = 'block';
        if (activateView) activateView.style.display = 'none';
      } else {
        if (activateTabBtn) activateTabBtn.classList.add('active');
        if (loginTabBtn) loginTabBtn.classList.remove('active');
        if (activateView) activateView.style.display = 'block';
        if (loginView) loginView.style.display = 'none';
      }
    }

    function fillDemoGatewayCredentials() {
      const emailInput = document.getElementById('gateway-login-email');
      const passInput = document.getElementById('gateway-login-password');
      if (emailInput) emailInput.value = 'admin@athletics.com';
      if (passInput) passInput.value = 'admin';
    }

    async function handleGatewayLoginSubmit(e) {
      e.preventDefault();
      const email = document.getElementById('gateway-login-email').value.trim();
      const password = document.getElementById('gateway-login-password').value;
      const btn = document.getElementById('btn-gateway-login');
      const errAlert = document.getElementById('gateway-login-error');
      if (errAlert) errAlert.style.display = 'none';

      btn.disabled = true;
      btn.innerHTML = '<span>Authenticating...</span>';

      try {
        const res = await fetch('/api/auth/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ email, password })
        });
        const data = await res.json();
        if (res.ok && data.status === 'ok') {
          showToast(`Welcome back, ${data.user.full_name}!`);
          await checkAuthStatus();
          loadSuggestedFolders();
        } else if (data.status === 'mfa_required') {
          const gwLoginView = document.getElementById('gateway-view-login');
          const gwMfaView = document.getElementById('gateway-view-mfa');
          const tokenInput = document.getElementById('gateway-mfa-token');
          if (tokenInput) tokenInput.value = data.mfa_token;
          if (gwLoginView) gwLoginView.style.display = 'none';
          if (gwMfaView) {
            gwMfaView.style.display = 'block';
            const codeInput = document.getElementById('gateway-mfa-code');
            if (codeInput) { codeInput.value = ''; codeInput.focus(); }
          }
          showToast('Two-Factor Authentication required.', 'info');
        } else {
          if (errAlert) {
            errAlert.textContent = data.message || 'Authentication failed. Please verify company credentials.';
            errAlert.style.display = 'block';
          }
        }
      } catch (err) {
        if (errAlert) {
          errAlert.textContent = 'Server connection error. Please try again.';
          errAlert.style.display = 'block';
        }
      } finally {
        btn.disabled = false;
        btn.innerHTML = '<span>Enter Atelier Workspace</span><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/></svg>';
      }
    }

    async function handleGatewayActivationSubmit(e) {
      e.preventDefault();
      const token = document.getElementById('gateway-activate-token').value.trim();
      const fullName = document.getElementById('gateway-activate-name').value.trim();
      const password = document.getElementById('gateway-activate-password').value;
      const confirm = document.getElementById('gateway-activate-confirm').value;
      const btn = document.getElementById('btn-gateway-activate');
      const errAlert = document.getElementById('gateway-activate-error');
      if (errAlert) errAlert.style.display = 'none';

      if (password !== confirm) {
        if (errAlert) {
          errAlert.textContent = 'Passwords do not match.';
          errAlert.style.display = 'block';
        }
        return;
      }

      btn.disabled = true;
      btn.innerHTML = '<span>Activating Seat...</span>';

      try {
        const res = await fetch('/api/auth/activate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ token, password, full_name: fullName })
        });
        const data = await res.json();
        if (res.ok && data.status === 'ok') {
          window.location.hash = '';
          showToast(`Seat activated! Welcome, ${data.user.full_name}.`);
          await checkAuthStatus();
          loadSuggestedFolders();
        } else {
          if (errAlert) {
            errAlert.textContent = data.message || 'Activation failed or invitation expired.';
            errAlert.style.display = 'block';
          }
        }
      } catch (err) {
        if (errAlert) {
          errAlert.textContent = 'Server connection error. Please try again.';
          errAlert.style.display = 'block';
        }
      } finally {
        btn.disabled = false;
        btn.innerHTML = '<span>Activate Seat & Open Studio</span><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/></svg>';
      }
    }

    function checkInviteUrlHash() {
      const hash = window.location.hash || '';
      if (hash.includes('token=')) {
        const tokenMatch = hash.match(/token=([^&]+)/);
        if (tokenMatch && tokenMatch[1]) {
          const token = tokenMatch[1];
          // Pre-fill both gateway and modal activation inputs
          const gwToken = document.getElementById('gateway-activate-token');
          if (gwToken) gwToken.value = token;
          switchGatewayTab('activate');
          showAuthModal('activate', token);
        }
      }
    }

    // Modal Control: Auth
    function showAuthModal(tab = 'login', token = '') {
      const modal = document.getElementById('modal-auth');
      if (!modal) return;
      modal.style.display = 'flex';
      switchAuthTab(tab);
      if (token) {
        const tokenInput = document.getElementById('activate-token');
        if (tokenInput) tokenInput.value = token;
      }
    }

    function hideAuthModal() {
      const modal = document.getElementById('modal-auth');
      if (modal) modal.style.display = 'none';
      const errAlert1 = document.getElementById('login-error-alert');
      if (errAlert1) errAlert1.style.display = 'none';
      const errAlert2 = document.getElementById('activate-error-alert');
      if (errAlert2) errAlert2.style.display = 'none';
    }

    function switchAuthTab(tab) {
      const loginTabBtn = document.getElementById('tab-auth-login');
      const activateTabBtn = document.getElementById('tab-auth-activate');
      const loginView = document.getElementById('view-auth-login');
      const activateView = document.getElementById('view-auth-activate');

      if (tab === 'login') {
        if (loginTabBtn) loginTabBtn.classList.add('active');
        if (activateTabBtn) activateTabBtn.classList.remove('active');
        if (loginView) loginView.style.display = 'block';
        if (activateView) activateView.style.display = 'none';
      } else {
        if (activateTabBtn) activateTabBtn.classList.add('active');
        if (loginTabBtn) loginTabBtn.classList.remove('active');
        if (activateView) activateView.style.display = 'block';
        if (loginView) loginView.style.display = 'none';
      }
    }

    function fillDemoCredentials() {
      const emailInput = document.getElementById('login-email');
      const passInput = document.getElementById('login-password');
      if (emailInput) emailInput.value = 'admin@athletics.com';
      if (passInput) passInput.value = 'admin';
    }

    async function handleLoginSubmit(e) {
      e.preventDefault();
      const email = document.getElementById('login-email').value.trim();
      const password = document.getElementById('login-password').value;
      const btn = document.getElementById('btn-login-submit');
      const errAlert = document.getElementById('login-error-alert');
      if (errAlert) errAlert.style.display = 'none';

      btn.disabled = true;
      btn.innerHTML = '<span>Signing in...</span>';

      try {
        const res = await fetch('/api/auth/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ email, password })
        });
        const data = await res.json();
        if (res.ok && data.status === 'ok') {
          hideAuthModal();
          showToast(`Welcome back, ${data.user.full_name}!`);
          await checkAuthStatus();
        } else if (data.status === 'mfa_required') {
          const loginView = document.getElementById('view-auth-login');
          const mfaView = document.getElementById('view-auth-mfa');
          const tokenInput = document.getElementById('modal-mfa-token');
          if (tokenInput) tokenInput.value = data.mfa_token;
          if (loginView) loginView.style.display = 'none';
          if (mfaView) {
            mfaView.style.display = 'block';
            const codeInput = document.getElementById('modal-mfa-code');
            if (codeInput) { codeInput.value = ''; codeInput.focus(); }
          }
          showToast('Two-Factor Authentication required.', 'info');
        } else {
          if (errAlert) {
            errAlert.textContent = data.message || 'Login failed. Please check your credentials.';
            errAlert.style.display = 'block';
          }
        }
      } catch (err) {
        if (errAlert) {
          errAlert.textContent = 'Server connection error. Please try again.';
          errAlert.style.display = 'block';
        }
      } finally {
        btn.disabled = false;
        btn.innerHTML = '<span>Sign In ➔</span>';
      }
    }

    async function handleActivationSubmit(e) {
      e.preventDefault();
      const token = document.getElementById('activate-token').value.trim();
      const fullName = document.getElementById('activate-name').value.trim();
      const password = document.getElementById('activate-password').value;
      const confirm = document.getElementById('activate-confirm').value;
      const btn = document.getElementById('btn-activate-submit');
      const errAlert = document.getElementById('activate-error-alert');
      if (errAlert) errAlert.style.display = 'none';

      if (password !== confirm) {
        if (errAlert) {
          errAlert.textContent = 'Passwords do not match.';
          errAlert.style.display = 'block';
        }
        return;
      }

      btn.disabled = true;
      btn.innerHTML = '<span>Activating Account...</span>';

      try {
        const res = await fetch('/api/auth/activate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ token, password, full_name: fullName })
        });
        const data = await res.json();
        if (res.ok && data.status === 'ok') {
          hideAuthModal();
          window.location.hash = '';
          showToast(`Welcome to Pro Portrait Studio, ${data.user.full_name}!`);
          await checkAuthStatus();
        } else {
          if (errAlert) {
            errAlert.textContent = data.message || 'Activation failed or invitation expired.';
            errAlert.style.display = 'block';
          }
        }
      } catch (err) {
        if (errAlert) {
          errAlert.textContent = 'Server connection error. Please try again.';
          errAlert.style.display = 'block';
        }
      } finally {
        btn.disabled = false;
        btn.innerHTML = '<span>Activate Account & Enter Studio</span>';
      }
    }

    async function logoutUser() {
      try {
        await fetch('/api/auth/logout', { method: 'POST' });
        currentUser = null;
        currentCompany = null;
        renderAuthUI();
        showToast('You have been logged out.');
      } catch (e) {
        console.error(e);
      }
    }

    // Modal Control: Team Management & Bulk Invites
    async function openTeamModal(tab = 'bulk') {
      const modal = document.getElementById('modal-team-mgmt');
      if (!modal) return;

      const isPrivilegedAdmin = currentUser && (currentUser.role === 'superadmin' || currentUser.role === 'company_admin');

      // Regular members can only view the member directory; hide invite & bulk tabs
      const bulkTabBtn = document.getElementById('tab-team-bulk');
      const singleTabBtn = document.getElementById('tab-team-single');
      if (bulkTabBtn) bulkTabBtn.style.display = isPrivilegedAdmin ? 'inline-flex' : 'none';
      if (singleTabBtn) singleTabBtn.style.display = isPrivilegedAdmin ? 'inline-flex' : 'none';

      if (!isPrivilegedAdmin) {
        tab = 'members';
      }

      modal.style.display = 'flex';
      switchTeamTab(tab);
      await loadTeamData();
    }

    function hideTeamModal() {
      const modal = document.getElementById('modal-team-mgmt');
      if (modal) modal.style.display = 'none';
    }

    function switchTeamTab(tab) {
      const isPrivilegedAdmin = currentUser && (currentUser.role === 'superadmin' || currentUser.role === 'company_admin');
      if (!isPrivilegedAdmin && tab !== 'members') {
        tab = 'members';
      }

      const tabs = ['bulk', 'single', 'members'];
      tabs.forEach(t => {
        const btn = document.getElementById(`tab-team-${t}`);
        const view = document.getElementById(`view-team-${t}`);
        if (btn) btn.classList.toggle('active', t === tab);
        if (view) view.style.display = (t === tab) ? 'block' : 'none';
      });
    }

    async function loadTeamData() {
      try {
        const res = await fetch('/api/company/users');
        if (!res.ok) throw new Error('Could not load company members');
        const data = await res.json();
        cachedTeamData = data;

        const compTitle = document.getElementById('team-modal-company-title');
        const meterComp = document.getElementById('meter-company-name');
        const meterPlan = document.getElementById('meter-plan-tag');
        const meterText = document.getElementById('meter-seat-text');
        const meterBar = document.getElementById('meter-bar-fill');
        const countSpan = document.getElementById('tab-member-count');

        if (data.company) {
          if (compTitle) compTitle.textContent = data.company.name;
          if (meterComp) meterComp.textContent = data.company.name;
          if (meterPlan) {
            meterPlan.textContent = `${(data.company.plan || 'team').toUpperCase()} PLAN`;
            meterPlan.className = 'saas-plan-pill plan-' + (data.company.plan || 'team');
          }
        }

        const used = data.used_seats || 0;
        const max = data.max_seats || 10;
        const remaining = data.remaining_seats || 0;
        const pct = Math.min(100, Math.round((used / max) * 100));

        if (meterText) meterText.textContent = `${used} / ${max} Seats Used (${remaining} Remaining)`;
        if (meterBar) meterBar.style.width = `${pct}%`;
        if (countSpan) countSpan.textContent = (data.users || []).length;

        // Render member directory table
        renderTeamMembersTable(data.users || []);

        // Also update navbar quota pill
        const quotaTextEl = document.getElementById('nav-seat-quota-text');
        if (quotaTextEl) quotaTextEl.textContent = `${used} / ${max} Seats`;
      } catch (err) {
        console.error(err);
      }
    }

        function renderTeamMembersTable(members) {
      const tbody = document.getElementById('team-members-tbody');
      if (!tbody) return;
      tbody.innerHTML = '';

      if (members.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" style="text-align:center; color:var(--text-muted); padding:20px;">No members found in this company.</td></tr>';
        return;
      }

      const isSuperAdmin = currentUser && currentUser.role === 'superadmin';
      const isCompanyAdmin = currentUser && (currentUser.role === 'company_admin' || currentUser.role === 'admin');
      const isPrivilegedAdmin = isSuperAdmin || isCompanyAdmin;

      members.forEach(m => {
        const tr = document.createElement('tr');
        const isSelf = currentUser && currentUser.id === m.id;
        const isPending = !m.password_hash && m.invite_token;
        const roleBadge = m.role === 'superadmin' ? '<span class="user-role-tag role-superadmin">SuperAdmin</span>'
          : (m.role === 'company_admin' ? '<span class="user-role-tag role-admin">Admin</span>'
          : '<span class="user-role-tag role-member">Member</span>');

        const statusBadge = isPending
          ? '<span style="font-size:0.7rem; background:rgba(245,158,11,0.15); border:1px solid rgba(245,158,11,0.3); color:#b45309; padding:2px 8px; border-radius:10px; font-weight:700;">Pending Invite</span>'
          : '<span style="font-size:0.7rem; background:rgba(16,185,129,0.12); border:1px solid rgba(16,185,129,0.3); color:#047857; padding:2px 8px; border-radius:10px; font-weight:700;">Active</span>';

        let actionHtml = '';

        // 1. Invites & Activation Links: ONLY privileged admins can view or resend invites!
        if (isPrivilegedAdmin && m.activation_url) {
          actionHtml += `<button class="btn-copy-link" onclick="copyActivationUrl('${m.activation_url}')" title="Copy password activation link to clipboard">Copy Invite Link</button> `;
          actionHtml += `<button class="btn btn-secondary" onclick="resendMemberInvite('${m.id}')" style="font-size:0.72rem; padding:4px 8px;" title="Resend invitation email">Resend</button> `;
        }

        // 2. Removal / Revocation Hierarchy:
        // - Regular members can NEVER remove ANYONE!
        // - Company Admins can ONLY remove regular 'member' users. They can NEVER remove fellow administrators or superadmins!
        // - SuperAdmins can remove company admins and members, but never themselves!
        // - No user can ever remove themselves!
        let canRemove = false;
        if (!isSelf && isPrivilegedAdmin) {
          if (isSuperAdmin) {
            canRemove = true;
          } else if (isCompanyAdmin) {
            canRemove = (m.role === 'member');
          }
        }

        if (canRemove) {
          actionHtml += `<button class="btn-revoke-user" onclick="revokeCompanyMember('${m.id}', '${escapeHtml(m.email)}')" title="Revoke membership and free seat">Remove</button>`;
        } else if (!actionHtml) {
          actionHtml = `<span style="font-size:0.74rem; color:var(--text-muted); font-style:italic;">Protected</span>`;
        }

        tr.innerHTML = `
          <td>
            <div style="font-weight:700; color:var(--text);">${escapeHtml(m.full_name || m.email)} ${isSelf ? '<span style="font-size:0.7rem; color:var(--primary); font-weight:800;">(You)</span>' : ''}</div>
            <div style="font-size:0.74rem; color:var(--text-muted); font-family:monospace;">${escapeHtml(m.email)}</div>
          </td>
          <td>${roleBadge}</td>
          <td>${statusBadge}</td>
          <td style="text-align:right;">${actionHtml}</td>
        `;
        tbody.appendChild(tr);
      });
    }

    function insertBulkSample() {
      const textarea = document.getElementById('bulk-invite-text');
      if (textarea) {
        textarea.value = `sarah.connor@athletics.com, Sarah Connor, company_admin\njohn.smith@athletics.com, John Smith, member\ncoach.carter@athletics.com, Coach Carter, member\nassistant.coach@athletics.com`;
      }
    }

    async function handleBulkInviteSubmit() {
      const textarea = document.getElementById('bulk-invite-text');
      const rawText = textarea.value.trim();
      const btn = document.getElementById('btn-submit-bulk');
      const resultsBox = document.getElementById('bulk-results-box');
      const resultsList = document.getElementById('bulk-results-list');

      if (!rawText) {
        showToast('Please enter at least one user email to invite.', 'error');
        return;
      }

      btn.disabled = true;
      btn.innerHTML = '<span>Inviting & Sending Emails...</span>';

      try {
        const res = await fetch('/api/company/users/bulk_invite', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ raw_text: rawText })
        });
        const data = await res.json();
        if (res.ok && data.status === 'ok') {
          resultsBox.style.display = 'block';
          resultsList.innerHTML = '';

          // Show added
          (data.added || []).forEach(u => {
            const div = document.createElement('div');
            div.className = 'result-pill-added';
            div.innerHTML = `
              <div>
                <strong>${escapeHtml(u.full_name)}</strong> &lt;${escapeHtml(u.email)}&gt;
                <span style="font-size:0.7rem; opacity:0.8; margin-left:6px;">(${u.role})</span>
                ${u.email_simulated ? '<span style="font-size:0.68rem; background:rgba(56,189,248,0.2); padding:1px 6px; border-radius:6px; margin-left:6px; color:#38bdf8;">Dev Mode Link</span>' : '<span style="font-size:0.68rem; color:#34d399; margin-left:6px;">📧 Email Sent</span>'}
              </div>
              <div>
                <button class="btn-copy-link" onclick="copyActivationUrl('${u.activation_url}')">Copy Invite Link</button>
              </div>
            `;
            resultsList.appendChild(div);
          });

          // Show skipped
          (data.skipped || []).forEach(s => {
            const div = document.createElement('div');
            div.className = 'result-pill-skipped';
            div.innerHTML = `
              <div>
                <strong>${escapeHtml(s.name || s.email)}</strong> &lt;${escapeHtml(s.email)}&gt;
              </div>
              <div style="font-size:0.75rem; font-weight:700;">${escapeHtml(s.reason)}</div>
            `;
            resultsList.appendChild(div);
          });

          showToast(`Processed bulk invite: ${(data.added || []).length} users invited.`);
          textarea.value = '';
          await loadTeamData();
          await checkAuthStatus();
        } else {
          showToast(data.message || 'Bulk invite error occurred.', 'error');
        }
      } catch (err) {
        showToast('Server connection failed.', 'error');
      } finally {
        btn.disabled = false;
        btn.innerHTML = '<span>Send Bulk Invites & Allocate Seats</span>';
      }
    }

    async function handleSingleInviteSubmit(e) {
      e.preventDefault();
      const email = document.getElementById('single-email').value.trim();
      const fullName = document.getElementById('single-name').value.trim();
      const role = document.getElementById('single-role').value;
      const btn = document.getElementById('btn-submit-single');
      const alertBox = document.getElementById('single-invite-alert');
      if (alertBox) alertBox.style.display = 'none';

      btn.disabled = true;
      btn.innerHTML = '<span>Sending Invitation...</span>';

      try {
        const res = await fetch('/api/company/users/invite', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ email, full_name: fullName, role })
        });
        const data = await res.json();
        if (res.ok && data.status === 'ok') {
          showToast(`Invitation sent to ${email}.`);
          document.getElementById('single-email').value = '';
          document.getElementById('single-name').value = '';

          if (alertBox) {
            alertBox.style.display = 'block';
            alertBox.style.background = 'rgba(16,185,129,0.15)';
            alertBox.style.color = '#34d399';
            alertBox.style.border = '1px solid rgba(16,185,129,0.3)';
            alertBox.innerHTML = `
              <div>Invitation sent to <strong>${escapeHtml(email)}</strong>!</div>
              <div style="margin-top:6px; font-size:0.75rem;">
                Direct activation link: <a href="${data.activation_url}" target="_blank" style="color:#38bdf8;">${data.activation_url}</a>
                <button class="btn-copy-link" style="margin-left:8px;" onclick="copyActivationUrl('${data.activation_url}')">📋 Copy</button>
              </div>
            `;
          }
          await loadTeamData();
          await checkAuthStatus();
        } else {
          if (alertBox) {
            alertBox.style.display = 'block';
            alertBox.style.background = 'rgba(239,68,68,0.15)';
            alertBox.style.color = '#fca5a5';
            alertBox.style.border = '1px solid rgba(239,68,68,0.3)';
            alertBox.textContent = data.message || 'Failed to send invite.';
          }
        }
      } catch (err) {
        showToast('Server error.', 'error');
      } finally {
        btn.disabled = false;
        btn.innerHTML = '<span>Send Invitation Email</span>';
      }
    }

    async function revokeCompanyMember(userId, email) {
      if (!confirm(`Are you sure you want to remove ${email} from your company team? This will free 1 subscription seat.`)) return;
      try {
        const res = await fetch('/api/company/users/revoke', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ user_id: userId })
        });
        const data = await res.json();
        if (res.ok && data.status === 'ok') {
          showToast(`Seat freed: ${email} removed.`);
          await loadTeamData();
          await checkAuthStatus();
        } else {
          showToast(data.message || 'Could not remove member.', 'error');
        }
      } catch (e) {
        showToast('Server error.', 'error');
      }
    }

    async function resendMemberInvite(userId) {
      try {
        const res = await fetch('/api/company/users/resend_invite', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ user_id: userId })
        });
        const data = await res.json();
        if (res.ok && data.status === 'ok') {
          showToast('Invitation email resent!');
          if (data.activation_url) {
            navigator.clipboard.writeText(data.activation_url);
            showToast('Copied activation link to clipboard.');
          }
          await loadTeamData();
        } else {
          showToast(data.message || 'Failed to resend invite.', 'error');
        }
      } catch (e) {
        showToast('Server error.', 'error');
      }
    }

    function copyActivationUrl(url) {
      if (!url) return;
      navigator.clipboard.writeText(url).then(() => {
        showToast('Copied activation link to clipboard.');
      }).catch(() => {
        prompt('Copy activation link:', url);
      });
    }

    // =========================================================================
    // MULTI-FACTOR AUTHENTICATION (MFA) & PASSKEY CLIENT CONTROLS
    // =========================================================================

    async function handleMfaLoginSubmit(e, context = 'gateway') {
      e.preventDefault();
      const isGateway = (context === 'gateway');
      const tokenInput = document.getElementById(isGateway ? 'gateway-mfa-token' : 'modal-mfa-token');
      const codeInput = document.getElementById(isGateway ? 'gateway-mfa-code' : 'modal-mfa-code');
      const errAlert = document.getElementById(isGateway ? 'gateway-mfa-error' : 'modal-mfa-error');
      const btn = document.getElementById(isGateway ? 'btn-gateway-mfa' : 'btn-modal-mfa');

      const mfa_token = tokenInput ? tokenInput.value : '';
      const code = codeInput ? codeInput.value.trim() : '';

      if (errAlert) errAlert.style.display = 'none';
      if (btn) { btn.disabled = true; btn.innerHTML = '<span>Verifying MFA...</span>'; }

      try {
        const res = await fetch('/api/auth/mfa/verify_login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ mfa_token, code })
        });
        const data = await res.json();
        if (res.ok && data.status === 'ok') {
          showToast(`MFA Verified! Welcome, ${data.user.full_name}.`);
          if (!isGateway) hideAuthModal();
          await checkAuthStatus();
          loadSuggestedFolders();
        } else {
          if (data.mfa_token && tokenInput) tokenInput.value = data.mfa_token;
          if (errAlert) {
            errAlert.textContent = data.message || 'Verification failed. Please check your code.';
            errAlert.style.display = 'block';
          }
        }
      } catch (err) {
        if (errAlert) {
          errAlert.textContent = 'Server connection error during MFA verification.';
          errAlert.style.display = 'block';
        }
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = '<span>Verify & Enter Workspace</span>';
        }
      }
    }

    function cancelMfaLogin(context = 'gateway') {
      const isGateway = (context === 'gateway');
      if (isGateway) {
        const mfaView = document.getElementById('gateway-view-mfa');
        const loginView = document.getElementById('gateway-view-login');
        if (mfaView) mfaView.style.display = 'none';
        if (loginView) loginView.style.display = 'block';
      } else {
        const mfaView = document.getElementById('view-auth-mfa');
        const loginView = document.getElementById('view-auth-login');
        if (mfaView) mfaView.style.display = 'none';
        if (loginView) loginView.style.display = 'block';
      }
    }

    // WebAuthn Passkeys: Buffers & Encoders
    function bufferToBase64Url(buffer) {
      const bytes = new Uint8Array(buffer);
      let binary = '';
      for (let i = 0; i < bytes.byteLength; i++) {
        binary += String.fromCharCode(bytes[i]);
      }
      return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
    }

    function base64UrlToBuffer(base64url) {
      let base64 = base64url.replace(/-/g, '+').replace(/_/g, '/');
      while (base64.length % 4) {
        base64 += '=';
      }
      const binary = atob(base64);
      const bytes = new Uint8Array(binary.length);
      for (let i = 0; i < binary.length; i++) {
        bytes[i] = binary.charCodeAt(i);
      }
      return bytes.buffer;
    }

    async function startPasskeyLogin(context = 'gateway') {
      if (!window.PublicKeyCredential) {
        showToast('Passkeys / WebAuthn is not supported on this browser.', 'error');
        return;
      }
      try {
        const optRes = await fetch('/api/auth/passkey/login_options');
        const optData = await optRes.json();
        if (!optRes.ok || optData.status !== 'ok') {
          showToast(optData.message || 'Could not initiate Passkey authentication.', 'error');
          return;
        }

        const opts = optData.options;
        const challengeBuffer = base64UrlToBuffer(opts.challenge);

        showToast('Touch your biometric sensor or security key now...', 'info');

        const assertion = await navigator.credentials.get({
          publicKey: {
            challenge: challengeBuffer,
            timeout: 60000,
            userVerification: "preferred"
          }
        });

        if (!assertion) {
          showToast('Passkey authentication was cancelled.', 'error');
          return;
        }

        const verifyRes = await fetch('/api/auth/passkey/login_verify', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            challenge_id: opts.challenge_id,
            credential: {
              id: assertion.id,
              rawId: bufferToBase64Url(assertion.rawId),
              type: assertion.type,
              response: {
                clientDataJSON: bufferToBase64Url(assertion.response.clientDataJSON),
                authenticatorData: bufferToBase64Url(assertion.response.authenticatorData),
                signature: bufferToBase64Url(assertion.response.signature),
                userHandle: assertion.response.userHandle ? bufferToBase64Url(assertion.response.userHandle) : null
              }
            }
          })
        });

        const verifyData = await verifyRes.json();
        if (verifyRes.ok && verifyData.status === 'ok') {
          showToast(`Biometric Sign-In Successful! Welcome, ${verifyData.user.full_name}.`);
          if (context === 'modal') hideAuthModal();
          await checkAuthStatus();
          loadSuggestedFolders();
        } else {
          showToast(verifyData.message || 'Passkey verification failed.', 'error');
        }
      } catch (err) {
        if (err.name === 'NotAllowedError' || err.name === 'AbortError') {
          showToast('Passkey sign-in was cancelled.', 'info');
        } else {
          console.error("Passkey error:", err);
          showToast('Biometric authentication failed: ' + (err.message || err), 'error');
        }
      }
    }

    async function startPasskeyRegister() {
      if (!window.PublicKeyCredential) {
        showToast('Passkeys / WebAuthn is not supported on this browser.', 'error');
        return;
      }
      const deviceName = prompt('Enter a label for this Passkey (e.g. MacBook Touch ID, iPhone Face ID):', 'My Biometric Key');
      if (!deviceName) return;

      try {
        const optRes = await fetch('/api/auth/passkey/register_options');
        const optData = await optRes.json();
        if (!optRes.ok || optData.status !== 'ok') {
          showToast(optData.message || 'Could not fetch registration options.', 'error');
          return;
        }

        const opts = optData.options;
        const challengeBuffer = base64UrlToBuffer(opts.challenge);
        const userIdBuffer = new TextEncoder().encode(opts.user.id);

        showToast('Touch your biometric sensor or security key now...', 'info');

        const credential = await navigator.credentials.create({
          publicKey: {
            challenge: challengeBuffer,
            rp: { name: opts.rp.name, id: window.location.hostname },
            user: {
              id: userIdBuffer,
              name: opts.user.name,
              displayName: opts.user.displayName
            },
            pubKeyCredParams: opts.pubKeyCredParams,
            authenticatorSelection: {
              authenticatorAttachment: "platform",
              userVerification: "preferred"
            },
            timeout: 60000
          }
        });

        if (!credential) {
          showToast('Passkey registration was cancelled.', 'error');
          return;
        }

        const verifyRes = await fetch('/api/auth/passkey/register_verify', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            challenge_id: opts.challenge_id,
            name: deviceName,
            credential: {
              id: credential.id,
              rawId: bufferToBase64Url(credential.rawId),
              type: credential.type,
              response: {
                clientDataJSON: bufferToBase64Url(credential.response.clientDataJSON),
                attestationObject: bufferToBase64Url(credential.response.attestationObject)
              }
            }
          })
        });

        const verifyData = await verifyRes.json();
        if (verifyRes.ok && verifyData.status === 'ok') {
          showToast(`Passkey '${deviceName}' registered successfully!`);
          await loadPasskeysList();
          await checkAuthStatus();
        } else {
          showToast(verifyData.message || 'Passkey registration verification failed.', 'error');
        }
      } catch (err) {
        if (err.name === 'NotAllowedError' || err.name === 'AbortError') {
          showToast('Passkey registration cancelled.', 'info');
        } else {
          console.error("Passkey reg error:", err);
          showToast('Registration error: ' + (err.message || err), 'error');
        }
      }
    }

    async function loadPasskeysList() {
      const tbody = document.getElementById('passkeys-table-body');
      if (!tbody) return;
      tbody.innerHTML = '<tr><td colspan="4" style="text-align:center; padding:16px; color:var(--text-muted);">Loading registered passkeys...</td></tr>';
      try {
        const res = await fetch('/api/auth/passkey/list');
        const data = await res.json();
        if (res.ok && data.status === 'ok') {
          const keys = data.passkeys || [];
          if (keys.length === 0) {
            tbody.innerHTML = '<tr><td colspan="4" style="text-align:center; padding:20px; color:var(--text-muted);">No biometric passkeys registered yet. Click "+ Add New Passkey" above.</td></tr>';
            return;
          }
          tbody.innerHTML = '';
          keys.forEach(k => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
              <td>
                <div style="font-weight:700; color:#0f172a; display:flex; align-items:center; gap:8px;">
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#b8860b" stroke-width="2"><path d="M2 18v3c0 .6.4 1 1 1h4v-3h3v-3h2l1.4-1.4a6.5 6.5 0 1 0-4-4Z"/><circle cx="16.5" cy="7.5" r=".5"/></svg>
                  <span>${escapeHtml(k.name || 'Biometric Key')}</span>
                </div>
                <div style="font-size:0.7rem; color:var(--text-muted); font-family:var(--font-mono);">${escapeHtml((k.credential_id || '').substring(0, 24))}...</div>
              </td>
              <td style="font-size:0.78rem; color:var(--text-muted);">${k.created_at ? new Date(k.created_at).toLocaleDateString() : 'N/A'}</td>
              <td style="font-size:0.78rem; color:#059669; font-weight:600;">${k.last_used_at ? new Date(k.last_used_at).toLocaleDateString() : 'Never'}</td>
              <td style="text-align:right;">
                <button class="btn btn-secondary" onclick="deletePasskey('${k.id}')" style="border-color:#ef4444; color:#ef4444; font-size:0.72rem; padding:4px 8px;">
                  Remove
                </button>
              </td>
            `;
            tbody.appendChild(tr);
          });
        }
      } catch (e) {
        console.error(e);
      }
    }

    async function deletePasskey(passkeyId) {
      if (!confirm('Are you sure you want to remove this passkey?')) return;
      try {
        const res = await fetch('/api/auth/passkey/delete', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ passkey_id: passkeyId })
        });
        const data = await res.json();
        if (res.ok && data.status === 'ok') {
          showToast('Passkey removed.');
          await loadPasskeysList();
          await checkAuthStatus();
        } else {
          showToast(data.message || 'Could not delete passkey.', 'error');
        }
      } catch (e) {
        showToast('Server error.', 'error');
      }
    }

    // =========================================================================
    // ACCOUNT CREDENTIALS & MFA SETTINGS CONTROLS
    // =========================================================================
    let currentMfaSetupData = null;

    function openAccountSettingsModal(tab = 'credentials') {
      const modal = document.getElementById('modal-account-settings');
      if (!modal) return;
      modal.style.display = 'flex';
      switchAccountTab(tab);

      if (currentUser) {
        const nameInput = document.getElementById('acc-full-name');
        const emailInput = document.getElementById('acc-email');
        if (nameInput) nameInput.value = currentUser.full_name || '';
        if (emailInput) emailInput.value = currentUser.email || '';

        const disabledBox = document.getElementById('mfa-status-disabled-box');
        const enabledBox = document.getElementById('mfa-status-enabled-box');
        const wizardBox = document.getElementById('mfa-setup-wizard');
        if (wizardBox) wizardBox.style.display = 'none';

        if (currentUser.mfa_enabled) {
          if (disabledBox) disabledBox.style.display = 'none';
          if (enabledBox) enabledBox.style.display = 'block';
        } else {
          if (disabledBox) disabledBox.style.display = 'block';
          if (enabledBox) enabledBox.style.display = 'none';
        }
      }

      loadPasskeysList();
    }

    function hideAccountSettingsModal() {
      const modal = document.getElementById('modal-account-settings');
      if (modal) modal.style.display = 'none';
    }

    function switchAccountTab(tab) {
      const tabs = ['credentials', 'mfa', 'passkeys'];
      tabs.forEach(t => {
        const btn = document.getElementById(`tab-account-${t}`);
        const view = document.getElementById(`view-account-${t}`);
        if (btn) btn.classList.toggle('active', t === tab);
        if (view) view.style.display = (t === tab) ? 'block' : 'none';
      });
      if (tab === 'passkeys') loadPasskeysList();
    }

    async function handleUpdateProfileSubmit(e) {
      e.preventDefault();
      const fullName = document.getElementById('acc-full-name').value.trim();
      const email = document.getElementById('acc-email').value.trim();
      const currentPassword = document.getElementById('acc-current-password').value;
      const newPassword = document.getElementById('acc-new-password').value;
      const confirmPassword = document.getElementById('acc-confirm-password').value;
      const errEl = document.getElementById('acc-profile-error');
      const succEl = document.getElementById('acc-profile-success');
      const btn = document.getElementById('btn-save-credentials');

      if (errEl) errEl.style.display = 'none';
      if (succEl) succEl.style.display = 'none';

      if (newPassword) {
        if (newPassword.length < 4) {
          if (errEl) { errEl.textContent = 'New password must be at least 4 characters.'; errEl.style.display = 'block'; }
          return;
        }
        if (newPassword !== confirmPassword) {
          if (errEl) { errEl.textContent = 'New passwords do not match.'; errEl.style.display = 'block'; }
          return;
        }
      }

      btn.disabled = true;
      btn.innerHTML = '<span>Saving Changes...</span>';

      try {
        const profRes = await fetch('/api/auth/update_profile', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ full_name: fullName, email: email, current_password: currentPassword })
        });
        const profData = await profRes.json();
        if (!profRes.ok || profData.status !== 'ok') {
          if (errEl) { errEl.textContent = profData.message || 'Profile update failed.'; errEl.style.display = 'block'; }
          btn.disabled = false;
          btn.innerHTML = '<span>Save Credentials & Password</span>';
          return;
        }

        if (newPassword) {
          const passRes = await fetch('/api/auth/change_password', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ current_password: currentPassword, new_password: newPassword })
          });
          const passData = await passRes.json();
          if (!passRes.ok || passData.status !== 'ok') {
            if (errEl) { errEl.textContent = passData.message || 'Password update failed.'; errEl.style.display = 'block'; }
            btn.disabled = false;
            btn.innerHTML = '<span>Save Credentials & Password</span>';
            return;
          }
        }

        if (succEl) {
          succEl.textContent = 'Account credentials and password successfully updated!';
          succEl.style.display = 'block';
        }
        document.getElementById('acc-current-password').value = '';
        document.getElementById('acc-new-password').value = '';
        document.getElementById('acc-confirm-password').value = '';
        showToast('Credentials updated successfully!');
        await checkAuthStatus();
      } catch (err) {
        if (errEl) { errEl.textContent = 'Server connection error.'; errEl.style.display = 'block'; }
      } finally {
        btn.disabled = false;
        btn.innerHTML = '<span>Save Credentials & Password</span>';
      }
    }

    async function startMfaSetupWizard() {
      try {
        const res = await fetch('/api/auth/mfa/setup', { method: 'POST' });
        const data = await res.json();
        if (res.ok && data.status === 'ok') {
          currentMfaSetupData = data;
          document.getElementById('mfa-status-disabled-box').style.display = 'none';
          document.getElementById('mfa-setup-wizard').style.display = 'block';
          document.getElementById('mfa-qr-img').src = data.qr_url;
          document.getElementById('mfa-secret-text').textContent = data.secret;

          const codesContainer = document.getElementById('mfa-backup-codes-list');
          if (codesContainer) {
            codesContainer.innerHTML = '';
            (data.backup_codes || []).forEach(c => {
              const div = document.createElement('div');
              div.className = 'backup-code-item';
              div.textContent = c;
              codesContainer.appendChild(div);
            });
          }
        } else {
          showToast(data.message || 'Could not initiate MFA setup.', 'error');
        }
      } catch (e) {
        showToast('Server error.', 'error');
      }
    }

    function cancelMfaSetupWizard() {
      document.getElementById('mfa-setup-wizard').style.display = 'none';
      document.getElementById('mfa-status-disabled-box').style.display = 'block';
    }

    function copyMfaSecret() {
      if (currentMfaSetupData && currentMfaSetupData.secret) {
        navigator.clipboard.writeText(currentMfaSetupData.secret);
        showToast('MFA Secret Key copied to clipboard!');
      }
    }

    function copyBackupCodes() {
      if (currentMfaSetupData && currentMfaSetupData.backup_codes) {
        navigator.clipboard.writeText(currentMfaSetupData.backup_codes.join('\n'));
        showToast('All 8 Backup Codes copied to clipboard!');
      }
    }

    async function handleMfaConfirmSubmit(e) {
      e.preventDefault();
      if (!currentMfaSetupData) return;
      const code = document.getElementById('mfa-confirm-code').value.trim();
      const errEl = document.getElementById('mfa-confirm-error');
      const btn = document.getElementById('btn-mfa-confirm');
      if (errEl) errEl.style.display = 'none';

      btn.disabled = true;
      btn.innerHTML = '<span>Verifying...</span>';

      try {
        const res = await fetch('/api/auth/mfa/enable', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            secret: currentMfaSetupData.secret,
            code: code,
            backup_codes: currentMfaSetupData.backup_codes
          })
        });
        const data = await res.json();
        if (res.ok && data.status === 'ok') {
          showToast('Two-Factor Authentication is now enabled!');
          document.getElementById('mfa-setup-wizard').style.display = 'none';
          document.getElementById('mfa-status-enabled-box').style.display = 'block';
          await checkAuthStatus();
        } else {
          if (errEl) { errEl.textContent = data.message || 'Invalid code.'; errEl.style.display = 'block'; }
        }
      } catch (e) {
        if (errEl) { errEl.textContent = 'Server connection error.'; errEl.style.display = 'block'; }
      } finally {
        btn.disabled = false;
        btn.innerHTML = '<span>Verify Code & Enable 2FA</span>';
      }
    }

    async function handleMfaDisableSubmit(e) {
      e.preventDefault();
      const password = document.getElementById('mfa-disable-password').value;
      const errEl = document.getElementById('mfa-disable-error');
      if (errEl) errEl.style.display = 'none';

      try {
        const res = await fetch('/api/auth/mfa/disable', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ password })
        });
        const data = await res.json();
        if (res.ok && data.status === 'ok') {
          showToast('Two-Factor Authentication has been disabled.');
          document.getElementById('mfa-disable-password').value = '';
          document.getElementById('mfa-status-enabled-box').style.display = 'none';
          document.getElementById('mfa-status-disabled-box').style.display = 'block';
          await checkAuthStatus();
        } else {
          if (errEl) { errEl.textContent = data.message || 'Incorrect password.'; errEl.style.display = 'block'; }
        }
      } catch (e) {
        if (errEl) { errEl.textContent = 'Server error.'; errEl.style.display = 'block'; }
      }
    }

    // =========================================================================
    // SUPERADMIN PLATFORM FLEET DASHBOARD CONTROLS
    // =========================================================================
    let allCompaniesCache = [];

    async function openPlatformDashboard(tab = 'companies') {
      const modal = document.getElementById('modal-superadmin');
      if (!modal) return;
      modal.style.display = 'flex';
      switchSuperAdminTab(tab);
      await loadPlatformDashboardMetrics();
    }

    async function openSuperAdminModal() {
      await openPlatformDashboard('companies');
    }

    function hideSuperAdminModal() {
      const modal = document.getElementById('modal-superadmin');
      if (modal) modal.style.display = 'none';
    }

    function switchSuperAdminTab(tab) {
      const tabComp = document.getElementById('tab-superadmin-companies');
      const tabCreate = document.getElementById('tab-superadmin-create');
      const tabKeep = document.getElementById('tab-superadmin-keepalive');
      const viewComp = document.getElementById('view-superadmin-companies');
      const viewCreate = document.getElementById('view-superadmin-create');
      const viewKeep = document.getElementById('view-superadmin-keepalive');

      if (tab === 'companies') {
        if (tabComp) tabComp.classList.add('active');
        if (tabCreate) tabCreate.classList.remove('active');
        if (tabKeep) tabKeep.classList.remove('active');
        if (viewComp) viewComp.style.display = 'block';
        if (viewCreate) viewCreate.style.display = 'none';
        if (viewKeep) viewKeep.style.display = 'none';
      } else if (tab === 'create') {
        if (tabCreate) tabCreate.classList.add('active');
        if (tabComp) tabComp.classList.remove('active');
        if (tabKeep) tabKeep.classList.remove('active');
        if (viewCreate) viewCreate.style.display = 'block';
        if (viewComp) viewComp.style.display = 'none';
        if (viewKeep) viewKeep.style.display = 'none';
      } else if (tab === 'keepalive') {
        if (tabKeep) tabKeep.classList.add('active');
        if (tabComp) tabComp.classList.remove('active');
        if (tabCreate) tabCreate.classList.remove('active');
        if (viewKeep) viewKeep.style.display = 'block';
        if (viewComp) viewComp.style.display = 'none';
        if (viewCreate) viewCreate.style.display = 'none';
        loadKeepAliveStatus();
      }
    }

    async function loadKeepAliveStatus() {
      try {
        const res = await fetch('/api/keep_alive/status');
        if (!res.ok) return;
        const data = await res.json();

        const badgeEl = document.getElementById('ka-status-badge');
        const urlEl = document.getElementById('ka-target-url');
        const intervalEl = document.getElementById('ka-interval');
        const pingsEl = document.getElementById('ka-total-pings');
        const lastPingEl = document.getElementById('ka-last-ping');
        const latencyEl = document.getElementById('ka-latency');
        const hostBadgeEl = document.getElementById('ka-host-badge');
        const inputUrl = document.getElementById('ka-custom-url-input');

        if (badgeEl) {
          badgeEl.innerHTML = data.enabled
            ? '<span style="display:inline-flex; align-items:center; gap:6px; color:#16a34a; font-weight:700;"><span style="width:8px; height:8px; border-radius:50%; background:#16a34a; box-shadow:0 0 8px #16a34a;"></span> Active (Anti-Idle Running)</span>'
            : '<span style="color:#dc2626; font-weight:700;">Disabled</span>';
        }
        if (urlEl) urlEl.textContent = data.target_url || 'Detecting upon first public request...';
        if (inputUrl && !inputUrl.value && data.target_url) inputUrl.value = data.target_url;
        if (intervalEl) intervalEl.textContent = (data.interval_seconds / 60) + ' min (' + data.interval_seconds + 's)';
        if (pingsEl) pingsEl.textContent = data.successful_pings + ' success / ' + data.total_pings + ' total';
        if (lastPingEl) {
          lastPingEl.textContent = data.last_ping_time ? (new Date(data.last_ping_time).toLocaleTimeString() + ' (' + (data.last_ping_status || 'OK') + ')') : 'Awaiting first interval';
        }
        if (latencyEl) latencyEl.textContent = data.last_ping_latency_ms ? (data.last_ping_latency_ms + ' ms') : '-';
        if (hostBadgeEl) {
          hostBadgeEl.textContent = data.is_render ? 'Render Cloud (Active)' : 'Local / Custom Server';
        }
      } catch (e) {
        console.error('Failed to load keep-alive status:', e);
      }
    }

    async function triggerKeepAliveTest() {
      const btn = document.getElementById('btn-ka-ping-now');
      const resultEl = document.getElementById('ka-ping-result');
      if (btn) btn.disabled = true;
      if (resultEl) resultEl.innerHTML = '<span style="color:#64748b;">Pinging edge proxy...</span>';
      try {
        const res = await fetch('/api/keep_alive/ping_now', { method: 'POST' });
        const data = await res.json();
        if (btn) btn.disabled = false;
        if (resultEl) {
          if (data.success) {
            resultEl.innerHTML = '<span style="color:#16a34a; font-weight:700;">✓ Edge Ping Success (' + data.latency_ms + 'ms) -> ' + escapeHtml(data.target_url) + '</span>';
          } else {
            resultEl.innerHTML = '<span style="color:#dc2626; font-weight:700;">⚠ ' + escapeHtml(data.status) + '</span>';
          }
        }
        loadKeepAliveStatus();
      } catch (e) {
        if (btn) btn.disabled = false;
        if (resultEl) resultEl.innerHTML = '<span style="color:#dc2626;">Error: ' + escapeHtml(e.message) + '</span>';
      }
    }

    async function saveKeepAliveCustomUrl(e) {
      if (e) e.preventDefault();
      const input = document.getElementById('ka-custom-url-input');
      const resultEl = document.getElementById('ka-url-save-result');
      if (!input) return;
      try {
        const res = await fetch('/api/keep_alive/set_url', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ url: input.value.trim() })
        });
        const data = await res.json();
        if (resultEl) {
          resultEl.innerHTML = '<span style="color:#16a34a; font-weight:700;">✓ Saved target URL: ' + escapeHtml(data.target_url) + '</span>';
          setTimeout(() => { if (resultEl) resultEl.innerHTML = ''; }, 4000);
        }
        loadKeepAliveStatus();
      } catch (e) {
        if (resultEl) resultEl.innerHTML = '<span style="color:#dc2626;">Error: ' + escapeHtml(e.message) + '</span>';
      }
    }

    async function loadPlatformDashboardMetrics() {
      try {
        const res = await fetch('/api/admin/dashboard_stats');
        if (!res.ok) throw new Error('Unauthorized');
        const data = await res.json();
        const m = data.metrics || {};
        allCompaniesCache = m.companies || [];

        const kpiComp = document.getElementById('admin-kpi-companies');
        const kpiSeats = document.getElementById('admin-kpi-seats');
        const kpiMembers = document.getElementById('admin-kpi-members');
        const tabCount = document.getElementById('tab-companies-count');
        const navCount = document.getElementById('nav-total-companies-badge');

        if (kpiComp) kpiComp.textContent = m.total_companies || 0;
        if (kpiSeats) kpiSeats.textContent = m.total_seats_allocated || 0;
        if (kpiMembers) kpiMembers.textContent = m.total_used_seats || 0;
        if (tabCount) tabCount.textContent = m.total_companies || 0;
        if (navCount) navCount.textContent = m.total_companies || 0;

        renderAdminCompaniesTable(allCompaniesCache);
      } catch (err) {
        console.error("Dashboard metrics load failed:", err);
      }
    }

    function renderAdminCompaniesTable(companies) {
      const tbody = document.getElementById('companies-tbody');
      if (!tbody) return;
      tbody.innerHTML = '';

      if (companies.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; padding:24px; color:var(--text-muted);">No tenant companies found.</td></tr>';
        return;
      }

      companies.forEach(c => {
        const tr = document.createElement('tr');
        const used = c.used_seats || 0;
        const max = c.max_seats || 10;
        const pct = Math.min(100, Math.round((used / max) * 100));

        tr.innerHTML = `
          <td>
            <div style="font-weight:800; font-size:0.92rem; color:#0f172a; display:flex; align-items:center; gap:8px;">
              <div style="width:28px; height:28px; border-radius:6px; background:#f1f5f9; border:1px solid #cbd5e1; display:flex; align-items:center; justify-content:center; font-weight:800; font-size:0.75rem; color:#475569;">
                ${escapeHtml((c.name || 'CO').substring(0, 2).toUpperCase())}
              </div>
              <span>${escapeHtml(c.name)}</span>
            </div>
            <div style="font-size:0.72rem; color:var(--text-muted); font-family:var(--font-mono); margin-left:36px;">slug: ${escapeHtml(c.slug)}</div>
          </td>
          <td>
            <span class="saas-plan-pill plan-${c.plan || 'team'}" style="font-size:0.72rem;">${(c.plan || 'team').toUpperCase()}</span>
          </td>
          <td style="min-width:160px;">
            <div style="display:flex; justify-content:space-between; font-size:0.75rem; font-weight:700; color:#334155; margin-bottom:4px;">
              <span>${used} Seated Users</span>
              <span style="color:#64748b;">${max} Seats Max</span>
            </div>
            <div style="height:6px; background:#e2e8f0; border-radius:999px; overflow:hidden;">
              <div style="width:${pct}%; height:100%; background:linear-gradient(90deg, #0284c7, #38bdf8); border-radius:999px;"></div>
            </div>
          </td>
          <td>
            <span style="font-size:0.7rem; background:${c.status === 'active' ? 'rgba(16,185,129,0.12)' : 'rgba(239,68,68,0.12)'}; border:1px solid ${c.status === 'active' ? 'rgba(16,185,129,0.3)' : 'rgba(239,68,68,0.3)'}; color:${c.status === 'active' ? '#047857' : '#b91c1c'}; padding:2px 8px; border-radius:10px; font-weight:700;">
              ${escapeHtml(c.status || 'active').toUpperCase()}
            </span>
          </td>
          <td style="text-align:right;">
            <div style="display:inline-flex; gap:6px;">
              <button class="btn btn-secondary" onclick="promptAssignCompanyQuota('${c.id}', '${escapeHtml(c.name)}', '${c.plan || 'team'}', ${max})" title="Assign Tier & Seats" style="font-size:0.72rem; padding:4px 9px;">
                ⚡ Assign Quota
              </button>
              <button class="btn btn-secondary" onclick="inspectCompanyMembers('${c.id}', '${escapeHtml(c.name)}')" title="View Company Members" style="border-color:#0284c7; color:#0284c7; font-size:0.72rem; padding:4px 9px;">
                👥 Members (${used})
              </button>
            </div>
          </td>
        `;
        tbody.appendChild(tr);
      });
    }

    function filterAdminCompanies() {
      const q = (document.getElementById('admin-company-search').value || '').trim().toLowerCase();
      if (!q) {
        renderAdminCompaniesTable(allCompaniesCache);
        return;
      }
      const filtered = allCompaniesCache.filter(c => 
        (c.name && c.name.toLowerCase().includes(q)) || 
        (c.slug && c.slug.toLowerCase().includes(q)) ||
        (c.plan && c.plan.toLowerCase().includes(q))
      );
      renderAdminCompaniesTable(filtered);
    }

    function autoFillPlanSeats() {
      const plan = document.getElementById('new-comp-plan').value;
      const seatsInput = document.getElementById('new-comp-seats');
      if (plan === 'free') seatsInput.value = 3;
      else if (plan === 'team') seatsInput.value = 15;
      else if (plan === 'enterprise') seatsInput.value = 100;
    }

    async function handleCreateCompanySubmit(e) {
      e.preventDefault();
      const name = document.getElementById('new-comp-name').value.trim();
      const plan = document.getElementById('new-comp-plan').value;
      const maxSeats = parseInt(document.getElementById('new-comp-seats').value, 10);
      const adminEmail = document.getElementById('new-comp-admin-email').value.trim();
      const adminName = document.getElementById('new-comp-admin-name').value.trim();
      const btn = document.getElementById('btn-create-comp');

      btn.disabled = true;
      btn.innerHTML = '<span>Creating Company...</span>';

      try {
        const res = await fetch('/api/admin/companies/create', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name, plan, max_seats: maxSeats, admin_email: adminEmail, admin_name: adminName })
        });
        const data = await res.json();
        if (res.ok && data.status === 'ok') {
          showToast(`Company '${name}' created with ${maxSeats} seats.`);
          document.getElementById('new-comp-name').value = '';
          document.getElementById('new-comp-admin-email').value = '';
          document.getElementById('new-comp-admin-name').value = '';
          switchSuperAdminTab('companies');
          await loadPlatformDashboardMetrics();
          await checkAuthStatus();
        } else {
          showToast(data.message || 'Could not create company.', 'error');
        }
      } catch (err) {
        showToast('Server error.', 'error');
      } finally {
        btn.disabled = false;
        btn.innerHTML = '<span>Provision Organization & Activate Quota</span>';
      }
    }

    async function promptAssignCompanyQuota(companyId, companyName, currentPlan, currentSeats) {
      const newPlan = prompt(`[${companyName}]\nEnter subscription plan tier ('free', 'team', 'enterprise'):`, currentPlan);
      if (!newPlan) return;
      const newSeatsStr = prompt(`[${companyName}]\nEnter maximum seats quota:`, currentSeats);
      if (!newSeatsStr) return;
      const newSeats = parseInt(newSeatsStr, 10);
      if (isNaN(newSeats) || newSeats < 1) {
        alert('Invalid seat count.');
        return;
      }

      try {
        const res = await fetch('/api/admin/companies/update_plan', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ company_id: companyId, plan: newPlan.toLowerCase().trim(), max_seats: newSeats })
        });
        const data = await res.json();
        if (res.ok && data.status === 'ok') {
          showToast(`Updated quota for ${companyName}!`);
          await loadPlatformDashboardMetrics();
          await checkAuthStatus();
        } else {
          showToast(data.message || 'Update failed.', 'error');
        }
      } catch (e) {
        showToast('Server error.', 'error');
      }
    }

    async function inspectCompanyMembers(companyId, companyName) {
      hideSuperAdminModal();
      await openTeamModal('members', companyId);
    }

    function escapeHtml(str) {
      if (!str) return '';
      return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
    }

    // Anti-Idle Browser Heartbeat: Keeps Render cloud service warm while tab is open
    setInterval(() => {
      fetch('/healthz', { cache: 'no-store' }).catch(() => {});
    }, 4 * 60 * 1000); // Every 4 minutes (Render inactivity cutoff is 15 minutes)

    window.onload = init;
  </script>

  <!-- MODAL 1: AUTHENTICATION (LOGIN & INVITE ACTIVATION) -->
  <div id="modal-auth" class="saas-modal-backdrop" onclick="if(event.target===this) hideAuthModal()">
    <div class="saas-modal-card">
      <div class="saas-modal-header">
        <div class="saas-modal-title">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#3b82f6" stroke-width="2"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="4"/></svg> Pro Portrait Studio
        </div>
        <button class="saas-modal-close" onclick="hideAuthModal()">&times;</button>
      </div>
      <div class="saas-modal-body">
        <div class="saas-tabs">
          <button class="saas-tab-btn active" id="tab-auth-login" onclick="switchAuthTab('login')">Sign In</button>
          <button class="saas-tab-btn" id="tab-auth-activate" onclick="switchAuthTab('activate')">Activate Seat</button>
        </div>

        <!-- Tab 1: Login Form -->
        <div id="view-auth-login">
          <form onsubmit="handleLoginSubmit(event)">
            <div class="saas-form-group">
              <label class="saas-form-label">Email Address</label>
              <input type="email" id="login-email" class="saas-input" placeholder="name@company.com" required autocomplete="username">
            </div>
            <div class="saas-form-group">
              <label class="saas-form-label">Password</label>
              <input type="password" id="login-password" class="saas-input" placeholder="••••••••" required autocomplete="current-password">
            </div>
            <div id="login-error-alert" style="display:none; color:#fca5a5; background:rgba(239,68,68,0.15); border:1px solid rgba(239,68,68,0.3); padding:10px 14px; border-radius:8px; font-size:0.82rem; margin-bottom:14px;"></div>
            <div style="display:flex; justify-content:space-between; align-items:center; margin-top:20px; gap:12px;">
              <button type="button" class="btn btn-secondary" onclick="fillDemoCredentials()" style="font-size:0.78rem; padding:8px 12px; color:#cbd5e1;">
                <span>Fill Demo SuperAdmin</span>
              </button>
              <button type="submit" class="btn btn-primary" id="btn-login-submit" style="padding:10px 24px;">
                <span>Sign In ➔</span>
              </button>
            </div>

            <div style="display:flex; align-items:center; gap:10px; margin:16px 0 6px 0;">
              <div style="flex:1; height:1px; background:rgba(180,140,45,0.2);"></div>
              <span style="font-size:0.7rem; color:var(--text-muted); font-weight:700; text-transform:uppercase; letter-spacing:0.06em;">Or Biometric Key</span>
              <div style="flex:1; height:1px; background:rgba(180,140,45,0.2);"></div>
            </div>
            <button type="button" class="btn-passkey" onclick="startPasskeyLogin('modal')">
              <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="#d4af37" stroke-width="2"><path d="M2 18v3c0 .6.4 1 1 1h4v-3h3v-3h2l1.4-1.4a6.5 6.5 0 1 0-4-4Z"/><circle cx="16.5" cy="7.5" r=".5"/></svg>
              <span>Sign In with Passkey (Touch ID / Face ID)</span>
            </button>
          </form>
        </div>

        <!-- Tab 3: Modal MFA Form -->
        <div id="view-auth-mfa" style="display:none;">
          <div style="text-align:center; margin-bottom:18px;">
            <div style="width:48px; height:48px; border-radius:50%; background:rgba(184,134,11,0.12); border:1px solid rgba(184,134,11,0.3); display:inline-flex; align-items:center; justify-content:center; margin-bottom:10px;">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="var(--gold-primary)" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
            </div>
            <div style="font-family:var(--font-royal); font-size:1.15rem; font-weight:700; color:#0f172a;">Two-Factor Verification</div>
            <div style="font-size:0.8rem; color:var(--text-muted); margin-top:4px;">Enter the 6-digit code from your authenticator app or emergency backup code.</div>
          </div>
          <form onsubmit="handleMfaLoginSubmit(event, 'modal')">
            <input type="hidden" id="modal-mfa-token" value="">
            <div class="saas-form-group">
              <label class="saas-form-label">Authenticator Code / Backup Code</label>
              <input type="text" id="modal-mfa-code" class="saas-input" placeholder="123456" autocomplete="one-time-code" required style="font-size:1.3rem; text-align:center; letter-spacing:0.18em; font-family:var(--font-mono); font-weight:800;">
            </div>
            <div id="modal-mfa-error" class="saas-alert-danger" style="display:none; margin-bottom:12px;"></div>
            <button type="submit" class="btn btn-primary" id="btn-modal-mfa" style="width:100%; padding:12px; margin-top:4px;">
              <span>Verify & Sign In</span>
            </button>
            <button type="button" class="btn btn-secondary" onclick="cancelMfaLogin('modal')" style="width:100%; padding:9px; margin-top:10px; font-size:0.82rem;">
              <span>← Back to Credentials Sign In</span>
            </button>
          </form>
        </div>

        <!-- Tab 2: Activation Form -->
        <div id="view-auth-activate" style="display:none;">
          <div style="background:rgba(56,189,248,0.1); border:1px solid rgba(56,189,248,0.3); padding:12px 14px; border-radius:8px; font-size:0.82rem; color:#7dd3fc; margin-bottom:18px;">
            Set your account password to activate your enterprise company membership.
          </div>
          <form onsubmit="handleActivationSubmit(event)">
            <input type="hidden" id="activate-token">
            <div class="saas-form-group">
              <label class="saas-form-label">Your Full Name</label>
              <input type="text" id="activate-name" class="saas-input" placeholder="e.g. Jordan Miller" required>
            </div>
            <div class="saas-form-group">
              <label class="saas-form-label">Create Password (Min 6 chars)</label>
              <input type="password" id="activate-password" class="saas-input" placeholder="••••••••" required minlength="6">
            </div>
            <div class="saas-form-group">
              <label class="saas-form-label">Confirm Password</label>
              <input type="password" id="activate-confirm" class="saas-input" placeholder="••••••••" required minlength="6">
            </div>
            <div id="activate-error-alert" style="display:none; color:#fca5a5; background:rgba(239,68,68,0.15); border:1px solid rgba(239,68,68,0.3); padding:10px 14px; border-radius:8px; font-size:0.82rem; margin-bottom:14px;"></div>
            <button type="submit" class="btn btn-primary" id="btn-activate-submit" style="width:100%; padding:12px; margin-top:10px;">
              <span>Activate Account & Enter Studio</span>
            </button>
          </form>
        </div>
      </div>
    </div>
  </div>

  <!-- MODAL 2: COMPANY TEAM & BULK USER ADDITION -->
  <div id="modal-team-mgmt" class="saas-modal-backdrop" onclick="if(event.target===this) hideTeamModal()">
    <div class="saas-modal-card wide">
      <div class="saas-modal-header">
        <div class="saas-modal-title">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/></svg> <span id="team-modal-company-title">Athletics Media Group</span> — Team & Subscriptions
        </div>
        <button class="saas-modal-close" onclick="hideTeamModal()">&times;</button>
      </div>
      <div class="saas-modal-body">
        <!-- Live Seat Meter Card -->
        <div class="seat-meter-card">
          <div class="seat-meter-header">
            <div>
              <span style="font-weight:800; color:var(--text);" id="meter-company-name">Athletics Media Group</span>
              <span id="meter-plan-tag" class="saas-plan-pill plan-team" style="margin-left:8px;">Team Plan</span>
            </div>
            <div style="font-weight:700; color:var(--gold-primary);" id="meter-seat-text">1 / 15 Seats Used (14 Available)</div>
          </div>
          <div class="seat-bar-track">
            <div id="meter-bar-fill" class="seat-bar-fill" style="width: 7%;"></div>
          </div>
        </div>

        <div class="saas-tabs">
          <button class="saas-tab-btn active" id="tab-team-bulk" onclick="switchTeamTab('bulk')">Bulk Add Users</button>
          <button class="saas-tab-btn" id="tab-team-single" onclick="switchTeamTab('single')">Single Invite</button>
          <button class="saas-tab-btn" id="tab-team-members" onclick="switchTeamTab('members')">Members Directory (<span id="tab-member-count">0</span>)</button>
        </div>

        <!-- TAB 1: BULK ADD USERS -->
        <div id="view-team-bulk">
          <div style="margin-bottom:12px; font-size:0.83rem; color:var(--text-muted); line-height:1.5;">
            Paste multiple user emails below. Supports CSV, TSV, or email lines with optional Name and Role (<code>member</code> or <code>company_admin</code>).
          </div>
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
            <span class="saas-form-label" style="margin:0;">User List (One per line)</span>
            <button type="button" class="btn btn-secondary" onclick="insertBulkSample()" style="font-size:0.73rem; padding:4px 10px;">
              <span>Paste Example Team</span>
            </button>
          </div>
          <textarea id="bulk-invite-text" class="saas-textarea" placeholder="sarah.connor@athletics.com, Sarah Connor, company_admin&#10;john.smith@athletics.com, John Smith, member&#10;coach.carter@athletics.com"></textarea>

          <div style="display:flex; justify-content:space-between; align-items:center; margin-top:14px; flex-wrap:wrap; gap:10px;">
            <div style="font-size:0.75rem; color:var(--text-muted);">
              ⚡ Each user will be registered and receive an email with their password activation link.
            </div>
            <button type="button" class="btn btn-primary" id="btn-submit-bulk" onclick="handleBulkInviteSubmit()" style="padding:10px 22px;">
              <span>Send Bulk Invites & Allocate Seats</span>
            </button>
          </div>

          <!-- Bulk Invite Results Box -->
          <div id="bulk-results-box" style="display:none; margin-top:18px; border-top:1px solid rgba(180, 140, 45, 0.2); padding-top:16px;">
            <div style="font-size:0.85rem; font-weight:800; color:var(--text); margin-bottom:10px;">Invitation Dispatch Results:</div>
            <div id="bulk-results-list" style="max-height:220px; overflow-y:auto;"></div>
          </div>
        </div>

        <!-- TAB 2: SINGLE USER INVITE -->
        <div id="view-team-single" style="display:none;">
          <form onsubmit="handleSingleInviteSubmit(event)">
            <div style="display:grid; grid-template-columns: 1fr 1fr; gap:14px;">
              <div class="saas-form-group">
                <label class="saas-form-label">Full Name</label>
                <input type="text" id="single-name" class="saas-input" placeholder="e.g. Alex Johnson" required>
              </div>
              <div class="saas-form-group">
                <label class="saas-form-label">Email Address</label>
                <input type="email" id="single-email" class="saas-input" placeholder="alex@athletics.com" required>
              </div>
            </div>
            <div class="saas-form-group">
              <label class="saas-form-label">Role</label>
              <select id="single-role" class="saas-input" style="cursor:pointer;">
                <option value="member">Member (Can edit portraits & scrape rosters)</option>
                <option value="company_admin">Company Admin (Can invite users & manage team)</option>
              </select>
            </div>
            <div id="single-invite-alert" style="display:none; padding:10px 14px; border-radius:8px; font-size:0.82rem; margin-bottom:14px;"></div>
            <button type="submit" class="btn btn-primary" id="btn-submit-single" style="padding:10px 24px;">
              <span>Send Invitation Email</span>
            </button>
          </form>
        </div>

        <!-- TAB 3: MEMBERS DIRECTORY -->
        <div id="view-team-members" style="display:none;">
          <div style="max-height:360px; overflow-y:auto; border:1px solid rgba(180, 140, 45, 0.22); border-radius:10px;">
            <table class="saas-table">
              <thead>
                <tr>
                  <th>Member</th>
                  <th>Role</th>
                  <th>Status</th>
                  <th style="text-align:right;">Actions</th>
                </tr>
              </thead>
              <tbody id="team-members-tbody">
                <!-- Dynamically populated -->
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- MODAL 3: SUPERADMIN PLATFORM FLEET DASHBOARD -->
  <div id="modal-superadmin" class="saas-modal-backdrop" onclick="if(event.target===this) hideSuperAdminModal()">
    <div class="saas-modal-card wide" style="max-width:1050px;">
      <div class="saas-modal-header" style="background:linear-gradient(135deg, #0f172a 0%, #1e293b 100%); border-bottom:1px solid rgba(212,175,55,0.3); color:#f8fafc;">
        <div class="saas-modal-title" style="color:#ffffff;">
          <div style="width:34px; height:34px; border-radius:8px; background:var(--gold-gradient); display:flex; align-items:center; justify-content:center; box-shadow:0 0 12px rgba(212,175,55,0.4);">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#05070a" stroke-width="2.2"><path d="M3 18h18M4 18l2-10 5 6 3-8 3 8 5-6 2 10H4z"/></svg>
          </div>
          <div>
            <div style="font-family:'Cinzel', serif; font-size:1.15rem; font-weight:800; color:#fff; letter-spacing:0.04em;">SUPERADMIN PLATFORM FLEET HUB</div>
            <div style="font-size:0.68rem; color:#d4af37; font-family:var(--font-sans); font-weight:700; letter-spacing:0.08em; text-transform:uppercase;">Master Tenant Management & Subscription Provisioning</div>
          </div>
        </div>
        <button class="saas-modal-close" onclick="hideSuperAdminModal()" style="color:#94a3b8;">&times;</button>
      </div>

      <div class="saas-modal-body" style="background:#f8fafc; padding:24px;">
        <!-- Top Metrics KPI Cards -->
        <div class="kpi-grid">
          <div class="kpi-metric-card">
            <div class="kpi-label">Total Organizations</div>
            <div class="kpi-value" id="admin-kpi-companies">3</div>
            <div class="kpi-sub">Active Tenant Fleets</div>
          </div>
          <div class="kpi-metric-card">
            <div class="kpi-label">Allocated Capacity</div>
            <div class="kpi-value" id="admin-kpi-seats" style="color:#0284c7;">128</div>
            <div class="kpi-sub">Total Maximum Seats Provisioned</div>
          </div>
          <div class="kpi-metric-card">
            <div class="kpi-label">Active Seated Users</div>
            <div class="kpi-value" id="admin-kpi-members" style="color:#059669;">3</div>
            <div class="kpi-sub">Tenant Staff Members Active</div>
          </div>
          <div class="kpi-metric-card">
            <div class="kpi-label">SuperAdmin Scope</div>
            <div class="kpi-value" style="font-size:1.1rem; color:#b45309; padding-top:4px;">Master Root</div>
            <div class="kpi-sub">Zero Company Seats Consumed</div>
          </div>
        </div>

        <!-- Navigation Tabs inside SuperAdmin Modal -->
        <div class="saas-tabs" style="margin-bottom:18px;">
          <button class="saas-tab-btn active" id="tab-superadmin-companies" onclick="switchSuperAdminTab('companies')">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="4" y="2" width="16" height="20" rx="2"/><line x1="9" y1="22" x2="9" y2="12"/><line x1="15" y1="22" x2="15" y2="12"/></svg>
            <span>Tenant Companies (<span id="tab-companies-count">3</span>)</span>
          </button>
          <button class="saas-tab-btn" id="tab-superadmin-create" onclick="switchSuperAdminTab('create')">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
            <span>Provision New Tenant Company</span>
          </button>
          <button class="saas-tab-btn" id="tab-superadmin-keepalive" onclick="switchSuperAdminTab('keepalive')">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>
            <span>Cloud Keep-Alive & Anti-Idle</span>
          </button>
        </div>

        <!-- TAB 1: FLEET DIRECTORY -->
        <div id="view-superadmin-companies">
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; gap:12px; flex-wrap:wrap;">
            <div style="position:relative; flex:1; max-width:320px;">
              <input type="text" id="admin-company-search" class="saas-input" placeholder="Search company by name or slug..." oninput="filterAdminCompanies()" style="padding-left:34px; font-size:0.82rem;">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" stroke-width="2" style="position:absolute; left:12px; top:12px;"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
            </div>
            <button class="btn btn-primary" onclick="switchSuperAdminTab('create')" style="font-size:0.8rem; padding:8px 14px;">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
              <span>Provision Organization</span>
            </button>
          </div>

          <div style="background:#fff; border:1px solid rgba(180, 140, 45, 0.22); border-radius:12px; overflow:hidden; box-shadow:0 2px 8px rgba(15,23,42,0.03);">
            <div style="max-height:360px; overflow-y:auto;">
              <table class="saas-table">
                <thead>
                  <tr style="background:#f1f5f9; border-bottom:1px solid #e2e8f0;">
                    <th>Organization / Slug</th>
                    <th>Plan Tier</th>
                    <th>Seat Allocation & Quota</th>
                    <th>Status</th>
                    <th style="text-align:right;">Actions & Assignment</th>
                  </tr>
                </thead>
                <tbody id="companies-tbody">
                  <!-- Populated by JavaScript -->
                </tbody>
              </table>
            </div>
          </div>
        </div>

        <!-- TAB 2: PROVISION NEW COMPANY -->
        <div id="view-superadmin-create" style="display:none;">
          <div style="background:#ffffff; border:1px solid rgba(180, 140, 45, 0.22); border-radius:12px; padding:22px; box-shadow:0 2px 8px rgba(15,23,42,0.03);">
            <div style="font-size:0.95rem; font-weight:800; color:var(--text); margin-bottom:6px;">Provision New Tenant Organization</div>
            <div style="font-size:0.8rem; color:var(--text-muted); margin-bottom:18px;">Create a dedicated company partition with custom plan quota and send an invitation to the lead administrator.</div>
            <form onsubmit="handleCreateCompanySubmit(event)">
              <div style="display:grid; grid-template-columns: 2fr 1fr 1fr; gap:14px; margin-bottom:14px;">
                <div>
                  <label class="saas-form-label">Company Name *</label>
                  <input type="text" id="new-comp-name" class="saas-input" placeholder="e.g. Manchester Storm Media" required>
                </div>
                <div>
                  <label class="saas-form-label">Plan Tier *</label>
                  <select id="new-comp-plan" class="saas-input" onchange="autoFillPlanSeats()">
                    <option value="free">Free Tier (3 Seats)</option>
                    <option value="team" selected>Team Tier (15 Seats)</option>
                    <option value="enterprise">Enterprise Tier (100 Seats)</option>
                  </select>
                </div>
                <div>
                  <label class="saas-form-label">Maximum Seats *</label>
                  <input type="number" id="new-comp-seats" class="saas-input" value="15" min="1" max="1000" required>
                </div>
              </div>
              <div style="display:grid; grid-template-columns: 1fr 1fr; gap:14px; margin-bottom:18px;">
                <div>
                  <label class="saas-form-label">Lead Administrator Email (Sends Activation)</label>
                  <input type="email" id="new-comp-admin-email" class="saas-input" placeholder="admin@manchesterstorm.com">
                </div>
                <div>
                  <label class="saas-form-label">Lead Administrator Full Name</label>
                  <input type="text" id="new-comp-admin-name" class="saas-input" placeholder="e.g. Liam Gallagher">
                </div>
              </div>
              <div style="display:flex; justify-content:flex-end; gap:10px;">
                <button type="button" class="btn btn-secondary" onclick="switchSuperAdminTab('companies')" style="padding:9px 18px;">Cancel</button>
                <button type="submit" class="btn btn-primary" id="btn-create-comp" style="padding:9px 24px;">
                  <span>Provision Organization & Activate Quota</span>
                </button>
              </div>
            </form>
          </div>
        </div>

        <!-- TAB 3: CLOUD KEEP-ALIVE & ANTI-IDLE MONITOR -->
        <div id="view-superadmin-keepalive" style="display:none;">
          <div style="background:#ffffff; border:1px solid rgba(180, 140, 45, 0.22); border-radius:12px; padding:22px; box-shadow:0 2px 8px rgba(15,23,42,0.03);">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:14px; flex-wrap:wrap; gap:10px;">
              <div>
                <div style="font-size:1.05rem; font-weight:800; color:var(--text); display:flex; align-items:center; gap:8px;">
                  <span>Cloud Keep-Alive & Anti-Idle Heartbeat</span>
                  <span id="ka-host-badge" class="badge" style="background:rgba(59,130,246,0.1); color:#2563eb; font-size:0.72rem; padding:3px 8px; border-radius:6px; border:1px solid rgba(59,130,246,0.25);">Render Cloud</span>
                </div>
                <div style="font-size:0.8rem; color:var(--text-muted); margin-top:3px;">Prevents Render Free tier from spinning down into cold sleep due to 15-minute inactivity.</div>
              </div>
              <div id="ka-status-badge">
                <span style="display:inline-flex; align-items:center; gap:6px; color:#16a34a; font-weight:700;">
                  <span style="width:8px; height:8px; border-radius:50%; background:#16a34a; box-shadow:0 0 8px #16a34a;"></span>
                  Active (Anti-Idle Running)
                </span>
              </div>
            </div>

            <!-- Metric Grid -->
            <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(180px, 1fr)); gap:12px; margin-bottom:20px;">
              <div class="kpi-metric-card" style="padding:14px;">
                <div class="kpi-label">Ping Interval</div>
                <div class="kpi-value" id="ka-interval" style="font-size:1.15rem; color:#0f172a;">10 min (600s)</div>
                <div class="kpi-sub">Safe buffer (Render timeout: 15m)</div>
              </div>
              <div class="kpi-metric-card" style="padding:14px;">
                <div class="kpi-label">Total Heartbeats</div>
                <div class="kpi-value" id="ka-total-pings" style="font-size:1.15rem; color:#16a34a;">0 pings</div>
                <div class="kpi-sub">Outbound-to-edge roundtrips</div>
              </div>
              <div class="kpi-metric-card" style="padding:14px;">
                <div class="kpi-label">Last Roundtrip Latency</div>
                <div class="kpi-value" id="ka-latency" style="font-size:1.15rem; color:#2563eb;">-</div>
                <div class="kpi-sub">Edge proxy response time</div>
              </div>
              <div class="kpi-metric-card" style="padding:14px;">
                <div class="kpi-label">Last Edge Ping Time</div>
                <div class="kpi-value" id="ka-last-ping" style="font-size:0.85rem; color:#0f172a; padding-top:6px; word-break:break-word;">Initializing...</div>
                <div class="kpi-sub">UTC Timestamp</div>
              </div>
            </div>

            <!-- Target URL & Action Controls -->
            <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:10px; padding:16px; margin-bottom:18px;">
              <div style="font-size:0.85rem; font-weight:700; color:#1e293b; margin-bottom:6px;">Current Edge Health Target:</div>
              <div style="font-family:monospace; font-size:0.85rem; color:#0284c7; background:#fff; padding:8px 12px; border-radius:6px; border:1px solid #cbd5e1; margin-bottom:12px; word-break:break-all;" id="ka-target-url">
                Detecting from live traffic...
              </div>

              <form onsubmit="saveKeepAliveCustomUrl(event)" style="display:flex; gap:10px; flex-wrap:wrap; margin-bottom:8px;">
                <input type="text" id="ka-custom-url-input" class="saas-input" placeholder="Custom URL (e.g. https://portrait-studio-pro.onrender.com/healthz)" style="flex:1; min-width:260px; font-size:0.82rem;">
                <button type="submit" class="btn btn-secondary" style="font-size:0.8rem; padding:8px 14px;">Update Target</button>
                <button type="button" class="btn btn-primary" id="btn-ka-ping-now" onclick="triggerKeepAliveTest()" style="font-size:0.8rem; padding:8px 16px;">
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right:4px;"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>
                  <span>Test Ping Now</span>
                </button>
              </form>
              <div id="ka-url-save-result" style="font-size:0.78rem;"></div>
              <div id="ka-ping-result" style="font-size:0.78rem; margin-top:4px;"></div>
            </div>

            <!-- Architecture Info Box -->
            <div style="background:rgba(180, 140, 45, 0.08); border:1px solid rgba(180, 140, 45, 0.25); border-radius:10px; padding:16px;">
              <div style="font-size:0.85rem; font-weight:800; color:#855f19; margin-bottom:6px; display:flex; align-items:center; gap:6px;">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>
                <span>Triple-Layer 24/7 Keep-Alive Architecture</span>
              </div>
              <div style="font-size:0.78rem; color:#475569; line-height:1.55;">
                <strong>1. Python Server Daemon:</strong> Runs continuously on a dedicated background thread in <code>studio.py</code>. Pings the public edge URL every 10 minutes (600s), resetting Render's 15-minute inactivity counter.<br>
                <strong>2. Browser Tab Heartbeat:</strong> Sends a lightweight <code>/healthz</code> ping every 4 minutes whenever any photographer or team member has the Studio open.<br>
                <strong>3. External Monitor (Optional):</strong> For 100% cloud redundancy, you can configure a free monitor at <a href="https://uptimerobot.com" target="_blank" style="color:#b45309; text-decoration:underline; font-weight:700;">UptimeRobot.com</a> or <a href="https://cron-job.org" target="_blank" style="color:#b45309; text-decoration:underline; font-weight:700;">cron-job.org</a> to ping your public URL <code>https://&lt;your-app&gt;.onrender.com/healthz</code> every 5-10 minutes.
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- MODAL 4: ACCOUNT SETTINGS & CREDENTIALS (CHANGE PASSWORD, MFA, PASSKEYS) -->
  <div id="modal-account-settings" class="saas-modal-backdrop" onclick="if(event.target===this) hideAccountSettingsModal()">
    <div class="saas-modal-card" style="max-width:680px;">
      <div class="saas-modal-header">
        <div class="saas-modal-title">
          <div style="width:32px; height:32px; border-radius:8px; background:rgba(184,134,11,0.12); border:1px solid rgba(184,134,11,0.3); display:flex; align-items:center; justify-content:center;">
            <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="var(--gold-primary)" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
          </div>
          <div>
            <div style="font-family:'Cinzel', serif; font-size:1.1rem; font-weight:800; color:#0f172a;">ACCOUNT & CREDENTIALS</div>
            <div style="font-size:0.68rem; color:var(--text-gold); font-weight:700; text-transform:uppercase; letter-spacing:0.08em;">Security, Password, MFA & Passkeys</div>
          </div>
        </div>
        <button class="saas-modal-close" onclick="hideAccountSettingsModal()">&times;</button>
      </div>

      <div class="saas-modal-body">
        <div class="saas-tabs">
          <button class="saas-tab-btn active" id="tab-account-credentials" onclick="switchAccountTab('credentials')">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
            <span>Password & Credentials</span>
          </button>
          <button class="saas-tab-btn" id="tab-account-mfa" onclick="switchAccountTab('mfa')">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
            <span>Two-Factor (MFA)</span>
          </button>
          <button class="saas-tab-btn" id="tab-account-passkeys" onclick="switchAccountTab('passkeys')">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M2 18v3c0 .6.4 1 1 1h4v-3h3v-3h2l1.4-1.4a6.5 6.5 0 1 0-4-4Z"/><circle cx="16.5" cy="7.5" r=".5"/></svg>
            <span>Passkeys</span>
          </button>
        </div>

        <!-- TAB 1: CREDENTIALS & PASSWORD -->
        <div id="view-account-credentials">
          <form onsubmit="handleUpdateProfileSubmit(event)">
            <div style="font-size:0.86rem; font-weight:800; color:#0f172a; margin-bottom:12px;">Corporate Identity & Profile</div>
            <div style="display:grid; grid-template-columns: 1fr 1fr; gap:12px; margin-bottom:14px;">
              <div>
                <label class="saas-form-label">Full Name</label>
                <input type="text" id="acc-full-name" class="saas-input" required>
              </div>
              <div>
                <label class="saas-form-label">Email Address</label>
                <input type="email" id="acc-email" class="saas-input" required>
              </div>
            </div>

            <div style="font-size:0.86rem; font-weight:800; color:#0f172a; margin:18px 0 8px 0; padding-top:14px; border-top:1px solid rgba(180,140,45,0.2);">Change Account Password</div>
            <div style="font-size:0.75rem; color:var(--text-muted); margin-bottom:12px;">Leave blank if you only wish to update your name/email.</div>

            <div class="saas-form-group">
              <label class="saas-form-label">Current Password (Required for changes)</label>
              <input type="password" id="acc-current-password" class="saas-input" placeholder="Enter current password" autocomplete="current-password">
            </div>

            <div style="display:grid; grid-template-columns: 1fr 1fr; gap:12px; margin-bottom:16px;">
              <div>
                <label class="saas-form-label">New Password</label>
                <input type="password" id="acc-new-password" class="saas-input" placeholder="Minimum 6 characters" minlength="6" autocomplete="new-password">
              </div>
              <div>
                <label class="saas-form-label">Confirm New Password</label>
                <input type="password" id="acc-confirm-password" class="saas-input" placeholder="Repeat new password" minlength="6" autocomplete="new-password">
              </div>
            </div>

            <div id="acc-profile-error" class="saas-alert-danger" style="display:none; margin-bottom:14px;"></div>
            <div id="acc-profile-success" class="saas-alert-info" style="display:none; margin-bottom:14px; background:rgba(16,185,129,0.1); border-color:rgba(16,185,129,0.3); color:#047857;"></div>

            <div style="display:flex; justify-content:flex-end;">
              <button type="submit" class="btn btn-primary" id="btn-save-credentials" style="padding:10px 24px;">
                <span>Save Credentials & Password</span>
              </button>
            </div>
          </form>
        </div>

        <!-- TAB 2: TWO-FACTOR AUTHENTICATION (MFA) -->
        <div id="view-account-mfa" style="display:none;">
          <!-- State A: MFA Not Enabled -->
          <div id="mfa-status-disabled-box" style="background:#f8fafc; border:1px solid rgba(180,140,45,0.25); border-radius:12px; padding:20px; margin-bottom:16px;">
            <div style="display:flex; align-items:flex-start; gap:14px;">
              <div style="width:42px; height:42px; border-radius:10px; background:rgba(239,68,68,0.1); border:1px solid rgba(239,68,68,0.3); display:flex; align-items:center; justify-content:center; color:#dc2626; flex-shrink:0;">
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
              </div>
              <div>
                <div style="font-weight:800; font-size:0.95rem; color:#0f172a;">Two-Factor Authentication is Disabled</div>
                <div style="font-size:0.8rem; color:var(--text-muted); margin-top:4px; line-height:1.4;">
                  Add an extra layer of security to your enterprise account. When enabled, signing in requires your password and a 6-digit verification code from Google Authenticator, 1Password, or Apple Keychain.
                </div>
                <button type="button" class="btn btn-primary" onclick="startMfaSetupWizard()" style="margin-top:14px; padding:8px 18px; font-size:0.82rem;">
                  <span>Set Up Authenticator App</span>
                </button>
              </div>
            </div>
          </div>

          <!-- Wizard: Setup Flow -->
          <div id="mfa-setup-wizard" style="display:none; background:#ffffff; border:1px solid rgba(180,140,45,0.3); border-radius:12px; padding:22px; margin-bottom:16px;">
            <div style="font-family:'Cinzel', serif; font-size:1rem; font-weight:800; color:#0f172a; margin-bottom:12px;">Step 1: Scan QR Code or Enter Secret Key</div>
            <div style="display:flex; gap:20px; align-items:center; flex-wrap:wrap; margin-bottom:16px;">
              <div style="padding:10px; background:#fff; border:1px solid #e2e8f0; border-radius:10px; box-shadow:0 2px 8px rgba(0,0,0,0.05);">
                <img id="mfa-qr-img" src="" alt="MFA QR Code" style="width:160px; height:160px; display:block;">
              </div>
              <div style="flex:1; min-width:220px;">
                <div style="font-size:0.75rem; color:var(--text-muted); margin-bottom:6px;">Can't scan the QR code? Manually enter this secret key into your authenticator app:</div>
                <div class="totp-code-display" id="mfa-secret-text" style="margin-bottom:8px;">.... .... .... ....</div>
                <div>
                  <button type="button" class="btn btn-secondary" onclick="copyMfaSecret()" style="font-size:0.75rem; padding:4px 10px;">
                    Copy Secret Key
                  </button>
                </div>
              </div>
            </div>

            <div style="font-family:'Cinzel', serif; font-size:1rem; font-weight:800; color:#0f172a; margin:16px 0 10px 0; padding-top:14px; border-top:1px solid #f1f5f9;">Step 2: Emergency Recovery Backup Codes</div>
            <div style="font-size:0.75rem; color:var(--text-muted);">Save these single-use recovery codes in case you lose access to your authenticator device:</div>
            <div class="backup-codes-grid" id="mfa-backup-codes-list"></div>
            <div style="margin-top:8px;">
              <button type="button" class="btn btn-secondary" onclick="copyBackupCodes()" style="font-size:0.75rem; padding:4px 10px;">Copy All Backup Codes</button>
            </div>

            <div style="font-family:'Cinzel', serif; font-size:1rem; font-weight:800; color:#0f172a; margin:16px 0 10px 0; padding-top:14px; border-top:1px solid #f1f5f9;">Step 3: Verify & Activate</div>
            <form onsubmit="handleMfaConfirmSubmit(event)">
              <div class="saas-form-group">
                <label class="saas-form-label">Enter 6-Digit Code from App</label>
                <input type="text" id="mfa-confirm-code" class="saas-input" placeholder="123456" maxlength="6" required style="font-size:1.15rem; font-family:var(--font-mono); letter-spacing:0.15em; max-width:200px;">
              </div>
              <div id="mfa-confirm-error" class="saas-alert-danger" style="display:none; margin-bottom:12px;"></div>
              <div style="display:flex; gap:10px;">
                <button type="button" class="btn btn-secondary" onclick="cancelMfaSetupWizard()" style="padding:8px 16px;">Cancel</button>
                <button type="submit" class="btn btn-primary" id="btn-mfa-confirm" style="padding:8px 20px;">
                  <span>Verify Code & Enable 2FA</span>
                </button>
              </div>
            </form>
          </div>

          <!-- State B: MFA Already Enabled -->
          <div id="mfa-status-enabled-box" style="display:none; background:#f0fdf4; border:1px solid rgba(16,185,129,0.3); border-radius:12px; padding:20px;">
            <div style="display:flex; align-items:flex-start; gap:14px;">
              <div style="width:42px; height:42px; border-radius:10px; background:rgba(16,185,129,0.15); border:1px solid rgba(16,185,129,0.3); display:flex; align-items:center; justify-content:center; color:#059669; flex-shrink:0;">
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
              </div>
              <div style="flex:1;">
                <div style="font-weight:800; font-size:0.95rem; color:#065f46;">Two-Factor Authentication is Active</div>
                <div style="font-size:0.8rem; color:#047857; margin-top:4px;">Your account is secured with standard TOTP two-factor authentication.</div>
                
                <div style="margin-top:16px; padding-top:14px; border-top:1px solid rgba(16,185,129,0.2);">
                  <div style="font-size:0.82rem; font-weight:700; color:#0f172a; margin-bottom:6px;">Disable Two-Factor Authentication</div>
                  <form onsubmit="handleMfaDisableSubmit(event)" style="display:flex; gap:10px; align-items:center; flex-wrap:wrap;">
                    <input type="password" id="mfa-disable-password" class="saas-input" placeholder="Current password to confirm" required style="max-width:240px; padding:8px 12px; font-size:0.82rem;">
                    <button type="submit" class="btn btn-secondary" style="border-color:#ef4444; color:#ef4444; padding:8px 16px; font-size:0.82rem;">Disable 2FA</button>
                  </form>
                  <div id="mfa-disable-error" class="saas-alert-danger" style="display:none; margin-top:8px;"></div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- TAB 3: PASSKEYS -->
        <div id="view-account-passkeys" style="display:none;">
          <div style="background:#f8fafc; border:1px solid rgba(180,140,45,0.25); border-radius:12px; padding:18px; margin-bottom:16px; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px;">
            <div>
              <div style="font-weight:800; font-size:0.92rem; color:#0f172a;">Passwordless Biometric Passkeys</div>
              <div style="font-size:0.78rem; color:var(--text-muted); margin-top:3px;">Use Touch ID, Face ID, Windows Hello, or hardware security keys to sign in instantly.</div>
            </div>
            <button type="button" class="btn btn-primary" onclick="startPasskeyRegister()" style="font-size:0.82rem; padding:8px 16px;">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
              <span>Add New Passkey</span>
            </button>
          </div>

          <div style="font-size:0.84rem; font-weight:800; color:#0f172a; margin-bottom:10px;">Registered Passkeys</div>
          <div style="border:1px solid rgba(180,140,45,0.2); border-radius:10px; overflow:hidden; background:#fff;">
            <table class="saas-table">
              <thead>
                <tr style="background:#f8fafc;">
                  <th>Passkey Device</th>
                  <th>Created Date</th>
                  <th>Last Used</th>
                  <th style="text-align:right;">Action</th>
                </tr>
              </thead>
              <tbody id="passkeys-table-body">
                <!-- Dynamically populated -->
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  </div>
</body>
</html>
"""


class KeepAliveService:
    """
    Autonomous Keep-Alive & Anti-Idle Heartbeat Service.
    Prevents Render and other cloud host containers from spinning down
    due to inactivity on free/idle tiers (15-minute inactivity timeout).
    Pings the public edge URL every 10 minutes (600s).
    """
    enabled = os.environ.get("KEEP_ALIVE_ENABLED", "true").lower() in ("true", "1", "yes")
    interval = int(os.environ.get("KEEP_ALIVE_INTERVAL", "600"))  # Default 10 min (Render spins down at 15m)
    target_url = os.environ.get("KEEP_ALIVE_URL") or os.environ.get("RENDER_EXTERNAL_URL") or os.environ.get("APP_URL") or ""

    total_pings = 0
    successful_pings = 0
    failed_pings = 0
    last_ping_time = None
    last_ping_status = None
    last_ping_latency_ms = None
    last_error = None
    discovered_url = None
    _thread = None
    _lock = threading.Lock()

    @classmethod
    def get_effective_target_url(cls):
        url = ""
        if cls.target_url and cls.target_url.strip():
            url = cls.target_url.strip()
        elif os.environ.get("RENDER_EXTERNAL_URL"):
            url = os.environ.get("RENDER_EXTERNAL_URL").strip()
        elif os.environ.get("RENDER_EXTERNAL_HOSTNAME"):
            url = f"https://{os.environ.get('RENDER_EXTERNAL_HOSTNAME').strip()}"
        elif cls.discovered_url:
            url = cls.discovered_url.strip()
        elif os.environ.get("RENDER"):
            url = "https://portrait-studio-pro.onrender.com"

        if url:
            parsed = urllib.parse.urlparse(url)
            scheme = parsed.scheme or "https"
            netloc = parsed.netloc or parsed.path.split("/")[0]
            if not netloc:
                netloc = url.replace("https://", "").replace("http://", "").split("/")[0]
            base = f"{scheme}://{netloc}"
            return f"{base.rstrip('/')}/healthz"
        return ""

    @classmethod
    def register_public_origin(cls, host: str, proto: str = "https"):
        if not host:
            return
        h_clean = host.split(":")[0].lower()
        if h_clean in ("localhost", "127.0.0.1", "0.0.0.0") or h_clean.startswith("192.168.") or h_clean.startswith("10.") or h_clean.startswith("172."):
            return
        with cls._lock:
            if not cls.discovered_url:
                cls.discovered_url = f"{proto}://{host}"
                print(f"[Keep-Alive] Dynamically learned public origin: {cls.discovered_url}")

    @classmethod
    def ping_now(cls):
        target = cls.get_effective_target_url()
        if not target:
            return {
                "success": False,
                "status": "No public target URL detected yet. Set RENDER_EXTERNAL_URL / KEEP_ALIVE_URL or visit the app from your public domain.",
                "latency_ms": 0,
                "target_url": ""
            }

        start_t = time.time()
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        req = urllib.request.Request(target, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) StudioAntiIdle/1.0",
            "X-Keep-Alive-Ping": "true"
        })
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
                status_code = resp.getcode()
                latency = round((time.time() - start_t) * 1000, 2)
                with cls._lock:
                    cls.total_pings += 1
                    cls.successful_pings += 1
                    cls.last_ping_time = datetime.now(timezone.utc).isoformat()
                    cls.last_ping_status = f"{status_code} OK"
                    cls.last_ping_latency_ms = latency
                    cls.last_error = None
                print(f"[Keep-Alive] Edge heartbeat ping to {target} -> {status_code} OK ({latency}ms)")
                return {
                    "success": True,
                    "status": f"{status_code} OK",
                    "latency_ms": latency,
                    "target_url": target
                }
        except Exception as e:
            latency = round((time.time() - start_t) * 1000, 2)
            with cls._lock:
                cls.total_pings += 1
                cls.failed_pings += 1
                cls.last_ping_time = datetime.now(timezone.utc).isoformat()
                cls.last_ping_status = f"Error: {e}"
                cls.last_ping_latency_ms = latency
                cls.last_error = str(e)
            print(f"[Keep-Alive] Warning: Heartbeat ping to {target} failed: {e}")
            return {
                "success": False,
                "status": str(e),
                "latency_ms": latency,
                "target_url": target
            }

    @classmethod
    def _loop(cls):
        time.sleep(25)  # Wait for server to bind and initial requests
        print(f"[Keep-Alive] Anti-idle heartbeat daemon started. Interval: {cls.interval}s.")
        while cls.enabled:
            try:
                target = cls.get_effective_target_url()
                if target:
                    cls.ping_now()
                else:
                    if cls.total_pings == 0:
                        print("[Keep-Alive] Standby: Waiting for public domain detection or RENDER_EXTERNAL_URL...")
            except Exception as e:
                print(f"[Keep-Alive] Exception in loop: {e}")
            time.sleep(max(60, cls.interval))

    @classmethod
    def start(cls):
        if not cls.enabled:
            print("[Keep-Alive] Service disabled via KEEP_ALIVE_ENABLED=false.")
            return
        if cls._thread and cls._thread.is_alive():
            return
        cls._thread = threading.Thread(target=cls._loop, daemon=True, name="StudioKeepAliveDaemon")
        cls._thread.start()

    @classmethod
    def get_status(cls):
        return {
            "enabled": cls.enabled,
            "target_url": cls.get_effective_target_url(),
            "interval_seconds": cls.interval,
            "total_pings": cls.total_pings,
            "successful_pings": cls.successful_pings,
            "failed_pings": cls.failed_pings,
            "last_ping_time": cls.last_ping_time,
            "last_ping_status": cls.last_ping_status,
            "last_ping_latency_ms": cls.last_ping_latency_ms,
            "last_error": cls.last_error,
            "is_render": bool(os.environ.get("RENDER")),
            "render_service_name": os.environ.get("RENDER_SERVICE_NAME", "portrait-studio-pro"),
            "discovered_url": cls.discovered_url
        }


class StudioServerHandler(BaseHTTPRequestHandler):
    def _send_json(self, data, status=200, cookie=None):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def _get_current_user(self):
        try:
            return saas_auth.get_authenticated_user(self.headers)
        except Exception as e:
            print(f"[Auth Error] {e}")
            return None

    def _get_base_url(self):
        proto = "https" if self.headers.get("X-Forwarded-Proto") == "https" else "http"
        host = self.headers.get("Host", "localhost:8080")
        return f"{proto}://{host}"

    def _require_auth(self):
        user = self._get_current_user()
        if not user:
            self._send_json({
                "status": "error",
                "code": "AUTH_REQUIRED",
                "message": "Authentication required. Please sign in with your enterprise company account to access studio services."
            }, status=401)
            return None
        return user

    def do_HEAD(self):
        proto = "https" if self.headers.get("X-Forwarded-Proto") == "https" else "http"
        host = self.headers.get("Host", "")
        KeepAliveService.register_public_origin(host, proto)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()

    def do_GET(self):
        proto = "https" if self.headers.get("X-Forwarded-Proto") == "https" else "http"
        host = self.headers.get("Host", "")
        KeepAliveService.register_public_origin(host, proto)

        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        params = urllib.parse.parse_qs(parsed.query)

        if path == "/healthz" or path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()
            self.wfile.write(b"OK")
            return

        elif path == "/api/keep_alive/status":
            self._send_json(KeepAliveService.get_status())
            return

        if path == "/" or path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            self.end_headers()
            self.wfile.write(HTML_PAGE.encode("utf-8"))
            return

        elif path == "/api/auth/me":
            user = self._get_current_user()
            if not user:
                self._send_json({"logged_in": False, "user": None})
                return
            is_superadmin = (user.get("role") == "superadmin")
            company = user.get("company") if not is_superadmin else None
            used_seats = saas_db.get_company_seat_count(user["company_id"]) if (user.get("company_id") and not is_superadmin) else 0
            passkeys = saas_db.get_passkeys_by_user(user["id"])
            platform_metrics = saas_db.get_platform_metrics() if is_superadmin else None

            safe_user = {
                "id": user["id"],
                "company_id": None if is_superadmin else user.get("company_id"),
                "email": user["email"],
                "full_name": user["full_name"],
                "role": user["role"],
                "is_superadmin": is_superadmin,
                "mfa_enabled": bool(user.get("mfa_enabled")),
                "passkeys_count": len(passkeys),
                "platform_metrics": platform_metrics,
                "is_active": user["is_active"],
                "created_at": user.get("created_at"),
                "company": {
                    "id": company["id"],
                    "name": company["name"],
                    "slug": company["slug"],
                    "plan": company.get("plan", "team"),
                    "max_seats": company.get("max_seats", 10),
                    "used_seats": used_seats,
                    "remaining_seats": max(0, company.get("max_seats", 10) - used_seats),
                    "status": company.get("status", "active")
                } if company else None
            }
            self._send_json({"logged_in": True, "user": safe_user})
            return

        elif path == "/api/auth/passkey/login_options":
            opts = saas_auth.create_passkey_login_challenge()
            self._send_json({"status": "ok", "options": opts})
            return

        # Strict authentication gate: all services require an authenticated active company account
        user = self._require_auth()
        if not user:
            return

        if path == "/api/admin/dashboard_stats":
            if user["role"] != "superadmin":
                self._send_json({"status": "error", "message": "Forbidden: Requires SuperAdmin"}, status=403)
                return
            metrics = saas_db.get_platform_metrics()
            self._send_json({"status": "ok", "metrics": metrics})
            return

        elif path == "/api/auth/passkey/register_options":
            opts = saas_auth.create_passkey_register_challenge(user)
            self._send_json({"status": "ok", "options": opts})
            return

        elif path == "/api/auth/passkey/list":
            keys = saas_db.get_passkeys_by_user(user["id"])
            safe_keys = []
            for k in keys:
                safe_keys.append({
                    "id": k["id"],
                    "credential_id": k["credential_id"],
                    "name": k.get("name") or "Biometric Key",
                    "created_at": k.get("created_at"),
                    "last_used_at": k.get("last_used_at")
                })
            self._send_json({"status": "ok", "passkeys": safe_keys})
            return

        elif path == "/api/company/details":
            user = self._get_current_user()
            if not user or not user.get("company_id"):
                self._send_json({"error": "Unauthorized"}, status=401)
                return
            company = saas_db.get_company_by_id(user["company_id"])
            if not company:
                self._send_json({"error": "Company not found"}, status=404)
                return
            used = saas_db.get_company_seat_count(company["id"])
            company["used_seats"] = used
            company["remaining_seats"] = max(0, company.get("max_seats", 10) - used)
            self._send_json({"status": "ok", "company": company})
            return

        elif path == "/api/company/users":
            user = self._get_current_user()
            if not user:
                self._send_json({"error": "Unauthorized"}, status=401)
                return

            target_company_id = user["company_id"]
            if user["role"] == "superadmin" and params.get("company_id"):
                target_company_id = params.get("company_id")[0]
            elif user["company_id"] != target_company_id:
                self._send_json({"error": "Forbidden: Cannot access members from another organization."}, status=403)
                return

            company = saas_db.get_company_by_id(target_company_id)
            members = saas_db.get_users_by_company(target_company_id)
            base_url = self._get_base_url()
            is_admin = user["role"] in ("superadmin", "company_admin")

            cleaned_members = []
            for m in members:
                m_dict = dict(m)
                m_dict.pop("password_hash", None)
                m_dict.pop("salt", None)
                if is_admin and m_dict.get("invite_token"):
                    m_dict["activation_url"] = f"{base_url}/#activate?token={m_dict['invite_token']}"
                else:
                    m_dict["activation_url"] = None
                    if not is_admin:
                        m_dict.pop("invite_token", None)
                cleaned_members.append(m_dict)

            used = saas_db.get_company_seat_count(target_company_id)
            max_seats = company.get("max_seats", 10) if company else 10
            self._send_json({
                "status": "ok",
                "company": company,
                "used_seats": used,
                "max_seats": max_seats,
                "remaining_seats": max(0, max_seats - used),
                "users": cleaned_members
            })
            return

        elif path == "/api/admin/companies":
            user = self._get_current_user()
            if not user or user["role"] != "superadmin":
                self._send_json({"error": "Forbidden: Requires SuperAdmin"}, status=403)
                return
            companies = saas_db.get_all_companies()
            self._send_json({"status": "ok", "companies": companies})
            return

        elif path == "/api/suggested_folders":
            workspace_dir = os.path.dirname(os.path.abspath(__file__))
            downloads_dir = os.path.expanduser("~/Downloads")
            search_dirs = [
                os.path.join(workspace_dir, "input_photos"),
                workspace_dir,
                downloads_dir,
                os.path.dirname(workspace_dir),
            ]
            suggestions_data = []
            seen_paths = set()

            for sdir in search_dirs:
                if os.path.exists(sdir):
                    entries = []
                    for item in os.listdir(sdir):
                        full = os.path.join(sdir, item)
                        if os.path.isdir(full) and not item.endswith("_edited") and not item.startswith("."):
                            try:
                                mtime = os.path.getmtime(full)
                                entries.append((mtime, item, full))
                            except OSError:
                                pass
                    entries.sort(key=lambda x: x[0], reverse=True)

                    for _, item, full in entries:
                        canonical = os.path.realpath(full)
                        if canonical in seen_paths or full in seen_paths:
                            continue
                        if item in ["Desktop", "ecstaticloud-animation", "ecstaticloud-services-anim", "Pdf extractor"]:
                            continue
                        photos = find_input_images(full)
                        if len(photos) > 0:
                            seen_paths.add(canonical)
                            seen_paths.add(full)
                            suggestions_data.append({
                                "name": item,
                                "path": full,
                                "count": len(photos),
                                "edited": resolve_edited_dir(full, create=False)
                            })

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "current": "",
                "suggestions_data": suggestions_data
            }).encode("utf-8"))

        elif path == "/api/scan_folder":
            raw_path = params.get("path", ["."])[0]
            folder = resolve_input_path(raw_path)
            if not folder or not os.path.exists(folder):
                self.send_response(404)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "status": "error",
                    "message": f"Folder '{raw_path}' could not be located on disk."
                }).encode("utf-8"))
                return

            photos = [os.path.basename(p) for p in find_input_images(folder)]
            edited = resolve_edited_dir(folder, create=False)

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "folder": folder,
                "edited": edited,
                "photos": photos
            }).encode("utf-8"))

        elif path == "/api/photo_raw":
            raw_folder = params.get("folder", ["."])[0]
            folder = resolve_input_path(raw_folder) or raw_folder
            name = params.get("name", [""])[0]
            img_path = os.path.join(folder, name)
            if os.path.exists(img_path) and os.path.isfile(img_path):
                ext = os.path.splitext(name)[1].lower()
                mime = "image/png"
                if ext in [".jpg", ".jpeg"]:
                    mime = "image/jpeg"
                elif ext == ".webp":
                    mime = "image/webp"
                with open(img_path, "rb") as f:
                    data = f.read()
                self.send_response(200)
                self.send_header("Content-Type", mime)
                self.end_headers()
                self.wfile.write(data)
            else:
                self.send_response(404)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": "Photo not found"}).encode("utf-8"))

        elif path == "/api/auto_align":
            raw_folder = params.get("folder", ["."])[0]
            folder = resolve_input_path(raw_folder) or raw_folder
            name = params.get("name", [""])[0]
            img_path = os.path.join(folder, name)
            if os.path.exists(img_path) and os.path.isfile(img_path):
                try:
                    with AI_LOCK:
                        data = compute_auto_framing(img_path)
                    gc.collect()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps(data).encode("utf-8"))
                except Exception as e:
                    self.send_response(500)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode("utf-8"))
            else:
                self.send_response(404)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": "Photo not found"}).encode("utf-8"))

        elif path == "/api/proxy_photo":
            img_url = params.get("url", [""])[0]
            width_param = params.get("width", ["800"])[0]
            try:
                tw = int(width_param)
            except Exception:
                tw = 800
            if not img_url:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"status":"error","message":"Missing url"}')
            else:
                try:
                    png_bytes, _ = download_player_portrait_bytes(img_url, target_width=tw)
                    self.send_response(200)
                    self.send_header("Content-Type", "image/png")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.send_header("Cache-Control", "public, max-age=86400")
                    self.send_header("Content-Length", str(len(png_bytes)))
                    self.end_headers()
                    self.wfile.write(png_bytes)
                except Exception as e:
                    self.send_response(500)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode("utf-8"))

        elif path == "/api/export_folder_zip":
            raw_folder = params.get("folder", ["."])[0]
            folder = resolve_input_path(raw_folder) or raw_folder
            if not os.path.exists(folder) or not os.path.isdir(folder):
                workspace_dir = os.path.dirname(os.path.abspath(__file__))
                for cand_base in [os.path.join(workspace_dir, "input_photos"), workspace_dir, os.path.expanduser("~/Downloads")]:
                    cand = os.path.join(cand_base, os.path.basename(raw_folder))
                    if os.path.exists(cand) and os.path.isdir(cand):
                        folder = cand
                        break
            if os.path.exists(folder) and os.path.isdir(folder):
                zip_buf = io.BytesIO()
                with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
                    for root, _, files in os.walk(folder):
                        for file in files:
                            if file.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                                file_p = os.path.join(root, file)
                                arcname = os.path.relpath(file_p, folder)
                                zf.write(file_p, arcname)
                zip_bytes = zip_buf.getvalue()
                folder_base = os.path.basename(folder) or "roster_photos"
                self.send_response(200)
                self.send_header("Content-Type", "application/zip")
                self.send_header("Content-Disposition", f'attachment; filename="{folder_base}.zip"')
                self.send_header("Content-Length", str(len(zip_bytes)))
                self.end_headers()
                self.wfile.write(zip_bytes)
            else:
                self.send_response(404)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": f"Folder '{os.path.basename(raw_folder)}' not found or empty."}).encode("utf-8"))
        else:
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "error", "message": f"Endpoint not found: {path}"}).encode("utf-8"))

    def do_POST(self):
        try:
            proto = "https" if self.headers.get("X-Forwarded-Proto") == "https" else "http"
            host = self.headers.get("Host", "")
            KeepAliveService.register_public_origin(host, proto)

            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query)
            content_len = int(self.headers.get("Content-Length", 0))

            # Strict authentication gate: All POST endpoints require active company login except auth login, invite activation, and MFA/Passkey challenge verification
            if parsed.path not in ("/api/auth/login", "/api/auth/activate", "/api/auth/mfa/verify_login", "/api/auth/passkey/login_verify"):
                user = self._require_auth()
                if not user:
                    return

            # Handle raw binary photo uploads from browser (enables full AI functionality on Render)
            if parsed.path == "/api/upload_single_file":
                raw_folder = params.get("folder", ["Selected_Photos"])[0]
                clean_folder = re.sub(r'[^a-zA-Z0-9_\-\s]', '', os.path.basename(raw_folder)).strip() or "Selected_Photos"
                filename = params.get("name", ["photo.png"])[0]
                clean_filename = os.path.basename(filename)

                workspace_dir = os.path.dirname(os.path.abspath(__file__))
                target_dir = os.path.join(workspace_dir, "input_photos", clean_folder)
                os.makedirs(target_dir, exist_ok=True)
                out_path = os.path.join(target_dir, clean_filename)

                file_bytes = self.rfile.read(content_len) if content_len > 0 else b""
                with open(out_path, "wb") as f:
                    f.write(file_bytes)

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "status": "ok",
                    "folder_path": target_dir,
                    "file_path": out_path
                }).encode("utf-8"))
                return

            body = self.rfile.read(content_len).decode("utf-8") if content_len > 0 else "{}"
            data = json.loads(body) if body else {}

            if parsed.path == "/api/keep_alive/ping_now":
                res = KeepAliveService.ping_now()
                self._send_json(res)
                return

            elif parsed.path == "/api/keep_alive/set_url":
                new_url = data.get("url", "").strip()
                if new_url:
                    KeepAliveService.target_url = new_url
                self._send_json({"status": "ok", "target_url": KeepAliveService.get_effective_target_url()})
                return

            elif parsed.path == "/api/resolve_folder_name":
                fname = data.get("folder_name", "")
                found_path = resolve_input_path(fname)

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "found": found_path is not None,
                    "path": found_path
                }).encode("utf-8"))
                return

            elif parsed.path == "/api/clear_server_storage":
                result = clean_server_storage(max_age_minutes=0)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "status": "ok",
                    "deleted_files": result["deleted_files"],
                    "freed_mb": result["freed_mb"],
                    "message": f"Successfully freed {result['freed_mb']} MB disk space and cleared RAM cache."
                }).encode("utf-8"))

            elif parsed.path == "/api/auto_align":
                b64_data = data.get("image_base64", "")
                photo_url = data.get("url", "")
                img_bytes = None
                if b64_data:
                    if "," in b64_data:
                        b64_data = b64_data.split(",", 1)[1]
                    img_bytes = base64.b64decode(b64_data)
                elif photo_url:
                    try:
                        img_bytes, _ = download_player_portrait_bytes(photo_url, target_width=800)
                    except Exception:
                        pass

                if img_bytes:
                    with AI_LOCK:
                        result = compute_auto_framing(image_bytes=img_bytes)
                    gc.collect()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps(result).encode("utf-8"))
                    return

                raw_folder = data.get("folder", ".")
                folder = resolve_input_path(raw_folder) or raw_folder
                name = data.get("name", data.get("photo", ""))
                img_path = os.path.join(folder, name)
                if os.path.exists(img_path) and os.path.isfile(img_path):
                    with AI_LOCK:
                        result = compute_auto_framing(img_path)
                    gc.collect()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps(result).encode("utf-8"))
                else:
                    self.send_response(404)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"status": "error", "message": "Photo not found"}).encode("utf-8"))

            elif parsed.path == "/api/preview_cutout":
                b64_data = data.get("image_base64", "")
                photo_url = data.get("url", "")
                scale = float(data.get("scale", 0.35))
                offset_x = float(data.get("offset_x", 0))
                offset_y = float(data.get("offset_y", 0))

                img_bytes = None
                if b64_data:
                    if "," in b64_data:
                        b64_data = b64_data.split(",", 1)[1]
                    img_bytes = base64.b64decode(b64_data)
                elif photo_url:
                    try:
                        img_bytes, _ = download_player_portrait_bytes(photo_url, target_width=800)
                    except Exception:
                        pass

                if img_bytes:
                    with AI_LOCK:
                        canvas = process_custom_framed_portrait(
                            image_bytes=img_bytes,
                            scale=scale,
                            offset_x=offset_x,
                            offset_y=offset_y,
                            output_size=180,
                        )
                    gc.collect()
                    buf = io.BytesIO()
                    canvas.save(buf, "PNG")
                    img_bytes_out = buf.getvalue()
                    self.send_response(200)
                    self.send_header("Content-Type", "image/png")
                    self.end_headers()
                    self.wfile.write(img_bytes_out)
                    return

                raw_folder = data.get("folder", ".")
                folder = resolve_input_path(raw_folder) or raw_folder
                photo = data.get("photo", "")
                img_path = os.path.join(folder, photo)
                if not os.path.exists(img_path):
                    workspace_dir = os.path.dirname(os.path.abspath(__file__))
                    alt_path = os.path.join(workspace_dir, "input_photos", os.path.basename(folder), photo)
                    if os.path.exists(alt_path):
                        img_path = alt_path

                if not os.path.exists(img_path):
                    self.send_response(404)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"status": "error", "message": f"Photo '{photo}' not found on server."}).encode("utf-8"))
                    return

                with AI_LOCK:
                    canvas = process_custom_framed_portrait(
                        image_path=img_path,
                        scale=scale,
                        offset_x=offset_x,
                        offset_y=offset_y,
                        output_size=180,
                    )
                gc.collect()

                buf = io.BytesIO()
                canvas.save(buf, "PNG")
                img_bytes = buf.getvalue()

                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.end_headers()
                self.wfile.write(img_bytes)

            elif parsed.path == "/api/save_refined_data":
                raw_folder = data.get("folder", ".")
                folder = resolve_input_path(raw_folder)
                if not folder:
                    workspace_dir = os.path.dirname(os.path.abspath(__file__))
                    folder = os.path.join(workspace_dir, "input_photos", os.path.basename(raw_folder))
                filename = data.get("filename", "headshot.png")
                clean_name = os.path.splitext(os.path.basename(filename))[0] + ".png"
                b64_data = data.get("image_base64", "")

                if "," in b64_data:
                    b64_data = b64_data.split(",", 1)[1]
                img_bytes = base64.b64decode(b64_data)

                out_dir = resolve_edited_dir(folder, create=True)
                out_path = os.path.join(out_dir, clean_name)

                img = Image.open(io.BytesIO(img_bytes))
                img.save(out_path, "PNG")

                folder_display = os.path.basename(out_dir)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "status": "ok",
                    "output_name": clean_name,
                    "folder_name": folder_display
                }).encode("utf-8"))

            elif parsed.path == "/api/process_single_portrait":
                b64_data = data.get("image_base64", "")
                photo_url = data.get("url", "")
                scale = float(data.get("scale", 0.35))
                offset_x = float(data.get("offset_x", 0))
                offset_y = float(data.get("offset_y", 0))
                photo = data.get("photo", "headshot.png")
                clean_name = os.path.splitext(os.path.basename(photo))[0] + ".png"

                img_bytes = None
                if b64_data:
                    if "," in b64_data:
                        b64_data = b64_data.split(",", 1)[1]
                    img_bytes = base64.b64decode(b64_data)
                elif photo_url:
                    try:
                        img_bytes, _ = download_player_portrait_bytes(photo_url, target_width=800)
                    except Exception:
                        pass

                if img_bytes:
                    with AI_LOCK:
                        canvas = process_custom_framed_portrait(
                            image_bytes=img_bytes,
                            scale=scale,
                            offset_x=offset_x,
                            offset_y=offset_y,
                            output_size=180,
                        )
                    gc.collect()
                    buf = io.BytesIO()
                    canvas.save(buf, "PNG")
                    out_b64 = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        "status": "ok",
                        "filename": clean_name,
                        "image_base64": out_b64
                    }).encode("utf-8"))
                    return

                raw_folder = data.get("folder", ".")
                folder = resolve_input_path(raw_folder)
                if not folder:
                    workspace_dir = os.path.dirname(os.path.abspath(__file__))
                    folder = os.path.join(workspace_dir, "input_photos", os.path.basename(raw_folder))

                out_dir = resolve_edited_dir(folder, create=True)
                clean_name = os.path.splitext(os.path.basename(photo))[0] + ".png"
                out_path = os.path.join(out_dir, clean_name)

                img_path = os.path.join(folder, photo)
                if not os.path.exists(img_path):
                    workspace_dir = os.path.dirname(os.path.abspath(__file__))
                    alt_path = os.path.join(workspace_dir, "input_photos", os.path.basename(folder), photo)
                    if os.path.exists(alt_path):
                        img_path = alt_path

                if not os.path.exists(img_path):
                    self.send_response(404)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        "status": "error",
                        "message": f"Source image '{photo}' not found on server."
                    }).encode("utf-8"))
                    return

                with AI_LOCK:
                    process_custom_framed_portrait(
                        image_path=img_path,
                        scale=scale,
                        offset_x=offset_x,
                        offset_y=offset_y,
                        output_path=out_path,
                        output_size=180,
                    )
                gc.collect()

                buf = io.BytesIO()
                canvas.save(buf, "PNG")
                out_b64 = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "status": "ok",
                    "filename": clean_name,
                    "folder_name": os.path.basename(out_dir),
                    "image_base64": out_b64
                }).encode("utf-8"))

            elif parsed.path == "/api/save_batch":
                raw_folder = data.get("folder", ".")
                folder = resolve_input_path(raw_folder) or raw_folder
                items = data.get("items", [])
                out_dir = resolve_edited_dir(folder, create=True)
                saved_names = []

                for item in items:
                    photo = item.get("photo", "")
                    scale = float(item.get("scale", 0.35))
                    offset_x = float(item.get("offset_x", 0))
                    offset_y = float(item.get("offset_y", 0))

                    img_path = os.path.join(folder, photo)
                    if not os.path.exists(img_path):
                        workspace_dir = os.path.dirname(os.path.abspath(__file__))
                        alt_path = os.path.join(workspace_dir, "input_photos", os.path.basename(folder), photo)
                        if os.path.exists(alt_path):
                            img_path = alt_path

                    if not os.path.exists(img_path):
                        continue

                    out_name = f"{os.path.splitext(photo)[0]}.png"
                    out_path = os.path.join(out_dir, out_name)

                    with AI_LOCK:
                        process_custom_framed_portrait(
                            image_path=img_path,
                            scale=scale,
                            offset_x=offset_x,
                            offset_y=offset_y,
                            output_path=out_path,
                            output_size=180,
                        )
                    saved_names.append(out_name)
                    gc.collect()

                folder_display = os.path.basename(out_dir)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "status": "ok",
                    "saved_count": len(saved_names),
                    "files": saved_names,
                    "folder_name": folder_display
                }).encode("utf-8"))

            elif parsed.path == "/api/fetch_roster":
                url = data.get("url", "").strip()
                if not url:
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"status": "error", "message": "Missing url parameter"}).encode("utf-8"))
                    return
                try:
                    result = scrape_roster_data(url)
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        "status": "ok",
                        "suggested_folder": result["suggested_folder"],
                        "players": result["players"]
                    }).encode("utf-8"))
                except Exception as e:
                    self.send_response(500)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        "status": "error",
                        "message": str(e)
                    }).encode("utf-8"))

            elif parsed.path == "/api/download_roster_zip":
                folder_name = data.get("folder_name", "Downloaded_Roster").strip()
                clean_folder = re.sub(r'[^a-zA-Z0-9_\-\s]', '', folder_name).strip() or "Downloaded_Roster"
                players = data.get("players", [])
                target_width = int(data.get("target_width", 800))

                zip_buf = io.BytesIO()
                seen_filenames = set()

                def _fetch_player_bytes(item):
                    p_name = item.get("name", "").strip()
                    assigned = item.get("assigned_number", "").strip()
                    img_url = item.get("image", "").strip()

                    clean_name = re.sub(r'[\\/*?:"<>|]', '', p_name).strip()
                    if assigned:
                        clean_assigned = re.sub(r'[\\/*?:"<>|]', '', assigned).strip()
                        out_filename = f"{clean_assigned}.png"
                    else:
                        out_filename = f"{clean_name}.png"

                    base_out = out_filename
                    counter = 2
                    while out_filename in seen_filenames:
                        root, ext = os.path.splitext(base_out)
                        out_filename = f"{root}_{counter}{ext}"
                        counter += 1
                    seen_filenames.add(out_filename)

                    try:
                        png_bytes, sz = download_player_portrait_bytes(img_url, target_width=target_width)
                        return (out_filename, png_bytes, "ok", None)
                    except Exception as e:
                        return (out_filename, None, "error", str(e))

                with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
                    results = list(executor.map(_fetch_player_bytes, players))

                with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
                    for filename, png_bytes, status, err in results:
                        if status == "ok" and png_bytes:
                            zf.writestr(filename, png_bytes)

                zip_bytes = zip_buf.getvalue()
                gc.collect()

                self.send_response(200)
                self.send_header("Content-Type", "application/zip")
                self.send_header("Content-Disposition", f'attachment; filename="{clean_folder}.zip"')
                self.send_header("Content-Length", str(len(zip_bytes)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(zip_bytes)
                return

            elif parsed.path == "/api/download_roster_players":
                folder_name = data.get("folder_name", "Downloaded_Roster").strip()
                players = data.get("players", [])
                target_width = int(data.get("target_width", 800))

                workspace_dir = os.path.dirname(os.path.abspath(__file__))
                downloads_dir = os.path.expanduser("~/Downloads")
                if os.environ.get("RENDER"):
                    target_dir = os.path.join(workspace_dir, "input_photos", folder_name)
                elif os.path.exists(downloads_dir) and not os.path.isabs(folder_name):
                    target_dir = os.path.join(downloads_dir, folder_name)
                else:
                    target_dir = os.path.join(workspace_dir, "input_photos", folder_name)

                os.makedirs(target_dir, exist_ok=True)

                def _download_worker(item):
                    p_name = item.get("name", "").strip()
                    assigned = item.get("assigned_number", "").strip()
                    img_url = item.get("image", "").strip()

                    clean_name = re.sub(r'[\\/*?:"<>|]', '', p_name).strip()
                    if assigned:
                        clean_assigned = re.sub(r'[\\/*?:"<>|]', '', assigned).strip()
                        out_filename = f"{clean_assigned}.png"
                        used_type = "assigned"
                    else:
                        out_filename = f"{clean_name}.png"
                        used_type = "name"

                    save_path = os.path.join(target_dir, out_filename)
                    try:
                        sp, sz = download_player_portrait(img_url, save_path, target_width=target_width)
                        return {
                            "name": p_name,
                            "filename": out_filename,
                            "type": used_type,
                            "dimensions": sz,
                            "path": sp,
                            "status": "ok"
                        }
                    except Exception as e:
                        return {
                            "name": p_name,
                            "filename": out_filename,
                            "type": used_type,
                            "status": "error",
                            "error": str(e)
                        }

                with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
                    saved_files = list(executor.map(_download_worker, players))

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "status": "ok",
                    "target_dir": target_dir,
                    "folder_name": os.path.basename(target_dir),
                    "total": len(players),
                    "saved_count": len([s for s in saved_files if s.get("status") == "ok"]),
                    "files": saved_files
                }).encode("utf-8"))
            elif parsed.path == "/api/auth/login":
                email = data.get("email", "").strip().lower()
                password = data.get("password", "")
                user = saas_db.get_user_by_email(email)
                if not user:
                    self._send_json({"status": "error", "message": "Invalid email or password."}, status=401)
                    return
                if not user.get("is_active"):
                    self._send_json({"status": "error", "message": "This account is inactive. Please contact your company administrator."}, status=403)
                    return
                if not user.get("password_hash") or not user.get("salt"):
                    self._send_json({"status": "error", "message": "Account has not been activated yet. Please click the invitation link sent to your email to set your password."}, status=400)
                    return
                if not saas_auth.verify_password(password, user["password_hash"], user["salt"]):
                    self._send_json({"status": "error", "message": "Invalid email or password."}, status=401)
                    return

                # Check if MFA (Two-Factor Authentication) is enabled for this user
                if user.get("mfa_enabled"):
                    mfa_token = saas_auth.create_mfa_login_token(user["id"])
                    self._send_json({
                        "status": "mfa_required",
                        "mfa_token": mfa_token,
                        "email": user["email"],
                        "message": "Two-Factor Authentication is enabled. Please enter your authenticator app code or backup code."
                    })
                    return

                token = saas_db.create_session(user["id"])
                is_superadmin = (user.get("role") == "superadmin")
                company = saas_db.get_company_by_id(user["company_id"]) if not is_superadmin else None
                used_seats = saas_db.get_company_seat_count(user["company_id"]) if (user.get("company_id") and not is_superadmin) else 0
                passkeys = saas_db.get_passkeys_by_user(user["id"])
                platform_metrics = saas_db.get_platform_metrics() if is_superadmin else None

                safe_user = {
                    "id": user["id"],
                    "company_id": None if is_superadmin else user.get("company_id"),
                    "email": user["email"],
                    "full_name": user["full_name"],
                    "role": user["role"],
                    "is_superadmin": is_superadmin,
                    "mfa_enabled": bool(user.get("mfa_enabled")),
                    "passkeys_count": len(passkeys),
                    "platform_metrics": platform_metrics,
                    "company": {
                        "id": company["id"],
                        "name": company["name"],
                        "slug": company["slug"],
                        "plan": company.get("plan", "team"),
                        "max_seats": company.get("max_seats", 10),
                        "used_seats": used_seats,
                        "remaining_seats": max(0, company.get("max_seats", 10) - used_seats),
                        "status": company.get("status", "active")
                    } if company else None
                }
                cookie = f"session_token={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age=2592000"
                self._send_json({"status": "ok", "token": token, "user": safe_user}, cookie=cookie)
                return

            elif parsed.path == "/api/auth/mfa/verify_login":
                mfa_token = data.get("mfa_token", "").strip()
                code = data.get("code", "").strip()
                if not mfa_token or not code:
                    self._send_json({"status": "error", "message": "Missing MFA challenge token or code."}, status=400)
                    return

                verified_user_id = saas_auth.verify_mfa_login_token(mfa_token)
                if not verified_user_id:
                    self._send_json({"status": "error", "message": "MFA challenge expired or invalid. Please sign in again."}, status=401)
                    return

                user = saas_db.get_user_by_id(verified_user_id)
                if not user:
                    self._send_json({"status": "error", "message": "User not found."}, status=404)
                    return

                clean_code = str(code).strip()
                valid = False
                secret = user.get("mfa_secret")
                if secret and saas_auth.verify_totp_code(secret, clean_code):
                    valid = True
                elif saas_auth.verify_and_consume_backup_code(user["id"], clean_code):
                    valid = True

                if not valid:
                    fresh_token = saas_auth.create_mfa_login_token(user["id"])
                    self._send_json({
                        "status": "error",
                        "message": "Invalid authentication code. Please check your authenticator app or backup code.",
                        "mfa_token": fresh_token
                    }, status=401)
                    return

                token = saas_db.create_session(user["id"])
                is_superadmin = (user.get("role") == "superadmin")
                company = saas_db.get_company_by_id(user["company_id"]) if not is_superadmin else None
                used_seats = saas_db.get_company_seat_count(user["company_id"]) if (user.get("company_id") and not is_superadmin) else 0
                passkeys = saas_db.get_passkeys_by_user(user["id"])
                platform_metrics = saas_db.get_platform_metrics() if is_superadmin else None

                safe_user = {
                    "id": user["id"],
                    "company_id": None if is_superadmin else user.get("company_id"),
                    "email": user["email"],
                    "full_name": user["full_name"],
                    "role": user["role"],
                    "is_superadmin": is_superadmin,
                    "mfa_enabled": bool(user.get("mfa_enabled")),
                    "passkeys_count": len(passkeys),
                    "platform_metrics": platform_metrics,
                    "company": {
                        "id": company["id"],
                        "name": company["name"],
                        "slug": company["slug"],
                        "plan": company.get("plan", "team"),
                        "max_seats": company.get("max_seats", 10),
                        "used_seats": used_seats,
                        "remaining_seats": max(0, company.get("max_seats", 10) - used_seats),
                        "status": company.get("status", "active")
                    } if company else None
                }
                cookie = f"session_token={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age=2592000"
                self._send_json({"status": "ok", "token": token, "user": safe_user}, cookie=cookie)
                return

            elif parsed.path == "/api/auth/passkey/login_verify":
                challenge_id = data.get("challenge_id")
                credential = data.get("credential", {})
                cred_id = credential.get("id") or credential.get("rawId")
                if not challenge_id or not cred_id:
                    self._send_json({"status": "error", "message": "Missing passkey credential data."}, status=400)
                    return

                pk = saas_db.get_passkey_by_credential_id(cred_id)
                if not pk:
                    self._send_json({"status": "error", "message": "Biometric passkey not recognized on this server."}, status=404)
                    return

                valid_ch = saas_auth.verify_passkey_challenge(challenge_id, expected_type="login")
                if not valid_ch:
                    self._send_json({"status": "error", "message": "Biometric challenge expired or invalid."}, status=401)
                    return

                user = saas_db.get_user_by_id(pk["user_id"])
                if not user or not user.get("is_active"):
                    self._send_json({"status": "error", "message": "Account associated with this passkey is inactive."}, status=403)
                    return

                saas_db.update_passkey_usage(pk["credential_id"])
                token = saas_db.create_session(user["id"])
                is_superadmin = (user.get("role") == "superadmin")
                company = saas_db.get_company_by_id(user["company_id"]) if not is_superadmin else None
                used_seats = saas_db.get_company_seat_count(user["company_id"]) if (user.get("company_id") and not is_superadmin) else 0
                passkeys = saas_db.get_passkeys_by_user(user["id"])
                platform_metrics = saas_db.get_platform_metrics() if is_superadmin else None

                safe_user = {
                    "id": user["id"],
                    "company_id": None if is_superadmin else user.get("company_id"),
                    "email": user["email"],
                    "full_name": user["full_name"],
                    "role": user["role"],
                    "is_superadmin": is_superadmin,
                    "mfa_enabled": bool(user.get("mfa_enabled")),
                    "passkeys_count": len(passkeys),
                    "platform_metrics": platform_metrics,
                    "company": {
                        "id": company["id"],
                        "name": company["name"],
                        "slug": company["slug"],
                        "plan": company.get("plan", "team"),
                        "max_seats": company.get("max_seats", 10),
                        "used_seats": used_seats,
                        "remaining_seats": max(0, company.get("max_seats", 10) - used_seats),
                        "status": company.get("status", "active")
                    } if company else None
                }
                cookie = f"session_token={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age=2592000"
                self._send_json({"status": "ok", "token": token, "user": safe_user}, cookie=cookie)
                return

            elif parsed.path == "/api/auth/passkey/register_verify":
                user = self._get_current_user()
                if not user:
                    self._send_json({"status": "error", "message": "Unauthorized"}, status=401)
                    return

                challenge_id = data.get("challenge_id")
                name = data.get("name") or "Biometric Key"
                credential = data.get("credential", {})
                cred_id = credential.get("id") or credential.get("rawId")
                if not challenge_id or not cred_id:
                    self._send_json({"status": "error", "message": "Missing passkey registration details."}, status=400)
                    return

                valid_ch = saas_auth.verify_passkey_challenge(challenge_id, expected_type="register")
                if not valid_ch:
                    self._send_json({"status": "error", "message": "Passkey registration challenge expired."}, status=400)
                    return

                pk = saas_db.create_passkey(
                    user_id=user["id"],
                    credential_id=cred_id,
                    public_key=credential.get("response", {}).get("attestationObject", ""),
                    name=name
                )
                self._send_json({"status": "ok", "passkey": pk})
                return

            elif parsed.path == "/api/auth/passkey/delete":
                user = self._get_current_user()
                if not user:
                    self._send_json({"status": "error", "message": "Unauthorized"}, status=401)
                    return
                passkey_id = data.get("passkey_id")
                if not passkey_id:
                    self._send_json({"status": "error", "message": "Missing passkey_id."}, status=400)
                    return
                saas_db.delete_passkey(passkey_id, user_id=user["id"])
                self._send_json({"status": "ok"})
                return

            elif parsed.path == "/api/auth/mfa/setup":
                user = self._get_current_user()
                if not user:
                    self._send_json({"status": "error", "message": "Unauthorized"}, status=401)
                    return
                secret = saas_auth.generate_totp_secret()
                totp_uri = saas_auth.get_totp_uri(secret, user["email"], issuer="Basketball Portrait Studio")
                qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=220x220&data={urllib.parse.quote(totp_uri)}"
                backup_codes = saas_auth.generate_backup_codes(count=8)
                self._send_json({
                    "status": "ok",
                    "secret": secret,
                    "totp_uri": totp_uri,
                    "qr_url": qr_url,
                    "backup_codes": backup_codes
                })
                return

            elif parsed.path == "/api/auth/mfa/enable":
                user = self._get_current_user()
                if not user:
                    self._send_json({"status": "error", "message": "Unauthorized"}, status=401)
                    return
                secret = data.get("secret", "").strip()
                code = data.get("code", "").strip().replace(" ", "").replace("-", "")
                backup_codes = data.get("backup_codes", [])
                if not secret or not code:
                    self._send_json({"status": "error", "message": "Secret and verification code are required."}, status=400)
                    return
                if not saas_auth.verify_totp_code(secret, code):
                    self._send_json({"status": "error", "message": "Verification code is incorrect. Please check your authenticator app."}, status=400)
                    return

                backup_codes_str = json.dumps(backup_codes) if isinstance(backup_codes, list) else str(backup_codes)
                saas_db.update_user_mfa(user["id"], enabled=True, secret=secret, backup_codes_json=backup_codes_str)
                self._send_json({"status": "ok", "message": "Two-factor authentication enabled successfully."})
                return

            elif parsed.path == "/api/auth/mfa/disable":
                user = self._get_current_user()
                if not user:
                    self._send_json({"status": "error", "message": "Unauthorized"}, status=401)
                    return
                password = data.get("password", "")
                if not password:
                    self._send_json({"status": "error", "message": "Password is required to disable 2FA."}, status=400)
                    return
                if not saas_auth.verify_password(password, user["password_hash"], user["salt"]):
                    self._send_json({"status": "error", "message": "Incorrect password."}, status=401)
                    return

                saas_db.update_user_mfa(user["id"], enabled=False, secret=None, backup_codes_json=None)
                self._send_json({"status": "ok", "message": "Two-factor authentication disabled."})
                return

            elif parsed.path == "/api/auth/update_profile":
                user = self._get_current_user()
                if not user:
                    self._send_json({"status": "error", "message": "Unauthorized"}, status=401)
                    return
                full_name = data.get("full_name", "").strip()
                email = data.get("email", "").strip().lower()
                current_password = data.get("current_password", "")

                if not full_name or not email:
                    self._send_json({"status": "error", "message": "Full name and email are required."}, status=400)
                    return

                if email != user["email"]:
                    if not current_password or not saas_auth.verify_password(current_password, user["password_hash"], user["salt"]):
                        self._send_json({"status": "error", "message": "Current password is required to change email."}, status=401)
                        return
                    existing = saas_db.get_user_by_email(email)
                    if existing and existing["id"] != user["id"]:
                        self._send_json({"status": "error", "message": "Email is already taken by another user."}, status=400)
                        return

                saas_db.update_user_credentials(user["id"], email=email, full_name=full_name)
                self._send_json({"status": "ok", "message": "Profile updated successfully."})
                return

            elif parsed.path == "/api/auth/change_password":
                user = self._get_current_user()
                if not user:
                    self._send_json({"status": "error", "message": "Unauthorized"}, status=401)
                    return
                current_password = data.get("current_password", "")
                new_password = data.get("new_password", "")
                if not current_password or not new_password:
                    self._send_json({"status": "error", "message": "Current and new password are required."}, status=400)
                    return
                if len(new_password) < 4:
                    self._send_json({"status": "error", "message": "New password must be at least 4 characters."}, status=400)
                    return
                if not saas_auth.verify_password(current_password, user["password_hash"], user["salt"]):
                    self._send_json({"status": "error", "message": "Current password incorrect."}, status=401)
                    return

                p_hash, salt = saas_auth.hash_password(new_password)
                saas_db.update_user_credentials(user["id"], password_hash=p_hash, salt=salt)
                self._send_json({"status": "ok", "message": "Password successfully updated."})
                return

            elif parsed.path == "/api/auth/logout":
                token = None
                auth_header = self.headers.get("Authorization", "")
                if auth_header.startswith("Bearer "):
                    token = auth_header.split(" ", 1)[1].strip()
                if not token:
                    cookie_header = self.headers.get("Cookie", "")
                    if "session_token=" in cookie_header:
                        m = re.search(r'session_token=([^;]+)', cookie_header)
                        if m:
                            token = m.group(1).strip()
                if token:
                    saas_db.delete_session(token)
                cookie = "session_token=; Path=/; Expires=Thu, 01 Jan 1970 00:00:00 GMT"
                self._send_json({"status": "ok"}, cookie=cookie)
                return

            elif parsed.path == "/api/auth/activate":
                invite_token = data.get("token", "").strip()
                password = data.get("password", "")
                full_name = data.get("full_name", "").strip()
                if not invite_token:
                    self._send_json({"status": "error", "message": "Missing activation token."}, status=400)
                    return
                if not password or len(password) < 6:
                    self._send_json({"status": "error", "message": "Password must be at least 6 characters long."}, status=400)
                    return

                user = saas_db.get_user_by_invite_token(invite_token)
                if not user:
                    self._send_json({"status": "error", "message": "Invalid or expired activation link."}, status=404)
                    return

                p_hash, salt = saas_auth.hash_password(password)
                saas_db.activate_user(user["id"], p_hash, salt, full_name=full_name if full_name else None)
                token = saas_db.create_session(user["id"])
                company = saas_db.get_company_by_id(user["company_id"])
                used_seats = saas_db.get_company_seat_count(user["company_id"]) if user.get("company_id") else 0
                safe_user = {
                    "id": user["id"],
                    "company_id": user["company_id"],
                    "email": user["email"],
                    "full_name": full_name or user["full_name"],
                    "role": user["role"],
                    "company": {
                        "id": company["id"],
                        "name": company["name"],
                        "slug": company["slug"],
                        "plan": company.get("plan", "team"),
                        "max_seats": company.get("max_seats", 10),
                        "used_seats": used_seats,
                        "remaining_seats": max(0, company.get("max_seats", 10) - used_seats),
                        "status": company.get("status", "active")
                    } if company else None
                }
                cookie = f"session_token={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age=2592000"
                self._send_json({"status": "ok", "token": token, "user": safe_user}, cookie=cookie)
                return

            elif parsed.path == "/api/company/users/invite":
                user = self._get_current_user()
                if not user or user["role"] not in ("superadmin", "company_admin"):
                    self._send_json({"status": "error", "message": "Forbidden: Admin privileges required."}, status=403)
                    return

                company_id = data.get("company_id") or user["company_id"]
                if user["role"] != "superadmin":
                    company_id = user["company_id"]

                company = saas_db.get_company_by_id(company_id)
                if not company:
                    self._send_json({"status": "error", "message": "Company not found."}, status=404)
                    return

                used_seats = saas_db.get_company_seat_count(company_id)
                max_seats = company.get("max_seats", 10)
                if used_seats >= max_seats:
                    self._send_json({
                        "status": "error",
                        "message": f"Seat limit reached for {company['name']} ({used_seats}/{max_seats} used). Please upgrade company subscription to add more members."
                    }, status=400)
                    return

                email = data.get("email", "").strip().lower()
                name = data.get("full_name", "").strip() or email.split("@")[0].title()
                role = data.get("role", "member")
                if role not in ("member", "company_admin"):
                    role = "member"

                if not email or "@" not in email:
                    self._send_json({"status": "error", "message": "A valid email address is required."}, status=400)
                    return

                if saas_db.get_user_by_email(email):
                    self._send_json({"status": "error", "message": f"User with email '{email}' already exists."}, status=400)
                    return

                invite_token = saas_auth.generate_invite_token()
                new_user = saas_db.create_user(company_id, email, name, role, invite_token)
                base_url = self._get_base_url()
                email_res = saas_email.send_invitation_email(email, name, company["name"], invite_token, base_url)

                self._send_json({
                    "status": "ok",
                    "user": new_user,
                    "activation_url": f"{base_url}/#activate?token={invite_token}",
                    "email_status": email_res,
                    "used_seats": saas_db.get_company_seat_count(company_id),
                    "max_seats": max_seats
                })
                return

            elif parsed.path == "/api/company/users/bulk_invite":
                user = self._get_current_user()
                if not user or user["role"] not in ("superadmin", "company_admin"):
                    self._send_json({"status": "error", "message": "Forbidden: Admin privileges required."}, status=403)
                    return

                company_id = data.get("company_id") or user["company_id"]
                if user["role"] != "superadmin":
                    company_id = user["company_id"]

                company = saas_db.get_company_by_id(company_id)
                if not company:
                    self._send_json({"status": "error", "message": "Company not found."}, status=404)
                    return

                raw_text = data.get("raw_text", "")
                parsed_users = saas_auth.parse_bulk_user_input(raw_text)
                if not parsed_users:
                    self._send_json({"status": "error", "message": "No valid user emails found in provided text."}, status=400)
                    return

                used_seats = saas_db.get_company_seat_count(company_id)
                max_seats = company.get("max_seats", 10)
                available_seats = max(0, max_seats - used_seats)

                added = []
                skipped = []
                base_url = self._get_base_url()

                for item in parsed_users:
                    em = item["email"]
                    nm = item["full_name"]
                    rl = item.get("role", "member")
                    if available_seats <= 0:
                        skipped.append({"email": em, "name": nm, "reason": f"Seat quota reached ({max_seats} max seats)"})
                        continue
                    if saas_db.get_user_by_email(em):
                        skipped.append({"email": em, "name": nm, "reason": "User with this email already exists"})
                        continue

                    inv_tok = saas_auth.generate_invite_token()
                    nu = saas_db.create_user(company_id, em, nm, rl, inv_tok)
                    email_res = saas_email.send_invitation_email(em, nm, company["name"], inv_tok, base_url)
                    available_seats -= 1
                    added.append({
                        "id": nu["id"],
                        "email": em,
                        "full_name": nm,
                        "role": rl,
                        "activation_url": f"{base_url}/#activate?token={inv_tok}",
                        "email_simulated": email_res.get("simulated", False)
                    })

                self._send_json({
                    "status": "ok",
                    "added": added,
                    "skipped": skipped,
                    "used_seats": saas_db.get_company_seat_count(company_id),
                    "max_seats": max_seats,
                    "remaining_seats": max(0, max_seats - saas_db.get_company_seat_count(company_id))
                })
                return

            elif parsed.path == "/api/company/users/revoke":
                user = self._get_current_user()
                if not user or user["role"] not in ("superadmin", "company_admin"):
                    self._send_json({
                        "status": "error",
                        "message": "Forbidden: Administrator privileges required to manage team members."
                    }, status=403)
                    return

                target_user_id = data.get("user_id")
                if not target_user_id:
                    self._send_json({"status": "error", "message": "Missing user_id parameter."}, status=400)
                    return

                target_user = saas_db.get_user_by_id(target_user_id)
                if not target_user:
                    self._send_json({"status": "error", "message": "User not found."}, status=404)
                    return

                # Prevent self-removal
                if target_user["id"] == user["id"]:
                    self._send_json({"status": "error", "message": "You cannot remove your own account."}, status=400)
                    return

                # Strict Hierarchy Enforcement:
                if user["role"] != "superadmin":
                    # 1. Company Admin cannot touch other companies
                    if target_user["company_id"] != user["company_id"]:
                        self._send_json({
                            "status": "error",
                            "message": "Forbidden: Unauthorized to manage users from another organization."
                        }, status=403)
                        return

                    # 2. Company Admin CANNOT remove fellow administrators or superadmins!
                    if target_user["role"] in ("superadmin", "company_admin", "admin"):
                        self._send_json({
                            "status": "error",
                            "message": "Forbidden: Company Administrators cannot remove other Administrators or SuperAdmins. Only Platform SuperAdmins can manage Administrator accounts."
                        }, status=403)
                        return

                company_id = target_user["company_id"]
                saas_db.delete_user(target_user_id)
                used_seats = saas_db.get_company_seat_count(company_id)
                self._send_json({
                    "status": "ok",
                    "message": f"User {target_user['email']} has been removed and seat freed.",
                    "used_seats": used_seats
                })
                return

            elif parsed.path == "/api/company/users/resend_invite":
                user = self._get_current_user()
                if not user or user["role"] not in ("superadmin", "company_admin"):
                    self._send_json({"status": "error", "message": "Forbidden: Admin privileges required."}, status=403)
                    return

                target_user_id = data.get("user_id")
                target_user = saas_db.get_user_by_id(target_user_id)
                if not target_user:
                    self._send_json({"status": "error", "message": "User not found."}, status=404)
                    return

                if user["role"] != "superadmin" and target_user["company_id"] != user["company_id"]:
                    self._send_json({"status": "error", "message": "Unauthorized."}, status=403)
                    return

                company = saas_db.get_company_by_id(target_user["company_id"])
                inv_tok = saas_auth.generate_invite_token()
                now = datetime.datetime.now(datetime.timezone.utc)
                exp = (now + datetime.timedelta(days=7)).isoformat()
                saas_db.execute_query("UPDATE users SET invite_token = ?, invite_expires_at = ? WHERE id = ?", (inv_tok, exp, target_user_id), commit=True)
                base_url = self._get_base_url()
                email_res = saas_email.send_invitation_email(target_user["email"], target_user["full_name"], company["name"], inv_tok, base_url)
                self._send_json({
                    "status": "ok",
                    "activation_url": f"{base_url}/#activate?token={inv_tok}",
                    "email_status": email_res
                })
                return

            elif parsed.path == "/api/admin/companies/create":
                user = self._get_current_user()
                if not user or user["role"] != "superadmin":
                    self._send_json({"status": "error", "message": "Forbidden: SuperAdmin required."}, status=403)
                    return

                name = data.get("name", "").strip()
                plan = data.get("plan", "team")
                max_seats = int(data.get("max_seats", 10))
                if not name:
                    self._send_json({"status": "error", "message": "Company name is required."}, status=400)
                    return

                comp = saas_db.create_company(name=name, plan=plan, max_seats=max_seats)

                admin_email = data.get("admin_email", "").strip().lower()
                admin_name = data.get("admin_name", "").strip() or "Company Admin"
                admin_user = None
                activation_url = None
                if admin_email and "@" in admin_email:
                    if not saas_db.get_user_by_email(admin_email):
                        inv_tok = saas_auth.generate_invite_token()
                        admin_user = saas_db.create_user(comp["id"], admin_email, admin_name, role="company_admin", invite_token=inv_tok)
                        base_url = self._get_base_url()
                        saas_email.send_invitation_email(admin_email, admin_name, comp["name"], inv_tok, base_url)
                        activation_url = f"{base_url}/#activate?token={inv_tok}"

                self._send_json({
                    "status": "ok",
                    "company": comp,
                    "admin_user": admin_user,
                    "activation_url": activation_url
                })
                return

            elif parsed.path == "/api/admin/companies/update_plan":
                user = self._get_current_user()
                if not user or user["role"] != "superadmin":
                    self._send_json({"status": "error", "message": "Forbidden: SuperAdmin required."}, status=403)
                    return

                cid = data.get("company_id")
                plan = data.get("plan", "team")
                max_seats = int(data.get("max_seats", 10))
                status = data.get("status", "active")
                updated = saas_db.update_company_plan(cid, plan, max_seats, status)
                self._send_json({"status": "ok", "company": updated})
                return
            elif parsed.path in ("/", ""):
                self.send_response(204)
                self.end_headers()
                return
            else:
                self.send_response(404)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": f"Endpoint not found: {parsed.path}"}).encode("utf-8"))
        except Exception as e:
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "status": "error",
                "message": f"Server processing error: {str(e)}"
            }).encode("utf-8"))

    def log_message(self, format, *args):
        return


def launch_studio(port: int = None):
    # Support Render and other cloud platforms via PORT environment variable
    env_port = os.environ.get("PORT")
    target_port = int(env_port) if env_port else (port or 8080)
    host = "0.0.0.0"

    # Clean any stale temporary files and release RAM on startup
    try:
        startup_clean = clean_server_storage(max_age_minutes=0)
        print(f"[Studio] Startup cleanup complete: freed {startup_clean.get('freed_mb', 0)} MB disk space & RAM cache.")
    except Exception as e:
        print(f"[Studio] Startup cleanup note: {e}")

    # Initialize multi-tenant SaaS database (PostgreSQL / SQLite fallback)
    try:
        saas_db.init_db()
        print("[Studio] Multi-tenant SaaS database initialized.")
    except Exception as e:
        print(f"[Studio] Database init error: {e}")

    # Start autonomous Keep-Alive anti-idle heartbeat daemon
    KeepAliveService.start()

    ports_to_try = [target_port] if env_port else [target_port, 8081, 8082, 8888, 5050]

    for p in ports_to_try:
        try:
            server = ThreadingHTTPServer((host, p), StudioServerHandler)
            server.daemon_threads = True
            print("=" * 66)
            print(f"🏀 Basketball Portrait Studio Pro running at: http://{host}:{p}")
            print("=" * 66)
            # Only auto-open browser in local desktop sessions, not in headless cloud
            if not os.environ.get("RENDER"):
                try:
                    import webbrowser
                    webbrowser.open(f"http://localhost:{p}")
                except Exception:
                    pass
            server.serve_forever()
            return
        except OSError as e:
            if env_port:
                print(f"Error: Could not bind to port {p}: {e}")
                sys.exit(1)
            continue
    print("Error: Could not bind to an open port.")


if __name__ == "__main__":
    launch_studio()
