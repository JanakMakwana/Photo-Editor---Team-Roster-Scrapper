"""
Sports Roster Ingestion, URL Scraping, and Player Search API Router.
"""

from typing import Optional, Dict, Any, List
from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import io
import re
import zipfile
import studio

router = APIRouter(prefix="/api", tags=["Roster & Athletes"])


class FetchRosterRequest(BaseModel):
    url: Optional[str] = ""
    player_name: Optional[str] = ""
    team_name: Optional[str] = ""


class DownloadRosterZipRequest(BaseModel):
    folder_name: Optional[str] = "Downloaded_Roster"
    players: List[Dict[str, Any]] = []
    target_width: Optional[int] = 800


@router.post("/fetch_roster")
async def fetch_roster(req: FetchRosterRequest):
    url = (req.url or "").strip()
    player_name = (req.player_name or "").strip()
    team_name = (req.team_name or "").strip()

    if not url and not player_name:
        raise HTTPException(status_code=400, detail="Missing url or player_name parameter.")

    try:
        result = studio.scrape_roster_data(url, player_name=player_name, team_name=team_name)
        return {
            "status": "ok",
            "suggested_folder": result.get("suggested_folder", "Roster"),
            "players": result.get("players", []),
            "options": result.get("options", []),
            "photo_options": result.get("photo_options", []),
            "is_single_player": result.get("is_single_player", False),
            "is_target_match": result.get("is_target_match", False),
            "target_team": result.get("target_team", "")
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to scrape roster data: {str(e)}")


@router.get("/search_player")
async def search_player(name: str, team: Optional[str] = None):
    p_name = name.strip()
    if not p_name:
        raise HTTPException(status_code=400, detail="Missing name parameter.")

    try:
        data = studio.search_sports_player_or_team(p_name, target_team_override=team.strip() if team else "")
        return {
            "status": "ok",
            "name": p_name,
            "target_team": team or "",
            "suggested_folder": data.get("suggested_folder", f"Player - {p_name}"),
            "is_single_player": data.get("is_single_player", True),
            "is_target_match": data.get("is_target_match", False),
            "players": data.get("players", []),
            "options": data.get("options", []),
            "photo_options": data.get("photo_options", [])
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")


@router.post("/download_roster_zip")
async def download_roster_zip(req: DownloadRosterZipRequest):
    folder_name = re.sub(r'[^a-zA-Z0-9_\-\s]', '', req.folder_name).strip() or "Downloaded_Roster"
    target_width = int(req.target_width or 800)

    zip_buf = io.BytesIO()
    seen_filenames = set()

    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for item in req.players:
            p_name = item.get("name", "").strip()
            assigned = item.get("assigned_number", "").strip()
            img_url = item.get("image", "").strip()
            if not img_url:
                continue

            clean_name = re.sub(r'[\\/*?:"<>|]', '', p_name).strip()
            if assigned:
                clean_assigned = re.sub(r'[\\/*?:"<>|]', '', assigned).strip()
                out_filename = f"{clean_assigned}.png"
            else:
                out_filename = f"{clean_name}.png"

            # Prevent duplicate collision
            base = out_filename[:-4]
            counter = 2
            while out_filename in seen_filenames:
                out_filename = f"{base}_{counter}.png"
                counter += 1
            seen_filenames.add(out_filename)

            try:
                png_bytes, _ = studio.download_player_portrait_bytes(img_url, target_width=target_width)
                zf.writestr(out_filename, png_bytes)
            except Exception as e:
                print(f"[Roster ZIP] Skipped {p_name} ({e})")

    zip_bytes = zip_buf.getvalue()
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{folder_name}.zip"'}
    )
