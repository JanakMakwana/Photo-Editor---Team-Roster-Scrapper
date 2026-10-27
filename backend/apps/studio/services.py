import os
import sys
import io
import time
import gc
import re
import shutil
import threading
from PIL import Image
import rembg
from pathlib import Path

WORKSPACE_DIR = str(Path(__file__).resolve().parents[3])

# Concurrency limiter to protect low-resource environments from memory spikes
AI_LOCK = threading.Semaphore(1)
DETECTOR = None
REMBG_SESSION = None
FACE_CACHE = {}


def get_services():
    global DETECTOR, REMBG_SESSION
    if DETECTOR is None:
        try:
            from process_portraits import FaceDetectorWrapper
            print("[Django Studio] Initializing Face Detector...")
            DETECTOR = FaceDetectorWrapper()
        except Exception as e:
            print(f"[Django Studio Warning] Face detector wrapper init error: {e}")
            DETECTOR = None

    if REMBG_SESSION is None:
        model_name = os.environ.get("REMBG_MODEL", "u2netp" if os.environ.get("RENDER") else "u2net")
        print(f"[Django Studio] Initializing Rembg Engine ({model_name})...")
        REMBG_SESSION = rembg.new_session(model_name)

    return DETECTOR, REMBG_SESSION


def compute_auto_framing(image_path: str = None, image_bytes: bytes = None, cache_key: str = None):
    """Calculates optimal default framing using FaceDetector, supporting disk files or in-memory bytes."""
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
    box = None
    if detector:
        try:
            box = detector.detect_face(orig)
        except Exception as e:
            print(f"[AutoAlign] Face detector failed: {e}")

    if not box:
        # Fallback to upper third center
        fw = int(w_orig * 0.45)
        fh = int(h_orig * 0.40)
        fx = int((w_orig - fw) / 2)
        fy = int(h_orig * 0.15)
        box = (fx, fy, fw, fh)

    fx, fy, fw, fh = box

    # Standard sports bust clearances: upper eye level 35%, chin clearance 85%
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


def remove_background_bytes(image_bytes: bytes) -> bytes:
    """Removes background and returns RGBA PNG bytes."""
    _, session = get_services()
    with AI_LOCK:
        output_bytes = rembg.remove(image_bytes, session=session)
    return output_bytes


def process_custom_framed_portrait(
    image_path: str = None,
    image_bytes: bytes = None,
    scale: float = 0.35,
    offset_x: float = 0,
    offset_y: float = 0,
    output_size: int = 180,
) -> Image.Image:
    """Crops the framed region, runs rembg, and fits to 180x180 RGBA canvas."""
    _, rembg_session = get_services()
    if image_bytes:
        orig = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    elif image_path and os.path.exists(image_path):
        orig = Image.open(image_path).convert("RGB")
    else:
        raise ValueError("Valid image_path or image_bytes required")

    w_orig, h_orig = orig.size
    scale_factor = scale * (output_size / 180.0)
    x1 = -offset_x / scale_factor
    y1 = -offset_y / scale_factor
    x2 = x1 + (output_size / scale_factor)
    y2 = y1 + (output_size / scale_factor)

    crop_box = (int(max(0, x1)), int(max(0, y1)), int(min(w_orig, x2)), int(min(h_orig, y2)))
    cropped = orig.crop(crop_box)

    with AI_LOCK:
        cutout = rembg.remove(cropped, session=rembg_session)

    # Scale cutout and composite onto canvas
    cut_w = int(cropped.width * scale_factor)
    cut_h = int(cropped.height * scale_factor)
    if cut_w > 0 and cut_h > 0:
        cutout_resized = cutout.resize((cut_w, cut_h), Image.Resampling.LANCZOS)
    else:
        cutout_resized = cutout

    canvas = Image.new("RGBA", (output_size, output_size), (0, 0, 0, 0))
    paste_x = int(offset_x + (crop_box[0] * scale_factor))
    paste_y = int(offset_y + (crop_box[1] * scale_factor))
    canvas.paste(cutout_resized, (paste_x, paste_y), cutout_resized)
    return canvas


def resolve_input_path(raw_path: str) -> str:
    """Intelligently resolves a user-provided folder path or name."""
    if not raw_path:
        return None

    cleaned = raw_path.strip().strip("'\"")
    expanded = os.path.expanduser(os.path.expandvars(cleaned))
    if os.path.isdir(expanded):
        return os.path.abspath(expanded)

    downloads_dir = os.path.expanduser("~/Downloads")
    workspace_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
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

    search_dirs = [downloads_dir, parent_dir, os.path.expanduser("~/Desktop")]
    norm_target = re.sub(r'[\s_\-]+', '', cleaned.lower().replace("copy", ""))

    for sdir in search_dirs:
        if os.path.exists(sdir):
            try:
                for item in os.listdir(sdir):
                    if item.startswith(".") or item.endswith("_edited"):
                        continue
                    full = os.path.join(sdir, item)
                    if os.path.isdir(full):
                        norm_item = re.sub(r'[\s_\-]+', '', item.lower().replace("copy", ""))
                        if norm_item == norm_target or norm_target in norm_item or norm_item in norm_target:
                            return os.path.abspath(full)
            except Exception:
                pass
    return None


def resolve_edited_dir(folder_path: str, create: bool = False) -> str:
    abs_path = os.path.abspath(folder_path)
    parent = os.path.dirname(abs_path)
    base = os.path.basename(abs_path)
    out_dir = os.path.join(parent, f"{base}_edited")
    if create:
        os.makedirs(out_dir, exist_ok=True)
    return out_dir


def detect_downloads_folders():
    """Detects folders containing athlete photos in Downloads and workspace."""
    results = []
    seen_paths = set()

    downloads_dir = os.path.expanduser("~/Downloads")
    workspace_dir = WORKSPACE_DIR
    input_photos_dir = os.path.join(workspace_dir, "input_photos")

    search_dirs = [downloads_dir, input_photos_dir, workspace_dir]

    for sdir in search_dirs:
        if not os.path.exists(sdir) or not os.path.isdir(sdir):
            continue
        try:
            for item in os.listdir(sdir):
                if item.startswith(".") or item.endswith("_edited") or item in ("venv", ".venv", "node_modules", "frontend", "backend", ".git"):
                    continue
                full_path = os.path.join(sdir, item)
                if os.path.isdir(full_path) and full_path not in seen_paths:
                    image_count = 0
                    try:
                        for f in os.listdir(full_path):
                            if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                                image_count += 1
                    except Exception:
                        pass
                    if image_count > 0:
                        seen_paths.add(full_path)
                        results.append({
                            "name": item,
                            "path": full_path,
                            "count": image_count,
                            "edited": resolve_edited_dir(full_path)
                        })
        except Exception:
            pass

    return sorted(results, key=lambda x: x["count"], reverse=True)[:15]


def clean_server_storage(max_age_minutes: int = 15) -> dict:
    workspace_dir = WORKSPACE_DIR
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
        try:
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
        except Exception:
            pass

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
