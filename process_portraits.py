#!/usr/bin/env python3
"""
VeloRoster AI — Automated Athletic Portrait Processing Engine
Developed from scratch with full proprietary rights owned by Ecstaticloud Technologies.
Standardizes athletic player photographs into 180x180 transparent headshots
with customizable canvas fit, padding, and positioning.
"""

import os
import sys
import argparse
import glob
import urllib.request
from pathlib import Path
from PIL import Image

# Auto-re-execute with local .venv python if running under system python
script_dir = os.path.dirname(os.path.abspath(__file__))
venv_python = os.path.join(script_dir, ".venv", "bin", "python3")
if not os.environ.get("RENDER") and sys.prefix == sys.base_prefix and os.path.exists(venv_python) and sys.executable != venv_python:
    os.execv(venv_python, [venv_python] + sys.argv)

# Note: Heavy libraries (cv2, numpy, rembg, mediapipe) are imported lazily inside
# classes/functions to keep cold startup memory < 50MB on 512MB RAM cloud instances.

MODEL_URL = "https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/latest/blaze_face_short_range.tflite"
MODEL_PATH = os.path.join(script_dir, "models", "blaze_face_short_range.tflite")


def ensure_face_detector_model():
    """Ensure the blaze_face TFLite model is available locally."""
    if os.path.exists(MODEL_PATH):
        return MODEL_PATH
    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    print(f"Downloading face detector model to {MODEL_PATH}...")
    urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
    return MODEL_PATH


class FaceDetectorWrapper:
    """Unified face detector supporting both MediaPipe solutions and tasks."""
    def __init__(self):
        self.backend = None
        self.detector = None
        
        # Try legacy mediapipe solutions API
        try:
            import mediapipe as mp
            if hasattr(mp, "solutions") and hasattr(mp.solutions, "face_detection"):
                self.mp_face = mp.solutions.face_detection
                self.detector = self.mp_face.FaceDetection(model_selection=1, min_detection_confidence=0.4)
                self.backend = "solutions"
                return
        except Exception:
            pass

        # Try modern mediapipe tasks vision API
        try:
            import mediapipe as mp
            from mediapipe.tasks import python
            from mediapipe.tasks.python import vision
            
            model_file = ensure_face_detector_model()
            base_options = python.BaseOptions(model_asset_path=model_file)
            options = vision.FaceDetectorOptions(base_options=base_options, min_detection_confidence=0.35)
            self.detector = vision.FaceDetector.create_from_options(options)
            self.mp = mp
            self.backend = "tasks"
            return
        except Exception as e:
            print(f"Warning: MediaPipe Tasks initialization error: {e}")

        # Fallback to OpenCV Haar Cascade
        import cv2
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        self.detector = cv2.CascadeClassifier(cascade_path)
        self.backend = "opencv"

    def detect_face(self, pil_image):
        """
        Detects primary face in PIL Image.
        Returns: (x, y, w, h) bounding box coordinates in pixels, or None.
        """
        import numpy as np
        w_img, h_img = pil_image.size
        
        if self.backend == "solutions":
            rgb_arr = np.array(pil_image.convert("RGB"))
            results = self.detector.process(rgb_arr)
            if results and results.detections:
                bb = results.detections[0].location_data.relative_bounding_box
                return (
                    int(bb.xmin * w_img),
                    int(bb.ymin * h_img),
                    int(bb.width * w_img),
                    int(bb.height * h_img),
                )
        elif self.backend == "tasks":
            rgb_arr = np.array(pil_image.convert("RGB"))
            mp_img = self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=rgb_arr)
            results = self.detector.detect(mp_img)
            if results and results.detections:
                bb = results.detections[0].bounding_box
                return (bb.origin_x, bb.origin_y, bb.width, bb.height)
        elif self.backend == "opencv":
            import cv2
            gray = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2GRAY)
            faces = self.detector.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(100, 100))
            if len(faces) > 0:
                x, y, w, h = faces[0]
                return (int(x), int(y), int(w), int(h))

        # Default fallback: center top bust framing
        return (int(w_img * 0.30), int(h_img * 0.18), int(w_img * 0.40), int(h_img * 0.32))


