#!/usr/bin/env python3
"""
Roster Downloader Script
Scrapes player portraits from athletic roster URLs (e.g. Sidearm Sports / NCAA),
resizes images proportionally to width=800 using high-quality Lanczos resampling,
and names each file according to the player's assigned ID number into a named folder.
"""

import os
import sys
import json
import re
import argparse
import urllib.request
from PIL import Image

# Auto-activate local .venv if not in virtualenv
script_dir = os.path.dirname(os.path.abspath(__file__))
venv_python = os.path.join(script_dir, ".venv", "bin", "python3")
if not os.environ.get("RENDER") and sys.prefix == sys.base_prefix and os.path.exists(venv_python) and sys.executable != venv_python:
    os.execv(venv_python, [venv_python] + sys.argv)


def scrape_roster(url: str):
    """
    Fetches roster and extracts player names, jerseys, positions, and photo URLs.
    Supports UK EIHL & Sports teams, NHL, and NCAA/Sidearm collegiate athletics sites.
    """
    try:
        from studio import scrape_roster_data
        res = scrape_roster_data(url)
        if res.get("players") and len(res["players"]) > 0:
            return res["players"]
    except Exception as e:
        print(f"[Notice] Routing through local collegiate scraper: {e}")

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
    )

    with urllib.request.urlopen(req) as resp:
        html = resp.read().decode("utf-8", errors="ignore")

    players = []

    # 1. Extract from Schema.org JSON-LD
    json_ld_matches = re.findall(r'<script type=\"application/ld\+json\">(.*?)</script>', html, re.DOTALL)
    for block in json_ld_matches:
        try:
            data = json.loads(block.strip())
            items = []
            if isinstance(data, dict):
                items = data.get("item", [])
            elif isinstance(data, list):
                items = data
            for it in items:
                name = it.get("name")
                img_obj = it.get("image")
                img_url = img_obj.get("url") if isinstance(img_obj, dict) else (img_obj if isinstance(img_obj, str) else "")
                profile_url = it.get("url", "")
                if name and img_url:
                    players.append({
                        "name": name.strip(),
                        "image": img_url.strip(),
                        "profile_url": profile_url,
                        "jersey": ""
                    })
        except Exception:
            pass

    # 2. Extract jersey numbers from table
    jerseys = re.findall(r'<td[^>]*class=\"[^\"]*jersey[^\"]*\"[^>]*>([^<]+)<', html)
    jerseys = [j.strip() for j in jerseys if j.strip()]

    if len(jerseys) >= len(players):
        for i, p in enumerate(players):
            p["jersey"] = jerseys[i]

    # Deduplicate players by name
    seen = set()
    unique_players = []
    for p in players:
        if p["name"] not in seen:
            seen.add(p["name"])
            unique_players.append(p)

    return unique_players


def boost_image_url_width(img_url: str, target_width: int = 1200) -> str:
    """Modifies or appends width parameter in URL to fetch high-res image from athletics CDN."""
    if not img_url:
        return ""
    if re.search(r'[?&]width=\d+', img_url):
        new_url = re.sub(r'([?&]width=)\d+', r'\g<1>' + str(target_width), img_url)
        if 'quality=' in new_url:
            new_url = re.sub(r'([?&]quality=)\d+', r'\g<1>100', new_url)
        else:
            new_url += '&quality=100'
        return new_url
    if any(k in img_url for k in ["/images/", "sidearm", "presto", "athletics"]):
        sep = '&' if '?' in img_url else '?'
        return f"{img_url}{sep}width={target_width}&quality=100"
    return img_url


def download_and_resize(img_url: str, save_path: str, target_width: int = 800):
    """
    Downloads high-resolution photo (with URL width boosted) and resizes proportionally so width=target_width.
    """
    high_res_url = boost_image_url_width(img_url, target_width=1200)
    raw_bytes = None

    for u in [high_res_url, img_url]:
        try:
            req = urllib.request.Request(
                u,
                headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw_bytes = resp.read()
            if raw_bytes:
                break
        except Exception:
            continue

    if not raw_bytes:
        raise ValueError(f"Could not download photo from: {img_url}")

    import io
    im = Image.open(io.BytesIO(raw_bytes))
    if im.mode not in ("RGB", "RGBA"):
        im = im.convert("RGBA" if "A" in im.mode else "RGB")

    # Resize proportionally to target width
    orig_w, orig_h = im.size
    scale = target_width / float(orig_w)
    new_h = int(round(orig_h * scale))

    resized = im.resize((target_width, new_h), Image.Resampling.LANCZOS)

    os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
    if not save_path.lower().endswith(".png"):
        save_path = os.path.splitext(save_path)[0] + ".png"

    resized.save(save_path, "PNG")
    return save_path, resized.size


def main():
    parser = argparse.ArgumentParser(description="Download roster profile photos resized to width 800")
    parser.add_argument("--url", "-u", required=True, help="Roster URL (e.g. https://smcathletics.com/sports/mens-basketball/roster/2025-26)")
    parser.add_argument("--folder", "-f", required=True, help="Target folder name (created in Downloads or current directory)")
    parser.add_argument("--mapping", "-m", default=None, help="JSON file or string mapping player names/jerseys to assigned numbers")
    args = parser.parse_args()

    # Determine destination folder (default to ~/Downloads/[folder])
    downloads_dir = os.path.expanduser("~/Downloads")
    if os.path.exists(downloads_dir) and not os.path.isabs(args.folder):
        target_dir = os.path.join(downloads_dir, args.folder)
    else:
        target_dir = os.path.abspath(args.folder)

    print(f"Scraping roster from: {args.url}...")
    players = scrape_roster(args.url)
    print(f"Found {len(players)} players on roster.\n")

    # Load mapping if provided
    mapping = {}
    if args.mapping:
        if os.path.exists(args.mapping):
            with open(args.mapping, "r") as f:
                mapping = json.load(f)
        else:
            try:
                mapping = json.loads(args.mapping)
            except Exception:
                pass

    print("-" * 65)
    print(f"{'#':<4} | {'Player Name':<26} | {'Assigned Number / File':<24}")
    print("-" * 65)

    os.makedirs(target_dir, exist_ok=True)

    for idx, p in enumerate(players, 1):
        name = p["name"]
        jersey = p.get("jersey", "")

        # Lookup assigned number by name or jersey
        assigned_number = mapping.get(name) or mapping.get(jersey) or mapping.get(f"#{jersey}")

        if not assigned_number:
            # If not assigned, use the player name as filename
            clean_name = re.sub(r'[\\/*?:"<>|]', '', name).strip()
            assigned_number = clean_name

        out_file = os.path.join(target_dir, f"{assigned_number}.png")
        print(f"#{jersey:<3} | {name:<26} | Downloading -> {assigned_number}.png...", end="", flush=True)

        try:
            saved_path, final_size = download_and_resize(p["image"], out_file, target_width=800)
            print(f" ✅ ({final_size[0]}x{final_size[1]})")
        except Exception as e:
            print(f" ❌ Failed: {e}")

    print("\n" + "=" * 65)
    print(f"🎉 Downloaded and standardized {len(players)} photos (width 800) into:")
    print(f"📁 {target_dir}")
    print("=" * 65)


if __name__ == "__main__":
    main()
