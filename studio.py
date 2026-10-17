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
import threading
import concurrent.futures
import gc
from datetime import datetime
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from PIL import Image

# Optimize thread allocation for low-resource cloud environments (Render Free tier)
os.environ.setdefault("OMP_NUM_THREADS", "2")
os.environ.setdefault("MKL_NUM_THREADS", "2")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")

# Auto-activate local .venv if not in virtualenv
script_dir = os.path.dirname(os.path.abspath(__file__))
venv_python = os.path.join(script_dir, ".venv", "bin", "python3")
if not os.environ.get("RENDER") and sys.prefix == sys.base_prefix and os.path.exists(venv_python) and sys.executable != venv_python:
    os.execv(venv_python, [venv_python] + sys.argv)

import rembg
from process_portraits import FaceDetectorWrapper, find_input_images

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


def compute_auto_framing(image_path: str):
    """Calculates optimal default framing using MediaPipe face detection."""
    if image_path in FACE_CACHE:
        return FACE_CACHE[image_path]

    detector, _ = get_services()
    orig = Image.open(image_path).convert("RGB")
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
    FACE_CACHE[image_path] = result
    return result


def process_custom_framed_portrait(
    image_path: str,
    scale: float,
    offset_x: float,
    offset_y: float,
    output_path: str = None,
    output_size: int = 180,
) -> Image.Image:
    """Crops the framed region, runs rembg, and fits to 180x180 RGBA canvas."""
    _, rembg_session = get_services()
    orig = Image.open(image_path).convert("RGB")
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


def scrape_roster_data(url: str):
    """
    Intelligently routes roster URL to NHL, UK Teams, or College/NCAA athletics scrapers
    with automatic fallbacks.
    """
    url_lower = url.lower()
    if "nhl.com" in url_lower or "nhle.com" in url_lower:
        return scrape_nhl_roster(url)

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
        # Fallback to UK / general sports scraper if college returned no players
        try:
            uk_res = scrape_uk_roster(url)
            if uk_res.get("players") and len(uk_res["players"]) > 0:
                return uk_res
        except Exception:
            pass

    return res



def download_player_portrait(img_url: str, save_path: str, target_width: int = 800) -> tuple:
    """Downloads photo with boosted URL width and standardizes width to target_width with Lanczos."""
    high_res_url = boost_image_url_width(img_url, target_width=1200)
    raw_bytes = None

    for u in [high_res_url, img_url]:
        try:
            req = urllib.request.Request(
                u,
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                }
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                raw_bytes = resp.read()
            if raw_bytes:
                break
        except Exception:
            continue

    if not raw_bytes:
        raise ValueError(f"Could not download photo from: {img_url}")

    im = Image.open(io.BytesIO(raw_bytes))
    if im.mode not in ("RGB", "RGBA"):
        im = im.convert("RGBA" if "A" in im.mode else "RGB")

    orig_w, orig_h = im.size
    if orig_w != target_width:
        scale = target_width / float(orig_w)
        new_h = int(round(orig_h * scale))
        resized = im.resize((target_width, new_h), Image.Resampling.LANCZOS)
    else:
        resized = im

    os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
    if not save_path.lower().endswith(".png"):
        save_path = os.path.splitext(save_path)[0] + ".png"

    resized.save(save_path, "PNG")
    return save_path, resized.size


HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Basketball Portrait Studio | 180x180 Headshot Studio</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg: #090d16;
      --panel: #111827;
      --panel-border: #1f293d;
      --primary: #f97316;
      --primary-hover: #ea580c;
      --accent: #38bdf8;
      --success: #10b981;
      --danger: #ef4444;
      --text: #f8fafc;
      --text-muted: #94a3b8;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: var(--bg);
      color: var(--text);
      font-family: 'Plus Jakarta Sans', sans-serif;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      overflow: hidden;
      user-select: none;
    }

    /* PAGE 1: FOLDER SELECTION LANDING SCREEN */
    #page-folder-select {
      display: flex;
      flex-direction: column;
      height: 100vh;
      overflow-y: auto;
      padding: 40px 24px;
      align-items: center;
      background: radial-gradient(circle at 50% 10%, #151f33 0%, #090d16 80%);
    }
    .landing-hero {
      text-align: center;
      max-width: 720px;
      margin-bottom: 32px;
    }
    .hero-badge {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      background: rgba(249, 115, 22, 0.12);
      border: 1px solid rgba(249, 115, 22, 0.3);
      color: var(--primary);
      padding: 6px 14px;
      border-radius: 30px;
      font-size: 0.8rem;
      font-weight: 700;
      margin-bottom: 14px;
    }
    .landing-title {
      font-size: 2.2rem;
      font-weight: 800;
      letter-spacing: -0.02em;
      margin-bottom: 10px;
    }
    .landing-title span { color: var(--primary); }
    .landing-subtitle {
      font-size: 0.95rem;
      color: var(--text-muted);
      line-height: 1.5;
    }

    .folder-action-card {
      width: 100%;
      max-width: 820px;
      background: #111827;
      border: 2px dashed #28354f;
      border-radius: 16px;
      padding: 32px;
      text-align: center;
      margin-bottom: 36px;
      transition: all 0.2s;
    }
    .folder-action-card:hover {
      border-color: var(--primary);
      box-shadow: 0 10px 30px rgba(249, 115, 22, 0.15);
    }
    .browse-btn-big {
      background: linear-gradient(135deg, #f97316, #ea580c);
      color: #fff;
      border: none;
      padding: 14px 28px;
      border-radius: 12px;
      font-size: 1.05rem;
      font-weight: 700;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 10px;
      box-shadow: 0 4px 18px rgba(249, 115, 22, 0.35);
      transition: transform 0.15s;
    }
    .browse-btn-big:hover { transform: translateY(-2px); }

    .path-input-row {
      display: flex;
      gap: 10px;
      max-width: 660px;
      margin: 20px auto 0 auto;
    }
    .path-input {
      flex: 1;
      background: #090e1a;
      border: 1px solid #1f293d;
      border-radius: 8px;
      padding: 10px 14px;
      color: #fff;
      font-family: 'JetBrains Mono', monospace;
      font-size: 0.85rem;
      outline: none;
    }
    .path-input:focus { border-color: var(--primary); }

    .detected-section {
      width: 100%;
      max-width: 960px;
    }
    .detected-heading {
      font-size: 1rem;
      font-weight: 700;
      margin-bottom: 14px;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
    .detected-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
      gap: 14px;
    }
    .folder-card {
      background: #111827;
      border: 1px solid #1f293d;
      border-radius: 12px;
      padding: 16px;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 14px;
      transition: all 0.2s;
    }
    .folder-card:hover {
      background: #172033;
      border-color: var(--primary);
      transform: translateY(-2px);
      box-shadow: 0 6px 18px rgba(0,0,0,0.4);
    }
    .folder-icon {
      font-size: 26px;
      background: #1c263b;
      padding: 8px 12px;
      border-radius: 10px;
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
      color: #fff;
    }
    .folder-card-sub {
      font-size: 0.72rem;
      color: var(--text-muted);
      margin-top: 2px;
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .photo-count-pill {
      background: rgba(56, 189, 248, 0.12);
      color: var(--accent);
      padding: 1px 6px;
      border-radius: 10px;
      font-weight: 700;
    }

    /* PAGE 2: WORKBENCH / STUDIO SCREEN */
    #page-workbench {
      display: none;
      flex-direction: column;
      height: 100vh;
      overflow: hidden;
    }
    header {
      background: #0f172a;
      border-bottom: 1px solid var(--panel-border);
      padding: 10px 20px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      height: 64px;
      flex-shrink: 0;
    }
    .header-left {
      display: flex;
      align-items: center;
      gap: 12px;
    }
    .header-actions {
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .btn {
      padding: 7px 14px;
      border-radius: 8px;
      font-weight: 700;
      font-size: 0.82rem;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      border: 1px solid transparent;
      transition: all 0.15s;
    }
    .btn-primary {
      background: linear-gradient(135deg, #f97316, #ea580c);
      color: #fff;
      box-shadow: 0 4px 14px rgba(249, 115, 22, 0.3);
    }
    .btn-primary:hover { transform: translateY(-1px); }
    .btn-secondary {
      background: #1e293b;
      color: var(--text);
      border-color: #334155;
    }
    .btn-secondary:hover { background: #283548; }
    .btn:disabled { opacity: 0.5; cursor: not-allowed; }

    /* Workbench Columns */
    .workbench-body {
      display: flex;
      flex: 1;
      height: calc(100vh - 184px);
      overflow: hidden;
    }
    .sidebar {
      width: 330px;
      background: var(--panel);
      border-right: 1px solid var(--panel-border);
      padding: 16px;
      display: flex;
      flex-direction: column;
      gap: 14px;
      overflow-y: auto;
      flex-shrink: 0;
    }
    .section-label {
      font-size: 0.74rem;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: var(--text-muted);
      font-weight: 700;
      margin-bottom: 6px;
    }
    .box {
      background: #0a0f1d;
      border: 1px solid #1e293b;
      border-radius: 10px;
      padding: 12px;
    }
    .slider-row {
      display: flex;
      justify-content: space-between;
      margin-bottom: 6px;
      font-size: 0.8rem;
      font-weight: 600;
    }
    .pill {
      font-family: 'JetBrains Mono', monospace;
      color: var(--primary);
      background: rgba(249, 115, 22, 0.12);
      padding: 1px 6px;
      border-radius: 4px;
      font-size: 0.75rem;
    }
    input[type=range] {
      width: 100%;
      height: 5px;
      background: #1e293b;
      border-radius: 3px;
      outline: none;
      -webkit-appearance: none;
      cursor: pointer;
    }
    input[type=range]::-webkit-slider-thumb {
      -webkit-appearance: none;
      width: 15px;
      height: 15px;
      border-radius: 50%;
      background: var(--primary);
      cursor: pointer;
    }
    .tool-tabs {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 6px;
      margin-bottom: 10px;
    }
    .tool-tab {
      background: #1a2234;
      border: 1px solid #28354f;
      color: var(--text-muted);
      padding: 8px 4px;
      border-radius: 8px;
      font-size: 0.75rem;
      font-weight: 700;
      cursor: pointer;
      text-align: center;
      transition: all 0.15s;
    }
    .tool-tab:hover { color: #fff; background: #232e47; }
    .tool-tab.active {
      background: rgba(249, 115, 22, 0.15);
      border-color: var(--primary);
      color: #fff;
    }
    .btn-grid {
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: 6px;
      margin-top: 8px;
    }
    .btn-sm {
      background: #1a2234;
      border: 1px solid #28354f;
      color: var(--text);
      padding: 6px;
      border-radius: 6px;
      font-size: 0.75rem;
      font-weight: 600;
      cursor: pointer;
      text-align: center;
    }
    .btn-sm:hover { background: #25334c; border-color: var(--accent); }

    /* Center Stage */
    .stage {
      flex: 1;
      background: radial-gradient(circle at center, #131b2e 0%, #0a0e17 100%);
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      position: relative;
      overflow: hidden;
    }
    .stage-toolbar {
      position: absolute;
      top: 14px;
      display: flex;
      gap: 8px;
      background: rgba(17, 24, 39, 0.85);
      backdrop-filter: blur(8px);
      padding: 5px 12px;
      border-radius: 30px;
      border: 1px solid var(--panel-border);
      z-index: 10;
    }
    .chip {
      background: transparent;
      border: none;
      color: var(--text-muted);
      font-size: 0.78rem;
      font-weight: 600;
      padding: 3px 9px;
      border-radius: 20px;
      cursor: pointer;
    }
    .chip.active, .chip:hover { color: #fff; background: #1f293d; }

    .viewport-outer {
      position: relative;
      padding: 6px;
      border: 2px dashed rgba(249, 115, 22, 0.55);
      border-radius: 12px;
      background: rgba(0, 0, 0, 0.5);
      box-shadow: 0 20px 50px rgba(0, 0, 0, 0.6);
    }
    .viewport-container {
      width: 440px;
      height: 440px;
      position: relative;
      overflow: hidden;
      border-radius: 6px;
    }
    .checkerboard {
      background-image: 
        linear-gradient(45deg, #1e293b 25%, transparent 25%), 
        linear-gradient(-45deg, #1e293b 25%, transparent 25%), 
        linear-gradient(45deg, transparent 75%, #1e293b 75%), 
        linear-gradient(-45deg, transparent 75%, #1e293b 75%);
      background-size: 20px 20px;
      background-position: 0 0, 0 10px, 10px -10px, -10px 0px;
      background-color: #0b0f19;
    }
    canvas#editor-canvas {
      position: absolute;
      top: 0; left: 0; width: 100%; height: 100%;
      touch-action: none;
    }
    #brush-cursor {
      position: absolute;
      border: 2px solid rgba(255, 255, 255, 0.85);
      border-radius: 50%;
      pointer-events: none;
      transform: translate(-50%, -50%);
      display: none;
      z-index: 100;
    }
    .cursor-recover { border-color: #10b981 !important; background: rgba(16, 185, 129, 0.2); }
    .cursor-erase { border-color: #ef4444 !important; background: rgba(239, 68, 68, 0.2); }

    .stage-hint {
      position: absolute;
      bottom: 12px;
      font-size: 0.75rem;
      color: var(--text-muted);
      background: rgba(17, 24, 39, 0.8);
      padding: 5px 12px;
      border-radius: 20px;
      border: 1px solid var(--panel-border);
      display: flex;
      align-items: center;
      gap: 10px;
    }

    /* Carousel */
    .carousel-bar {
      height: 120px;
      background: var(--panel);
      border-top: 1px solid var(--panel-border);
      padding: 8px 16px;
      display: flex;
      align-items: center;
      gap: 10px;
      overflow-x: auto;
      flex-shrink: 0;
    }
    .carousel-item {
      display: flex;
      flex-direction: column;
      align-items: center;
      padding: 5px;
      background: #0a0f1d;
      border: 2px solid transparent;
      border-radius: 8px;
      cursor: pointer;
      min-width: 78px;
      transition: all 0.15s;
      position: relative;
    }
    .carousel-item:hover { border-color: #38bdf8; transform: translateY(-2px); }
    .carousel-item.active { border-color: var(--primary); background: rgba(249, 115, 22, 0.12); }
    .carousel-item img { width: 50px; height: 60px; object-fit: cover; border-radius: 4px; }
    .carousel-item span {
      font-size: 0.65rem;
      font-family: 'JetBrains Mono', monospace;
      margin-top: 3px;
      color: var(--text-muted);
      max-width: 68px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .status-dot {
      position: absolute;
      top: 4px; right: 4px; width: 8px; height: 8px;
      border-radius: 50%; background: #64748b;
    }
    .status-dot.saved { background: var(--success); box-shadow: 0 0 6px var(--success); }
    .status-dot.cutout { background: var(--accent); }

    /* Loading overlay */
    .loading-overlay {
      position: fixed;
      top: 0; left: 0; right: 0; bottom: 0;
      background: rgba(9, 13, 22, 0.88);
      display: none;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 14px;
      z-index: 99999;
      backdrop-filter: blur(4px);
    }
    .spinner {
      width: 28px; height: 28px;
      border: 3px solid rgba(255,255,255,0.2);
      border-top-color: var(--primary);
      border-radius: 50%;
      animation: spin 0.8s linear infinite;
    }
    @keyframes spin { to { transform: rotate(360deg); } }

    /* LANDING PAGE TABS */
    .landing-tabs-bar {
      display: inline-flex;
      background: #0f172a;
      border: 1px solid #1f293d;
      border-radius: 12px;
      padding: 4px;
      gap: 6px;
      margin-bottom: 24px;
    }
    .landing-tab {
      background: transparent;
      border: none;
      color: var(--text-muted);
      padding: 10px 22px;
      border-radius: 8px;
      font-size: 0.9rem;
      font-weight: 700;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 8px;
      transition: all 0.2s;
    }
    .landing-tab:hover {
      color: #fff;
      background: rgba(255, 255, 255, 0.05);
    }
    .landing-tab.active {
      background: linear-gradient(135deg, #f97316, #ea580c);
      color: #fff;
      box-shadow: 0 4px 14px rgba(249, 115, 22, 0.35);
    }

    /* ROSTER DOWNLOAD CONTAINER */
    #view-roster-download {
      display: none;
      width: 100%;
      max-width: 960px;
      flex-direction: column;
      align-items: center;
    }
    .roster-config-card {
      width: 100%;
      background: #111827;
      border: 1px solid #1f293d;
      border-radius: 16px;
      padding: 24px 28px;
      margin-bottom: 24px;
    }
    .roster-input-grid {
      display: grid;
      grid-template-columns: 2fr 1fr auto;
      gap: 12px;
      align-items: flex-end;
    }
    .input-group {
      display: flex;
      flex-direction: column;
      gap: 6px;
      text-align: left;
    }
    .input-label {
      font-size: 0.78rem;
      font-weight: 700;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }
    .roster-text-input {
      background: #090e1a;
      border: 1px solid #1f293d;
      border-radius: 8px;
      padding: 11px 14px;
      color: #fff;
      font-family: 'Plus Jakarta Sans', sans-serif;
      font-size: 0.88rem;
      outline: none;
      transition: border-color 0.2s;
    }
    .roster-text-input:focus {
      border-color: var(--primary);
    }
    .quality-boost-tag {
      margin-top: 12px;
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 0.76rem;
      color: #38bdf8;
      background: rgba(56, 189, 248, 0.1);
      padding: 6px 12px;
      border-radius: 6px;
      border: 1px solid rgba(56, 189, 248, 0.2);
    }

    /* ROSTER PLAYERS TABLE & CARD */
    .roster-results-card {
      width: 100%;
      background: #111827;
      border: 1px solid #1f293d;
      border-radius: 16px;
      padding: 20px 24px;
      margin-bottom: 30px;
    }
    .roster-header-bar {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 16px;
      flex-wrap: wrap;
      gap: 12px;
    }
    .roster-title-badge {
      font-size: 1.05rem;
      font-weight: 800;
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .bulk-paste-drawer {
      display: none;
      background: #0a0f1d;
      border: 1px solid #28354f;
      border-radius: 10px;
      padding: 14px;
      margin-bottom: 16px;
    }
    .bulk-paste-textarea {
      width: 100%;
      height: 110px;
      background: #060911;
      border: 1px solid #1f293d;
      border-radius: 6px;
      padding: 10px;
      color: #fff;
      font-family: 'JetBrains Mono', monospace;
      font-size: 0.8rem;
      resize: vertical;
      outline: none;
      margin-bottom: 8px;
    }
    .bulk-paste-textarea:focus { border-color: var(--primary); }

    .roster-table {
      width: 100%;
      border-collapse: separate;
      border-spacing: 0 6px;
      user-select: text;
    }
    .roster-table th {
      padding: 8px 12px;
      font-size: 0.72rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--text-muted);
      text-align: left;
      white-space: nowrap;
      user-select: text;
    }
    .roster-row {
      background: #0d1322;
      border: 1px solid #1f293d;
      transition: background 0.15s;
    }
    .roster-row:hover {
      background: #141c2e;
    }
    .roster-cell {
      padding: 8px 12px;
      vertical-align: middle;
      border-top: 1px solid #1c263b;
      border-bottom: 1px solid #1c263b;
      font-size: 0.85rem;
      user-select: text;
    }
    .roster-cell:first-child {
      border-left: 1px solid #1c263b;
      border-top-left-radius: 8px;
      border-bottom-left-radius: 8px;
    }
    .roster-cell:last-child {
      border-right: 1px solid #1c263b;
      border-top-right-radius: 8px;
      border-bottom-right-radius: 8px;
    }
    .player-cell-content {
      display: flex;
      align-items: center;
      gap: 12px;
    }
    .player-avatar-circle {
      width: 42px;
      height: 42px;
      border-radius: 50%;
      object-fit: cover;
      background: #1e293b;
      border: 2px solid #3b82f6;
      flex-shrink: 0;
      transition: transform 0.2s, box-shadow 0.2s;
    }
    .player-avatar-circle:hover {
      transform: scale(2.2);
      z-index: 99;
      position: relative;
      box-shadow: 0 8px 24px rgba(0,0,0,0.8);
    }
    .player-name-text {
      font-size: 0.92rem;
      font-weight: 700;
      color: #fff;
      white-space: nowrap;
    }
    .btn-sheet-copy {
      background: #2563eb !important;
      border-color: #3b82f6 !important;
      color: #fff !important;
      font-weight: 700 !important;
    }
    .btn-sheet-copy:hover {
      background: #1d4ed8 !important;
      border-color: #60a5fa !important;
      box-shadow: 0 0 12px rgba(37, 99, 235, 0.4);
    }
    .player-meta-text {
      font-size: 0.74rem;
      color: var(--text-muted);
      display: flex;
      align-items: center;
      gap: 6px;
      margin-top: 2px;
      flex-wrap: wrap;
    }
    .player-details-text {
      font-size: 0.73rem;
      color: #94a3b8;
      margin-top: 4px;
      line-height: 1.35;
      font-weight: 500;
    }
    .preset-pill {
      background: rgba(255, 255, 255, 0.06);
      border: 1px solid rgba(255, 255, 255, 0.14);
      color: #cbd5e1;
      border-radius: 9999px;
      padding: 5px 12px;
      font-size: 0.76rem;
      font-weight: 600;
      cursor: pointer;
      transition: all 0.2s;
      font-family: inherit;
      display: inline-flex;
      align-items: center;
      gap: 5px;
    }
    .preset-pill:hover {
      background: rgba(249, 115, 22, 0.18);
      border-color: rgba(249, 115, 22, 0.5);
      color: #fed7aa;
      transform: translateY(-1px);
    }
    .assign-input {
      background: #060911;
      border: 1px solid #28354f;
      border-radius: 6px;
      padding: 8px 10px;
      color: #fff;
      font-family: 'JetBrains Mono', monospace;
      font-size: 0.88rem;
      width: 180px;
      outline: none;
      transition: all 0.2s;
    }
    .assign-input:focus {
      border-color: var(--primary);
      box-shadow: 0 0 8px rgba(249, 115, 22, 0.3);
    }
    .filename-preview-badge {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 4px 10px;
      border-radius: 6px;
      font-family: 'JetBrains Mono', monospace;
      font-size: 0.78rem;
      font-weight: 600;
    }
    .badge-assigned {
      background: rgba(249, 115, 22, 0.15);
      border: 1px solid rgba(249, 115, 22, 0.4);
      color: #fb923c;
    }
    .badge-default-name {
      background: rgba(56, 189, 248, 0.12);
      border: 1px solid rgba(56, 189, 248, 0.35);
      color: #7dd3fc;
    }

    /* DOWNLOAD FOOTER ACTION BAR */
    .roster-footer-bar {
      margin-top: 18px;
      padding-top: 16px;
      border-top: 1px solid #1f293d;
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 12px;
    }
    .roster-summary-text {
      font-size: 0.85rem;
      color: var(--text-muted);
    }
    .roster-summary-text strong {
      color: #fff;
    }
  </style>
</head>
<body>
  <!-- Native Folder Picker Input -->
  <input type="file" id="native-folder-picker" webkitdirectory directory multiple style="display:none;" onchange="onNativeFolderPicked(event)">

  <!-- PAGE 1: FOLDER SELECTION & ROSTER DOWNLOAD LANDING SCREEN -->
  <div id="page-folder-select">
    <div class="landing-hero">
      <div class="hero-badge">🏀 Automated Headshot Processor</div>
      <h1 class="landing-title">Basketball <span>Portrait Studio</span></h1>
      <p class="landing-subtitle">
        Download high-resolution roster portraits with custom player ID assignment, or select an existing local folder to crop into standardized 180×180 transparent headshots.
      </p>
    </div>

    <!-- Mode Selector Tabs -->
    <div class="landing-tabs-bar">
      <button class="landing-tab active" id="tab-btn-local" onclick="switchLandingTab('local')">
        <span>📂 Open Local Folder</span>
      </button>
      <button class="landing-tab" id="tab-btn-roster" onclick="switchLandingTab('roster')">
        <span>📥 Download Roster & Assign Numbers</span>
      </button>
    </div>

    <!-- VIEW A: LOCAL FOLDER SELECTION -->
    <div id="view-local-folder" style="width: 100%; max-width: 960px; display: flex; flex-direction: column; align-items: center;">
      <!-- Folder Action Box -->
      <div class="folder-action-card" id="folder-drop-zone">
        <label for="native-folder-picker" class="browse-btn-big" style="cursor: pointer;">
          <span>📂 Browse & Choose Local Folder...</span>
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
          <span>📁 Detected Photo Folders in Downloads</span>
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
            <button class="btn btn-primary" style="padding: 12px 20px; font-size: 0.9rem;" onclick="fetchRosterPlayers()">
              <span>🔍 Fetch Players</span>
            </button>
          </div>
        </div>

        <!-- Quick Presets -->
        <div style="display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin-top:12px;">
          <span style="font-size:0.75rem; color:var(--text-muted); font-weight:700;">Quick Presets:</span>
          <button type="button" class="preset-pill" onclick="setPresetUrl('https://www.cardiffdevils.com/team/', 'Cardiff Devils')">🇬🇧 Cardiff Devils (EIHL)</button>
          <button type="button" class="preset-pill" onclick="setPresetUrl('https://coventryblaze.co.uk/roster', 'Coventry Blaze')">🇬🇧 Coventry Blaze (EIHL)</button>
          <button type="button" class="preset-pill" onclick="setPresetUrl('https://www.belfastgiants.com/players', 'Belfast Giants')">🇬🇧 Belfast Giants (EIHL)</button>
          <button type="button" class="preset-pill" onclick="setPresetUrl('https://www.nhl.com/sabres/roster', 'Buffalo Sabres')">🏒 Buffalo Sabres (NHL)</button>
          <button type="button" class="preset-pill" onclick="setPresetUrl('https://smcathletics.com/sports/mens-basketball/roster/2025-26', 'Saint Michael\'s College')">🏀 Saint Michael's (NCAA)</button>
        </div>

        <div class="quality-boost-tag">
          <span>⚡</span>
          <span><strong>Automatic High Quality:</strong> High-res transparent headshots standardized with Lanczos downsampling to width 800px.</span>
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
              <span>📋 Copy for Sheets / Excel</span>
            </button>
            <button class="btn btn-secondary" onclick="exportRosterToCSV()" title="Download full roster as CSV spreadsheet">
              <span>📥 Export CSV</span>
            </button>
            <button class="btn btn-secondary" onclick="useJerseyNumbersAsAssigned()" title="Assign every player's jersey number as their file ID">
              <span>🔢 Use Jersey # as File ID</span>
            </button>
            <button class="btn btn-secondary" onclick="toggleBulkPasteDrawer()">
              <span>📋 Bulk Paste IDs</span>
            </button>
            <button class="btn btn-secondary" onclick="clearAllAssignedNumbers()">
              <span>🔄 Clear IDs</span>
            </button>
          </div>
        </div>

        <!-- Bulk Paste Drawer -->
        <div class="bulk-paste-drawer" id="bulk-paste-drawer">
          <div style="font-size:0.8rem; font-weight:700; color:#fff; margin-bottom:6px;">
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
          <button class="btn btn-primary" id="btn-download-roster" style="padding: 10px 24px; font-size: 0.92rem;" onclick="downloadAllRosterPhotos()">
            <span>🚀 Download All Photos (Width 800)</span>
          </button>
        </div>
      </div>

      <!-- Success Card -->
      <div class="roster-results-card" id="roster-success-card" style="display: none; text-align: center; border-color: rgba(16, 185, 129, 0.4); background: rgba(16, 185, 129, 0.05);">
        <div style="font-size: 2.2rem; margin-bottom: 8px;">🎉</div>
        <h3 style="font-size: 1.25rem; font-weight: 800; color: #fff; margin-bottom: 6px;">Photos Downloaded & Standardized!</h3>
        <p style="color: var(--text-muted); font-size: 0.88rem; margin-bottom: 16px;" id="roster-success-desc">
          All portraits were downloaded at high resolution (width 800) with their assigned numbers and names.
        </p>
        <div style="display:flex; justify-content:center; gap:12px; margin-top:8px; flex-wrap:wrap;">
          <button class="btn btn-primary" style="padding: 12px 28px; font-size: 1rem; font-weight:700;" onclick="openDownloadedFolderInStudio()">
            <span>🎨 Open Directly in Studio Workbench</span>
          </button>
          <button class="btn btn-secondary" style="padding: 12px 24px; font-size: 0.95rem; font-weight:700; background:#0284c7; border-color:#38bdf8; color:#fff;" onclick="downloadRosterZip()">
            <span>📦 Download All as ZIP</span>
          </button>
          <button class="btn btn-secondary" style="padding: 12px 20px; font-size: 0.9rem;" onclick="backToRosterView()">
            <span>📋 Back to Roster List</span>
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
          <span>⬅️ Change Folder</span>
        </button>
        <div style="display:flex; flex-direction:column;">
          <div style="font-size:0.88rem; font-weight:800;" id="active-folder-name">Folder Name</div>
          <div style="font-size:0.7rem; color:var(--accent); font-family:'JetBrains Mono', monospace;" id="active-output-name">→ folder_edited/</div>
        </div>
      </div>

      <div class="header-actions">
        <button class="btn btn-secondary" id="btn-cutout" onclick="triggerCutout()">
          <span>✨ AI Cutout</span>
        </button>
        <button class="btn btn-secondary" onclick="saveActivePhoto()">
          <span>💾 Save Headshot</span>
        </button>
        <button class="btn btn-primary" id="btn-batch-all" onclick="batchProcessFolder()">
          <span>⚡ Process All</span>
        </button>
        <button class="btn btn-secondary" style="border-color:#38bdf8; color:#38bdf8; font-weight:700;" onclick="downloadActiveEditedZip()" title="Download all edited headshots as a ZIP file">
          <span>📦 Download ZIP</span>
        </button>
      </div>
    </header>

    <div class="workbench-body">
      <!-- Left Sidebar -->
      <div class="sidebar">
        <div class="section-label">Tool Mode</div>
        <div class="tool-tabs">
          <button class="tool-tab active" id="tab-frame" onclick="setMode('frame')">🖐️ Pan & Zoom</button>
          <button class="tool-tab" id="tab-recover" onclick="setMode('recover')">🖌️ Recover</button>
          <button class="tool-tab" id="tab-erase" onclick="setMode('erase')">🧹 Erase</button>
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
              <button class="btn-sm" onclick="autoAlignCurrent()">🎯 Auto-Align Face</button>
              <button class="btn-sm" onclick="fitWidth()">↔️ Fit Width</button>
              <button class="btn-sm" onclick="fitHeight()">↕️ Fit Height</button>
              <button class="btn-sm" onclick="centerPhoto()">📍 Center</button>
            </div>
          </div>

          <div class="section-label" style="margin-top:12px;">Team Batch Framing</div>
          <div class="box">
            <p style="font-size:0.75rem; color:var(--text-muted); margin-bottom:8px;">
              Apply this portrait's exact scale & position across all photos in folder:
            </p>
            <button class="btn btn-secondary" style="width:100%; justify-content:center; font-size:0.75rem;" onclick="applyFramingToAll()">
              <span>📋 Apply Framing to All</span>
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
              <button class="btn-sm" style="flex:1;" onclick="undoMask()">↩️ Undo</button>
              <button class="btn-sm" style="flex:1;" onclick="resetMaskToCutout()">🔄 Reset Cutout</button>
            </div>
            <p style="font-size:0.72rem; color:var(--text-muted); margin-top:8px; line-height:1.4;">
              💡 <strong>Recover</strong> restores lost hair/collar from original photo.<br>
              💡 <strong>Erase</strong> cleans up leftover background fragments.
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
          <button class="chip active" id="chip-check" onclick="setBg('checker')">🏁 Transparent</button>
          <button class="chip" id="chip-dark" onclick="setBg('dark')">⬛ Dark</button>
          <button class="chip" id="chip-white" onclick="setBg('white')">⬜ White</button>
          <button class="chip" id="chip-team" onclick="setBg('team')">🏀 Team Navy</button>
          <span style="width:1px; height:14px; background:#28354f; align-self:center;"></span>
          <button class="chip" id="chip-compare" onmousedown="showOriginal(true)" onmouseup="showOriginal(false)" onmouseleave="showOriginal(false)">👁️ Hold: View Original</button>
        </div>

        <div class="viewport-outer">
          <div class="viewport-container checkerboard" id="viewport">
            <canvas id="editor-canvas" width="540" height="540"></canvas>
            <div id="brush-cursor"></div>
          </div>
        </div>

        <div class="stage-hint">
          <span id="hint-text">🖐️ Drag photo to position • Wheel to zoom</span>
          <span>•</span>
          <span id="pos-info" style="font-family:'JetBrains Mono', monospace; color:var(--accent);">x: 0, y: 0</span>
        </div>
      </div>
    </div>

    <!-- Bottom Carousel Bar -->
    <div class="carousel-bar" id="carousel"></div>
  </div>

  <!-- Global Loading Overlay -->
  <div class="loading-overlay" id="loading-overlay">
    <div class="spinner"></div>
    <div id="loading-text" style="font-size:0.88rem; font-weight:700; color:#fff;">Processing...</div>
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
      // Load suggested folders on first page
      try {
        const res = await fetch('/api/suggested_folders');
        const data = await res.json();
        renderDetectedFolders(data.suggestions_data || []);
      } catch (e) {
        console.error(e);
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
          <div class="folder-icon">🏀</div>
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
          dropZone.style.background = '#1e293b';
        });
      });

      ['dragleave', 'drop'].forEach(eventName => {
        dropZone.addEventListener(eventName, (e) => {
          e.preventDefault();
          e.stopPropagation();
          dropZone.style.borderColor = '#28354f';
          dropZone.style.background = '#111827';
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

    async function selectPhoto(index) {
      if (index < 0 || index >= photos.length) return;
      currentIndex = index;
      document.querySelectorAll('.carousel-item').forEach((el, i) => {
        el.classList.toggle('active', i === index);
      });

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
          const autoRes = await fetch(`/api/auto_align?folder=${encodeURIComponent(currentFolder)}&name=${encodeURIComponent(name)}`);
          if (autoRes.ok) {
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
        const canvasX = (clientX / VIEWPORT_PX) * BUFFER_PX;
        const canvasY = (clientY / VIEWPORT_PX) * BUFFER_PX;

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
          const dx = ((e.clientX - dragStartX) / VIEWPORT_PX) * CANVAS_PX;
          const dy = ((e.clientY - dragStartY) / VIEWPORT_PX) * CANVAS_PX;
          dragStartX = e.clientX;
          dragStartY = e.clientY;

          const data = photoData[photos[currentIndex]];
          data.offset_x += dx;
          data.offset_y += dy;
          render();
        } else if (isPainting) {
          const clientX = e.clientX - rect.left;
          const clientY = e.clientY - rect.top;
          const canvasX = (clientX / VIEWPORT_PX) * BUFFER_PX;
          const canvasY = (clientY / VIEWPORT_PX) * BUFFER_PX;
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
        const mouseX = ((e.clientX - rect.left) / VIEWPORT_PX) * CANVAS_PX;
        const mouseY = ((e.clientY - rect.top) / VIEWPORT_PX) * CANVAS_PX;

        const zoomFactor = e.deltaY < 0 ? 1.06 : 0.94;
        const oldScale = data.scale;
        const newScale = Math.max(0.05, Math.min(2.0, oldScale * zoomFactor));

        data.offset_x = mouseX - (mouseX - data.offset_x) * (newScale / oldScale);
        data.offset_y = mouseY - (mouseY - data.offset_y) * (newScale / oldScale);
        data.scale = newScale;

        syncZoomSlider();
        render();
      }, { passive: false });
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

      brushCursor.className = mode === 'recover' ? 'cursor-recover' : (mode === 'erase' ? 'cursor-erase' : '');
      const sizePx = brushRadius * 2 * (VIEWPORT_PX / BUFFER_PX);
      brushCursor.style.width = sizePx + 'px';
      brushCursor.style.height = sizePx + 'px';

      const hintEl = document.getElementById('hint-text');
      if (mode === 'frame') {
        hintEl.textContent = '🖐️ Drag photo freely to position • Wheel to zoom';
        viewport.style.cursor = 'grab';
      } else if (mode === 'recover') {
        hintEl.textContent = '🖌️ Painting with RECOVER brush (restores original photo)';
        viewport.style.cursor = 'crosshair';
      } else {
        hintEl.textContent = '🧹 Painting with ERASE brush (removes background)';
        viewport.style.cursor = 'crosshair';
      }
    }

    function setBrushSize(val) {
      brushRadius = parseInt(val);
      document.getElementById('brush-size-badge').textContent = val + ' px';
      const sizePx = brushRadius * 2 * (VIEWPORT_PX / BUFFER_PX);
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
        const res = await fetch('/api/preview_cutout', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            folder: currentFolder,
            photo: name,
            scale: data.scale,
            offset_x: data.offset_x,
            offset_y: data.offset_y
          })
        });
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
        alert('Cutout failed: ' + e);
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

      try {
        const res = await fetch('/api/save_refined_data', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            folder: currentFolder,
            filename: name,
            image_base64: b64
          })
        });
        if (!res.ok) {
          const errText = await res.text();
          try {
            const errJson = JSON.parse(errText);
            throw new Error(errJson.message || errText);
          } catch (_) {
            throw new Error(`HTTP ${res.status}: ${errText.substring(0, 100)}`);
          }
        }
        const json = await res.json();
        photoData[name].saved = true;
        document.getElementById(`dot-${currentIndex}`).className = 'status-dot saved';
        alert(`✅ Saved: ${json.output_name} to ${json.folder_name}/`);
      } catch (e) {
        alert('Save error: ' + (e.message || e));
      } finally {
        hideLoading();
      }
    }

    async function batchProcessFolder() {
      if (!confirm(`Process and export all ${photos.length} portraits into ${editedFolder.split('/').pop()}?`)) return;
      const btn = document.getElementById('btn-batch-all');
      btn.disabled = true;
      let completed = 0;
      let errors = 0;

      showLoading(`Starting batch export for ${photos.length} portraits...`);

      for (let i = 0; i < photos.length; i++) {
        const name = photos[i];
        const pct = Math.round(((i + 1) / photos.length) * 100);
        showLoading(`Processing ${i + 1} of ${photos.length}: ${name} (${pct}%)...`);

        const pData = photoData[name] || { scale: 0.35, offset_x: 0, offset_y: 0 };
        try {
          const res = await fetch('/api/process_single_portrait', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              folder: currentFolder,
              photo: name,
              scale: pData.scale,
              offset_x: pData.offset_x,
              offset_y: pData.offset_y
            })
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
          } else {
            errors++;
          }
        } catch (err) {
          errors++;
          console.error(`Failed to process ${name}:`, err);
        }
      }

      hideLoading();
      btn.disabled = false;
      const editedBase = editedFolder.split('/').pop() || 'folder_edited';
      alert(`🎉 Batch Complete!\nSuccessfully saved ${completed} of ${photos.length} portraits into ${editedBase}/` + (errors > 0 ? `\n(${errors} items failed)` : ''));
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
      showLoading('Auto-aligning face...');
      const res = await fetch(`/api/auto_align?folder=${encodeURIComponent(currentFolder)}&name=${encodeURIComponent(name)}`);
      const autoData = await res.json();
      const data = photoData[name];
      data.scale = autoData.scale;
      data.offset_x = autoData.offset_x;
      data.offset_y = autoData.offset_y;
      hideLoading();
      syncZoomSlider();
      render();
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
      showToast(`📥 Exported ${teamName}_Roster.csv successfully!`);
    }

    function showToast(msg) {
      let toast = document.getElementById('studio-toast');
      if (!toast) {
        toast = document.createElement('div');
        toast.id = 'studio-toast';
        toast.style.cssText = 'position:fixed; bottom:28px; left:50%; transform:translateX(-50%); background:#0f172a; border:1px solid #38bdf8; color:#fff; padding:12px 24px; border-radius:30px; font-size:0.88rem; font-weight:700; box-shadow:0 10px 35px rgba(0,0,0,0.85); z-index:99999; display:flex; align-items:center; gap:8px; opacity:0; transition:opacity 0.25s, transform 0.25s; pointer-events:none;';
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
        cell.innerHTML = `<span class="filename-preview-badge badge-assigned">📄 ${cleanVal}.png</span>`;
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

      showLoading(`Downloading & standardizing ${fetchedRosterPlayers.length} photos at width=800...`);
      try {
        const res = await fetch('/api/download_roster_players', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (data.status !== 'ok') {
          alert('Download error: ' + (data.message || 'Unknown error'));
          return;
        }

        currentRosterTargetDir = data.target_dir;
        document.getElementById('roster-results-card').style.display = 'none';
        document.getElementById('roster-success-card').style.display = 'block';
        document.getElementById('roster-success-desc').textContent = 
          `Saved ${data.saved_count} photos to "${data.folder_name}" in Downloads (scaled to width 800 with Lanczos).`;
      } catch (e) {
        alert('Error downloading: ' + e);
      } finally {
        hideLoading();
      }
    }

    function openDownloadedFolderInStudio() {
      if (currentRosterTargetDir) {
        openFolder(currentRosterTargetDir);
      }
    }

    function downloadRosterZip() {
      if (currentRosterTargetDir) {
        window.location.href = '/api/export_folder_zip?folder=' + encodeURIComponent(currentRosterTargetDir);
      }
    }

    function downloadActiveEditedZip() {
      if (!currentFolder) {
        showToast("No active folder loaded", "error");
        return;
      }
      const target = editedFolder || (currentFolder + '_edited');
      window.location.href = '/api/export_folder_zip?folder=' + encodeURIComponent(target);
    }

    window.onload = init;
  </script>
</body>
</html>
"""


class StudioServerHandler(BaseHTTPRequestHandler):
    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        params = urllib.parse.parse_qs(parsed.query)

        if path == "/healthz" or path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"OK")
            return

        if path == "/" or path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            self.end_headers()
            self.wfile.write(HTML_PAGE.encode("utf-8"))

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
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query)
            content_len = int(self.headers.get("Content-Length", 0))

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

            if parsed.path == "/api/resolve_folder_name":
                fname = data.get("folder_name", "")
                found_path = resolve_input_path(fname)

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "found": found_path is not None,
                    "path": found_path
                }).encode("utf-8"))

            elif parsed.path == "/api/preview_cutout":
                raw_folder = data.get("folder", ".")
                folder = resolve_input_path(raw_folder) or raw_folder
                photo = data.get("photo", "")
                scale = float(data.get("scale", 0.35))
                offset_x = float(data.get("offset_x", 0))
                offset_y = float(data.get("offset_y", 0))

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
                raw_folder = data.get("folder", ".")
                folder = resolve_input_path(raw_folder)
                if not folder:
                    workspace_dir = os.path.dirname(os.path.abspath(__file__))
                    folder = os.path.join(workspace_dir, "input_photos", os.path.basename(raw_folder))
                photo = data.get("photo", "")
                scale = float(data.get("scale", 0.35))
                offset_x = float(data.get("offset_x", 0))
                offset_y = float(data.get("offset_y", 0))

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

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "status": "ok",
                    "filename": clean_name,
                    "folder_name": os.path.basename(out_dir)
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
