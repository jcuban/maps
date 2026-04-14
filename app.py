#!/usr/bin/env python3
"""Blank Map Labeler — upload a blank map, enter place names, download labeled result."""

import base64
import io
import json
import time

from flask import Flask, jsonify, render_template, request
from geopy.exc import GeocoderServiceError, GeocoderTimedOut
from geopy.geocoders import Nominatim
from PIL import Image, ImageDraw, ImageFont

app = Flask(__name__)

# ── Geocoding ──────────────────────────────────────────────────────────────────

def _geocode_one(geolocator, name: str) -> dict:
    try:
        loc = geolocator.geocode(name, timeout=10)
        if loc:
            return {"lat": loc.latitude, "lon": loc.longitude, "found": True}
        return {"found": False}
    except GeocoderTimedOut:
        return {"found": False, "error": "Timed out"}
    except GeocoderServiceError as exc:
        return {"found": False, "error": str(exc)}


# ── Image labeling ─────────────────────────────────────────────────────────────

_FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "C:/Windows/Fonts/arialbd.ttf",
]


def _load_font(size: int):
    for path in _FONT_PATHS:
        try:
            return ImageFont.truetype(path, size)
        except (IOError, OSError):
            pass
    return ImageFont.load_default()


def _hex_rgba(hex_color: str, alpha: int = 255) -> tuple:
    h = hex_color.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), alpha)


def _draw_labels(img_bytes: bytes, bounds: dict, places: dict, opts: dict) -> io.BytesIO:
    img = Image.open(io.BytesIO(img_bytes)).convert("RGBA")
    w, h = img.size

    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    min_lat = bounds["min_lat"]
    max_lat = bounds["max_lat"]
    min_lon = bounds["min_lon"]
    max_lon = bounds["max_lon"]

    font_size = max(8, int(opts.get("font_size", 14)))
    dot_size  = max(2, int(opts.get("dot_size",  5)))
    dot_rgba  = _hex_rgba(opts.get("dot_color",  "#dc3232"))
    txt_rgba  = _hex_rgba(opts.get("text_color", "#000000"))
    dot_edge  = tuple(max(0, c - 55) for c in dot_rgba[:3]) + (255,)

    font = _load_font(font_size)
    labeled, skipped = 0, []

    for name, data in places.items():
        if not data.get("found"):
            skipped.append(name)
            continue

        lat, lon = data["lat"], data["lon"]
        x = int((lon - min_lon) / (max_lon - min_lon) * w)
        y = int((max_lat - lat) / (max_lat - min_lat) * h)

        if not (0 <= x <= w and 0 <= y <= h):
            skipped.append(f"{name} (outside bounds)")
            continue

        # Dot
        draw.ellipse(
            [x - dot_size, y - dot_size, x + dot_size, y + dot_size],
            fill=dot_rgba,
            outline=dot_edge,
        )

        # Label — white halo then main color
        tx, ty = x + dot_size + 3, y - font_size // 2
        halo = (255, 255, 255, 210)
        for dx, dy in [(-1,-1),(1,-1),(-1,1),(1,1),(0,-1),(0,1),(-1,0),(1,0)]:
            draw.text((tx + dx, ty + dy), name, font=font, fill=halo)
        draw.text((tx, ty), name, font=font, fill=txt_rgba)
        labeled += 1

    result = Image.alpha_composite(img, overlay).convert("RGB")
    out = io.BytesIO()
    result.save(out, format="PNG")
    out.seek(0)
    return out, labeled, skipped


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/geocode", methods=["POST"])
def geocode():
    data   = request.get_json(force=True)
    names  = [p.strip() for p in data.get("places", []) if p.strip()]
    geo    = Nominatim(user_agent="blank_map_labeler_v1")
    result = {}
    for i, name in enumerate(names):
        result[name] = _geocode_one(geo, name)
        if i < len(names) - 1:
            time.sleep(1.1)          # Nominatim: 1 req/s
    return jsonify(result)


@app.route("/label", methods=["POST"])
def label():
    map_file = request.files.get("map")
    if not map_file:
        return jsonify({"error": "No map file"}), 400

    bounds = json.loads(request.form["bounds"])
    places = json.loads(request.form["places"])
    opts   = json.loads(request.form.get("options", "{}"))

    out, labeled, skipped = _draw_labels(map_file.read(), bounds, places, opts)
    img_b64 = "data:image/png;base64," + base64.b64encode(out.getvalue()).decode()

    return jsonify({"image": img_b64, "labeled": labeled, "skipped": skipped})


if __name__ == "__main__":
    print("Map Labeler running at http://localhost:5000")
    app.run(debug=True, port=5000)
