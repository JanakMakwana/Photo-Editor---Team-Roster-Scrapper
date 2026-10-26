"""
Studio Workbench API Router:
Handles image uploads, auto-framing calculations, background removal, and file exporting.
"""

import os
import io
import re
import json
import base64
import zipfile
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, Request, HTTPException, Response, UploadFile, File
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
import studio
from PIL import Image

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

router = APIRouter(prefix="/api", tags=["Studio Workbench"])


class PreviewCutoutRequest(BaseModel):
    image_base64: Optional[str] = None
    url: Optional[str] = None
    folder: Optional[str] = "."
    photo: Optional[str] = ""
    scale: Optional[float] = 0.35
    offset_x: Optional[float] = 0.0
    offset_y: Optional[float] = 0.0


class SaveRefinedRequest(BaseModel):
    folder: Optional[str] = "."
    filename: Optional[str] = "headshot.png"
    image_base64: str


@router.get("/proxy_photo")
async def proxy_photo(url: str, width: Optional[int] = 800):
    if not url:
        raise HTTPException(status_code=400, detail="Missing url parameter.")
    try:
        png_bytes, _ = studio.download_player_portrait_bytes(url, target_width=width or 800)
        return Response(
            content=png_bytes,
            media_type="image/png",
            headers={
                "Cache-Control": "public, max-age=86400",
                "Access-Control-Allow-Origin": "*"
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Proxy error: {str(e)}")


@router.get("/auto_align")
async def auto_align(folder: Optional[str] = ".", name: Optional[str] = ""):
    resolved = studio.resolve_input_path(folder) or folder
    img_path = os.path.join(resolved, name)
    if not os.path.exists(img_path):
        raise HTTPException(status_code=404, detail="Photo not found on server.")

    with studio.AI_LOCK:
        data = studio.compute_auto_framing(img_path)
    return data


@router.get("/photo_raw")
async def photo_raw(folder: Optional[str] = ".", name: Optional[str] = ""):
    resolved = studio.resolve_input_path(folder) or folder
    img_path = os.path.join(resolved, name)
    if not os.path.exists(img_path) or not os.path.isfile(img_path):
        raise HTTPException(status_code=404, detail="Photo not found.")

    ext = os.path.splitext(name)[1].lower()
    mime = "image/png"
    if ext in [".jpg", ".jpeg"]:
        mime = "image/jpeg"
    elif ext == ".webp":
        mime = "image/webp"

    with open(img_path, "rb") as f:
        data = f.read()

    return Response(content=data, media_type=mime)


@router.post("/upload_single_file")
async def upload_single_file(
    request: Request,
    folder: Optional[str] = "Selected_Photos",
    name: Optional[str] = "photo.png"
):
    clean_folder = re.sub(r'[^a-zA-Z0-9_\-\s]', '', os.path.basename(folder)).strip() or "Selected_Photos"
    clean_filename = os.path.basename(name)
    target_dir = os.path.join(ROOT_DIR, "input_photos", clean_folder)
    os.makedirs(target_dir, exist_ok=True)

    target_path = os.path.join(target_dir, clean_filename)
    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="Empty upload body.")

    with open(target_path, "wb") as f:
        f.write(body)

    return {
        "status": "ok",
        "filename": clean_filename,
        "folder": clean_folder,
        "size_bytes": len(body),
        "target_path": target_path
    }


@router.get("/suggested_folders")
async def suggested_folders():
    downloads_dir = os.path.expanduser("~/Downloads")
    search_dirs = [
        os.path.join(ROOT_DIR, "input_photos"),
        ROOT_DIR,
        downloads_dir,
    ]
    suggestions = []
    seen = set()

    for base_dir in search_dirs:
        if not os.path.exists(base_dir):
            continue
        try:
            for item in os.listdir(base_dir):
                if item.startswith(".") or item in ("models", "backend", "frontend", ".venv", "__pycache__"):
                    continue
                full_path = os.path.join(base_dir, item)
                if os.path.isdir(full_path):
                    imgs = studio.find_input_images(full_path)
                    if imgs and full_path not in seen:
                        seen.add(full_path)
                        suggestions.append({
                            "name": os.path.basename(full_path),
                            "full_path": full_path,
                            "photo_count": len(imgs)
                        })
        except Exception:
            pass

    return {"status": "ok", "folders": suggestions}


@router.get("/list_folder_photos")
async def list_folder_photos(folder: Optional[str] = "."):
    resolved = studio.resolve_input_path(folder) or folder
    if not os.path.exists(resolved) or not os.path.isdir(resolved):
        raise HTTPException(status_code=404, detail="Folder not found.")

    photos = studio.find_input_images(resolved)
    return {
        "folder": resolved,
        "photos": photos,
        "count": len(photos)
    }


@router.post("/preview_cutout")
async def preview_cutout(req: PreviewCutoutRequest):
    img_bytes = None
    if req.image_base64:
        b64 = req.image_base64.split(",", 1)[1] if "," in req.image_base64 else req.image_base64
        img_bytes = base64.b64decode(b64)
    elif req.url:
        try:
            img_bytes, _ = studio.download_player_portrait_bytes(req.url, target_width=800)
        except Exception:
            pass

    if img_bytes:
        with studio.AI_LOCK:
            canvas = studio.process_custom_framed_portrait(
                image_bytes=img_bytes,
                scale=req.scale or 0.35,
                offset_x=req.offset_x or 0.0,
                offset_y=req.offset_y or 0.0,
                output_size=180
            )
        buf = io.BytesIO()
        canvas.save(buf, "PNG")
        return Response(content=buf.getvalue(), media_type="image/png")

    resolved = studio.resolve_input_path(req.folder) or req.folder
    img_path = os.path.join(resolved, req.photo)
    if not os.path.exists(img_path):
        raise HTTPException(status_code=404, detail="Photo not found.")

    with studio.AI_LOCK:
        canvas = studio.process_custom_framed_portrait(
            image_path=img_path,
            scale=req.scale or 0.35,
            offset_x=req.offset_x or 0.0,
            offset_y=req.offset_y or 0.0,
            output_size=180
        )
    buf = io.BytesIO()
    canvas.save(buf, "PNG")
    return Response(content=buf.getvalue(), media_type="image/png")


@router.get("/export_folder_zip")
async def export_folder_zip(folder: str):
    resolved = studio.resolve_input_path(folder) or folder
    if not os.path.exists(resolved) or not os.path.isdir(resolved):
        raise HTTPException(status_code=404, detail="Folder not found.")

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(resolved):
            for file in files:
                if file.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                    fp = os.path.join(root, file)
                    arc = os.path.relpath(fp, resolved)
                    zf.write(fp, arc)

    zip_bytes = zip_buf.getvalue()
    fname = os.path.basename(resolved) or "export"
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{fname}.zip"'}
    )


@router.post("/purge_storage")
async def purge_storage():
    res = studio.clean_server_storage(max_age_minutes=0)
    return {"status": "ok", "cleaned": res}
