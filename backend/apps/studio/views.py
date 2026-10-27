import os
import io
import json
import base64
import zipfile
from PIL import Image
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from .services import (
    compute_auto_framing,
    remove_background_bytes,
    process_custom_framed_portrait,
    detect_downloads_folders,
    clean_server_storage,
    resolve_input_path,
    resolve_edited_dir,
)


@csrf_exempt
def api_health(request):
    return HttpResponse("OK", content_type="text/plain")


@csrf_exempt
@require_http_methods(["GET", "POST"])
def api_auto_align(request):
    data = {}
    if request.method == "POST":
        try:
            data = json.loads(request.body or "{}")
        except Exception:
            data = {}
    else:
        data = request.GET.dict()

    b64_data = data.get("image_base64", "")
    photo_url = data.get("url", "")
    img_bytes = None

    if b64_data:
        if "," in b64_data:
            b64_data = b64_data.split(",", 1)[1]
        img_bytes = base64.b64decode(b64_data)
    elif photo_url:
        try:
            import urllib.request
            req = urllib.request.Request(photo_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=12) as resp:
                img_bytes = resp.read()
        except Exception as e:
            print(f"[AutoAlign] Failed to fetch photo_url: {e}")

    if img_bytes:
        try:
            result = compute_auto_framing(image_bytes=img_bytes)
            return JsonResponse(result)
        except Exception as e:
            return JsonResponse({"status": "error", "message": str(e)}, status=500)

    raw_folder = data.get("folder", ".")
    folder = resolve_input_path(raw_folder) or raw_folder
    name = data.get("name", data.get("photo", ""))
    img_path = os.path.join(folder, name)

    if os.path.exists(img_path) and os.path.isfile(img_path):
        try:
            result = compute_auto_framing(image_path=img_path)
            return JsonResponse(result)
        except Exception as e:
            return JsonResponse({"status": "error", "message": str(e)}, status=500)

    return JsonResponse({"status": "error", "message": "Photo not found or invalid input."}, status=404)


@csrf_exempt
@require_http_methods(["POST"])
def api_cutout(request):
    try:
        data = json.loads(request.body or "{}")
    except Exception:
        data = {}

    b64_data = data.get("image_base64", "")
    if not b64_data:
        return JsonResponse({"status": "error", "message": "Missing image_base64 parameter."}, status=400)

    if "," in b64_data:
        b64_data = b64_data.split(",", 1)[1]

    img_bytes = base64.b64decode(b64_data)
    try:
        out_bytes = remove_background_bytes(img_bytes)
        b64_out = "data:image/png;base64," + base64.b64encode(out_bytes).decode("utf-8")
        return JsonResponse({"status": "ok", "image_base64": b64_out})
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)


@csrf_exempt
@require_http_methods(["GET"])
def api_suggested_folders(request):
    suggestions = detect_downloads_folders()
    return JsonResponse({"suggestions_data": suggestions})


@csrf_exempt
@require_http_methods(["POST"])
def api_open_folder(request):
    try:
        data = json.loads(request.body or "{}")
    except Exception:
        data = {}

    folder_path = data.get("path", "")
    resolved = resolve_input_path(folder_path)
    if not resolved or not os.path.isdir(resolved):
        return JsonResponse({"status": "error", "message": f"Folder not found: {folder_path}"}, status=404)

    edited_dir = resolve_edited_dir(resolved, create=True)
    edited_files = set()
    if os.path.exists(edited_dir):
        for f in os.listdir(edited_dir):
            if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                edited_files.add(f.lower())

    photos = []
    for f in sorted(os.listdir(resolved)):
        if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp")) and not f.startswith("."):
            full_path = os.path.join(resolved, f)
            try:
                with Image.open(full_path) as im:
                    w, h = im.size
                is_saved = (f.lower() in edited_files or (os.path.splitext(f)[0].lower() + ".png") in edited_files)
                photos.append({
                    "name": f,
                    "path": full_path,
                    "width": w,
                    "height": h,
                    "is_saved": is_saved
                })
            except Exception:
                pass

    return JsonResponse({
        "status": "ok",
        "folder": resolved,
        "edited_folder": edited_dir,
        "photos": photos,
        "count": len(photos)
    })


