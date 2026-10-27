import os
import sys
import io
import json
import re
import urllib.request
import zipfile
from PIL import Image
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from pathlib import Path
ROOT_DIR = str(Path(__file__).resolve().parents[3])
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

try:
    from studio import scrape_roster_data, download_player_portrait_bytes
except Exception as e:
    print(f"[Roster View Import Warning] Could not import from studio: {e}")
    scrape_roster_data = None
    download_player_portrait_bytes = None


@csrf_exempt
@require_http_methods(["POST"])
def api_fetch_roster(request):
    try:
        data = json.loads(request.body or "{}")
    except Exception:
        data = {}

    url = (data.get("url") or "").strip()
    player_name = (data.get("player_name") or "").strip()
    team_name = (data.get("team_name") or "").strip()

    if not url and not player_name:
        return JsonResponse({"status": "error", "message": "Missing url or player_name parameter."}, status=400)

    try:
        if scrape_roster_data:
            result = scrape_roster_data(url, player_name=player_name, team_name=team_name)
        else:
            from download_roster import scrape_roster
            players = scrape_roster(url)
            result = {"players": players, "suggested_folder": "Roster", "options": []}

        return JsonResponse({
            "status": "ok",
            "suggested_folder": result.get("suggested_folder", "Roster"),
            "players": result.get("players", []),
            "options": result.get("options", []),
            "photo_options": result.get("photo_options", []),
            "is_single_player": result.get("is_single_player", False),
            "is_target_match": result.get("is_target_match", False),
            "target_team": result.get("target_team", "")
        })
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)


@csrf_exempt
@require_http_methods(["GET"])
def api_proxy_photo(request):
    img_url = request.GET.get("url", "").strip()
    width_param = request.GET.get("width", "800")
    try:
        target_width = int(width_param)
    except Exception:
        target_width = 800

    if not img_url:
        return HttpResponse('{"status":"error","message":"Missing url"}', content_type="application/json", status=400)

    try:
        if download_player_portrait_bytes:
            img_bytes, mime = download_player_portrait_bytes(img_url, target_width=target_width)
        else:
            req = urllib.request.Request(img_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=12) as resp:
                raw = resp.read()
            im = Image.open(io.BytesIO(raw))
            if target_width and im.width > target_width:
                h = int(im.height * (target_width / float(im.width)))
                im = im.resize((target_width, h), Image.Resampling.LANCZOS)
            buf = io.BytesIO()
            im.save(buf, "PNG")
            img_bytes = buf.getvalue()
            mime = "image/png"

        response = HttpResponse(img_bytes, content_type=mime)
        response["Cache-Control"] = "public, max-age=86400"
        return response
    except Exception as e:
        # Fallback to SVG avatar placeholder
        svg = """<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100" viewBox="0 0 24 24" fill="#94a3b8"><path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z"/></svg>"""
        return HttpResponse(svg, content_type="image/svg+xml")


@csrf_exempt
@require_http_methods(["POST"])
def api_download_roster_zip(request):
    try:
        data = json.loads(request.body or "{}")
    except Exception:
        data = {}

    folder_name = (data.get("folder_name") or "Downloaded_Roster").strip()
    clean_folder = re.sub(r'[^a-zA-Z0-9_\-\s]', '', folder_name).strip() or "Downloaded_Roster"
    players = data.get("players", [])
    target_width = int(data.get("target_width", 800))

    zip_buf = io.BytesIO()
    seen = set()

    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for idx, p in enumerate(players, 1):
            p_img = p.get("image") or p.get("raw_image")
            if not p_img:
                continue
            assigned = p.get("assigned_number") or p.get("jersey") or str(idx)
            safe_name = re.sub(r'[\\/*?:"<>|]', '', str(assigned)).strip() or f"athlete_{idx}"
            if safe_name.lower() in seen:
                safe_name = f"{safe_name}_{idx}"
            seen.add(safe_name.lower())

            try:
                if download_player_portrait_bytes:
                    img_bytes, _ = download_player_portrait_bytes(p_img, target_width=target_width)
                else:
                    req = urllib.request.Request(p_img, headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        img_bytes = resp.read()
                zf.writestr(f"{clean_folder}/{safe_name}.png", img_bytes)
            except Exception as e:
                print(f"[Roster ZIP] Failed to download {p.get('name')}: {e}")

    zip_bytes = zip_buf.getvalue()
    response = HttpResponse(zip_bytes, content_type="application/zip")
    response["Content-Disposition"] = f'attachment; filename="{clean_folder}.zip"'
    response["Content-Length"] = str(len(zip_bytes))
    return response