def process_portrait(
    image_path: str,
    output_path: str,
    detector: FaceDetectorWrapper,
    rembg_session,
    canvas_fill: float = 0.92,
    top_pad: float = 0.50,
    bottom_pad: float = 0.60,
    side_pad: float = 0.35,
    alignment: str = "bottom",
    output_size: int = 180,
):
    """
    Processes a single portrait:
    1. Loads photo
    2. Detects face coordinates with MediaPipe
    3. Removes background with rembg
    4. Computes custom padded bounding box
    5. Scales and positions onto a 180x180 transparent canvas
    """
    orig_img = Image.open(image_path).convert("RGB")
    w_img, h_img = orig_img.size

    # 1. Face detection
    face_box = detector.detect_face(orig_img)
    fx, fy, fw, fh = face_box

    # 2. Background removal
    import rembg
    no_bg = rembg.remove(orig_img, session=rembg_session)

    # 3. Apply custom sports framing paddings
    pad_top = int(fh * top_pad)
    pad_bottom = int(fh * bottom_pad)
    pad_side = int(fw * side_pad)

    ymin = max(0, fy - pad_top)
    ymax = min(h_img, fy + fh + pad_bottom)
    xmin = max(0, fx - pad_side)
    xmax = min(w_img, fx + fw + pad_side)

    # Crop bust
    crop = no_bg.crop((xmin, ymin, xmax, ymax))
    cw, ch = crop.size
    if cw <= 0 or ch <= 0:
        crop = no_bg
        cw, ch = crop.size

    # 4. Fit into output canvas according to chosen canvas_fill
    target_dim = max(1, int(round(output_size * canvas_fill)))
    scale = target_dim / max(cw, ch)
    nw = max(1, int(round(cw * scale)))
    nh = max(1, int(round(ch * scale)))

    scaled_crop = crop.resize((nw, nh), Image.Resampling.LANCZOS)

    # 5. Place on transparent canvas
    canvas = Image.new("RGBA", (output_size, output_size), (0, 0, 0, 0))
    pos_x = (output_size - nw) // 2

    if alignment == "bottom":
        pos_y = output_size - nh
    elif alignment == "center":
        pos_y = (output_size - nh) // 2
    elif alignment == "top":
        pos_y = 0
    else:
        pos_y = output_size - nh

    canvas.paste(scaled_crop, (pos_x, pos_y))

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    canvas.save(output_path, "PNG")
    return output_path


def interactive_prompt(args):
    """Interactive CLI menu to choose canvas fit and framing settings."""
    print("=" * 66)
    print(" 🏀 Automated Basketball Portrait Processor (180x180)")
    print("=" * 66)
    print("\nHow much of the photo should fit the 180x180 canvas?")
    print("  1) Standard Sports Framing  [92% fill]  - Balanced headroom & collar (Recommended)")
    print("  2) Full Bleed               [100% fill] - Maximum coverage (touches edge)")
    print("  3) Inset Avatar             [85% fill]  - Optimal for rounded/circle badges")
    print("  4) Close-up Headshot        [110% fill] - Tighter focus on face")
    print("  5) Custom Fill Percentage   [Enter 50% - 150%]")

    try:
        choice = input("\nSelect an option [1-5, default 1]: ").strip()
    except (EOFError, KeyboardInterrupt):
        choice = "1"

    if choice == "2":
        args.fill = 1.00
    elif choice == "3":
        args.fill = 0.85
    elif choice == "4":
        args.fill = 1.10
    elif choice == "5":
        try:
            val = input("Enter fill percentage (e.g. 95 for 95%): ").strip().replace("%", "")
            args.fill = float(val) / 100.0 if float(val) > 1.5 else float(val)
        except ValueError:
            print("Invalid input, defaulting to 92%.")
            args.fill = 0.92
    else:
        args.fill = 0.92

    print(f"-> Canvas Fill selected: {int(args.fill * 100)}%")

    print("\nVertical positioning on 180x180 canvas:")
    print("  1) Bottom-anchored (Bust grounded at bottom, hair clearance on top) [Default]")
    print("  2) Center          (Vertically centered)")
    try:
        align_choice = input("Select alignment [1-2, default 1]: ").strip()
    except (EOFError, KeyboardInterrupt):
        align_choice = "1"

    args.align = "center" if align_choice == "2" else "bottom"
    print(f"-> Alignment selected: {args.align}")


def find_input_images(input_dir: str):
    """Scans for valid image formats in input directory."""
    extensions = ("*.png", "*.jpg", "*.jpeg", "*.webp", "*.PNG", "*.JPG", "*.JPEG", "*.WEBP")
    images = []
    for ext in extensions:
        images.extend(glob.glob(os.path.join(input_dir, ext)))
    # Deduplicate and sort
    return sorted(list(set(images)))


def get_default_output_dir(input_dir: str = None) -> str:
    """Returns path string to the [original_folder]_edited directory without creating it."""
    target = os.path.abspath(input_dir) if input_dir else os.path.dirname(os.path.abspath(__file__))
    folder_name = os.path.basename(target)
    parent_dir = os.path.dirname(target)
    return os.path.join(parent_dir, f"{folder_name}_edited")