@csrf_exempt
@require_http_methods(["POST"])
def api_save_photo(request):
    try:
        data = json.loads(request.body or "{}")
    except Exception:
        data = {}

    folder = data.get("folder", "")
    name = data.get("name", "")
    b64_data = data.get("image_base64", "")

    if not b64_data or not folder or not name:
        return JsonResponse({"status": "error", "message": "Missing folder, name, or image_base64 parameter."}, status=400)

    resolved_folder = resolve_input_path(folder) or folder
    edited_dir = resolve_edited_dir(resolved_folder, create=True)

    clean_name = os.path.splitext(os.path.basename(name))[0] + ".png"
    out_path = os.path.join(edited_dir, clean_name)

    if "," in b64_data:
        b64_data = b64_data.split(",", 1)[1]
    img_bytes = base64.b64decode(b64_data)

    with open(out_path, "wb") as f:
        f.write(img_bytes)

    return JsonResponse({
        "status": "ok",
        "saved_path": out_path,
        "name": clean_name
    })


@csrf_exempt
@require_http_methods(["POST"])
def api_batch_process(request):
    try:
        data = json.loads(request.body or "{}")
    except Exception:
        data = {}

    folder = data.get("folder", "")
    resolved = resolve_input_path(folder) or folder
    if not os.path.isdir(resolved):
        return JsonResponse({"status": "error", "message": "Folder not found."}, status=404)

    edited_dir = resolve_edited_dir(resolved, create=True)
    images = [f for f in sorted(os.listdir(resolved)) if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp")) and not f.startswith(".")]

    processed = []
    for img_name in images:
        inp = os.path.join(resolved, img_name)
        out_name = os.path.splitext(img_name)[0] + ".png"
        out_path = os.path.join(edited_dir, out_name)
        try:
            framing = compute_auto_framing(image_path=inp)
            canvas = process_custom_framed_portrait(
                image_path=inp,
                scale=framing["scale"],
                offset_x=framing["offset_x"],
                offset_y=framing["offset_y"],
                output_size=180
            )
            canvas.save(out_path, "PNG")
            processed.append(out_name)
        except Exception as e:
            print(f"[Batch] Failed to process {img_name}: {e}")

    return JsonResponse({
        "status": "ok",
        "processed_count": len(processed),
        "total_count": len(images),
        "edited_folder": edited_dir
    })


@csrf_exempt
@require_http_methods(["POST", "GET"])
def api_download_edited_zip(request):
    data = {}
    if request.method == "POST":
        try:
            data = json.loads(request.body or "{}")
        except Exception:
            data = {}
    else:
        data = request.GET.dict()

    folder = data.get("folder", "")
    resolved = resolve_input_path(folder) or folder
    edited_dir = resolve_edited_dir(resolved)

    if not os.path.isdir(edited_dir):
        return JsonResponse({"status": "error", "message": "No edited photos found for this folder."}, status=404)

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in os.listdir(edited_dir):
            if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                fp = os.path.join(edited_dir, f)
                zf.write(fp, f)

    zip_bytes = zip_buf.getvalue()
    folder_name = os.path.basename(resolved) or "photos"
    response = HttpResponse(zip_bytes, content_type="application/zip")
    response["Content-Disposition"] = f'attachment; filename="{folder_name}_edited.zip"'
    response["Content-Length"] = str(len(zip_bytes))
    return response


@csrf_exempt
@require_http_methods(["POST"])
def api_clear_server_storage(request):
    res = clean_server_storage(max_age_minutes=0)
    return JsonResponse(res)