def main():
    parser = argparse.ArgumentParser(
        description="Automated Basketball Portrait Processing (180x180 transparent headshots)"
    )
    parser.add_argument(
        "--input", "-i",
        default="input_photos",
        help="Input directory containing photos (default: input_photos/)"
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="Output directory for processed portraits (default: [original_folder]_edited/)"
    )
    parser.add_argument(
        "--fill", "-f",
        type=float,
        default=None,
        help="Canvas fill ratio (e.g. 0.92 or 92 for 92%% fill of 180x180 canvas)"
    )
    parser.add_argument(
        "--align", "-a",
        choices=["bottom", "center", "top"],
        default="bottom",
        help="Vertical alignment on canvas (default: bottom)"
    )
    parser.add_argument(
        "--top-pad",
        type=float,
        default=0.50,
        help="Top padding multiplier relative to face height (default: 0.50 for hair)"
    )
    parser.add_argument(
        "--bottom-pad",
        type=float,
        default=0.60,
        help="Bottom padding multiplier relative to face height (default: 0.60 for neck/collar)"
    )
    parser.add_argument(
        "--side-pad",
        type=float,
        default=0.35,
        help="Side padding multiplier relative to face width (default: 0.35 for ears)"
    )
    parser.add_argument(
        "--yes", "-y", "--non-interactive",
        action="store_true",
        help="Run without interactive prompt using provided flags or defaults"
    )
    parser.add_argument(
        "--ui",
        action="store_true",
        help="Launch the interactive visual Studio UI in your browser"
    )

    args = parser.parse_args()

    # Launch visual Web Studio if requested
    if args.ui:
        import studio
        studio.launch_studio()
        return

    # Check input photos directory
    if not os.path.exists(args.input) or len(find_input_images(args.input)) == 0:
        if os.path.exists("input_photos") and len(find_input_images("input_photos")) > 0:
            args.input = "input_photos"
        elif len(find_input_images(".")) > 0:
            print("Note: 'input_photos/' not found, using images in current directory.")
            args.input = "."
        else:
            print(f"Error: No image files (.png, .jpg, .jpeg, .webp) found in '{args.input}'!")
            sys.exit(1)

    images = find_input_images(args.input)
    if not images:
        print(f"Error: No images found in {args.input}")
        sys.exit(1)

    # Prompt user interactively if fill was not explicitly supplied via CLI and not -y
    if args.fill is None and not args.yes:
        interactive_prompt(args)
    elif args.fill is None:
        args.fill = 0.92
    else:
        # If user passed e.g. 92 instead of 0.92
        if args.fill > 1.5:
            args.fill = args.fill / 100.0

    if args.output is None:
        args.output = get_default_output_dir(args.input)

    print("\n" + "-" * 66)
    print(f"🚀 Starting Batch Processing:")
    print(f" • Input Directory : {args.input} ({len(images)} images found)")
    print(f" • Output Directory: {args.output}")
    print(f" • Canvas Fit      : {int(args.fill * 100)}% of 180x180")
    print(f" • Alignment       : {args.align}")
    print(f" • Padding         : Top={args.top_pad}h | Bottom={args.bottom_pad}h | Sides={args.side_pad}w")
    print("-" * 66)

    # Initialize models once
    import rembg
    print("Initializing MediaPipe Face Detection & Rembg...")
    detector = FaceDetectorWrapper()
    rembg_session = rembg.new_session("u2net")
    print(f"Loaded successfully (Detector Backend: {detector.backend})!\n")

    os.makedirs(args.output, exist_ok=True)

    success_count = 0
    for idx, img_path in enumerate(images, 1):
        filename = os.path.basename(img_path)
        name_no_ext = os.path.splitext(filename)[0]
        out_name = f"{name_no_ext}.png"
        out_path = os.path.join(args.output, out_name)

        print(f"[{idx}/{len(images)}] Processing {filename} -> {out_name}...", end="", flush=True)
        try:
            process_portrait(
                image_path=img_path,
                output_path=out_path,
                detector=detector,
                rembg_session=rembg_session,
                canvas_fill=args.fill,
                top_pad=args.top_pad,
                bottom_pad=args.bottom_pad,
                side_pad=args.side_pad,
                alignment=args.align,
                output_size=180,
            )
            print(" ✅ Done")
            success_count += 1
        except Exception as e:
            print(f" ❌ Failed: {e}")

    print("\n" + "=" * 66)
    print(f"🎉 Batch Processing Complete! Successfully processed: {success_count}/{len(images)}")
    print(f"📁 Output files saved to: {os.path.abspath(args.output)}/")
    print("=" * 66)


if __name__ == "__main__":
    main()
