#!/usr/bin/env python3
"""Punchy card renderer — overlay punches + text on a blank scene card face."""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "out"
SCENES_DIR = ROOT / "scenes"
MANIFEST_PATH = SCENES_DIR / "manifest.json"

EMOJI_FONT_PATH = Path("/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf")
SANS_FONT_CANDIDATES = [
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    Path("/usr/share/fonts/truetype/sand-box/google/Noto Sans/NotoSans-VariableFont_wdth,wght.ttf"),
]
SANS_BOLD_CANDIDATES = [
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
]

# Soft card-face ink colors (readable on cream)
INK = (45, 38, 32, 255)
INK_MUTED = (90, 78, 68, 255)
HOLE_RING = (55, 48, 40, 220)
HOLE_CORE = (18, 14, 12, 255)
HOLE_CORE_LIGHT = (35, 28, 24, 255)
HOLE_HIGHLIGHT = (70, 60, 50, 90)


def _load_font(candidates: list[Path], size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in candidates:
        if path.is_file():
            try:
                return ImageFont.truetype(str(path), size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def load_sans(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    return _load_font(SANS_BOLD_CANDIDATES if bold else SANS_FONT_CANDIDATES, size)


def load_emoji(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont | None:
    if not EMOJI_FONT_PATH.is_file():
        return None
    # NotoColorEmoji is CBDT/CBLC; Pillow needs size that matches glyph bitmap slots.
    # Common working sizes: 109, 136 — try requested, then fall back.
    for attempt in (size, 109, 136, 64, 32):
        try:
            return ImageFont.truetype(str(EMOJI_FONT_PATH), size=attempt)
        except OSError:
            continue
    return None


def parse_roi(roi: dict[str, float] | list[float] | tuple[float, ...]) -> tuple[float, float, float, float]:
    if isinstance(roi, dict):
        return float(roi["x"]), float(roi["y"]), float(roi["w"]), float(roi["h"])
    if len(roi) != 4:
        raise ValueError("ROI must be {x,y,w,h} or [x,y,w,h]")
    return float(roi[0]), float(roi[1]), float(roi[2]), float(roi[3])


def load_manifest_roi(scene_id: str) -> tuple[Path, tuple[float, float, float, float]]:
    if not MANIFEST_PATH.is_file():
        raise FileNotFoundError(f"Missing scenes manifest: {MANIFEST_PATH}")
    data = json.loads(MANIFEST_PATH.read_text())
    for scene in data.get("scenes", []):
        if scene.get("id") == scene_id:
            path = SCENES_DIR / scene["filename"]
            return path, parse_roi(scene["card_roi"])
    raise KeyError(f"Unknown scene_id: {scene_id}")


def _ragged_disk(
    draw: ImageDraw.ImageDraw,
    cx: float,
    cy: float,
    r: float,
    fill: tuple[int, int, int, int],
    seed: int,
) -> None:
    """Filled punch core with slight irregular perimeter (physical hole look)."""
    rng = random.Random(seed)
    points: list[tuple[float, float]] = []
    n = 28
    for i in range(n):
        ang = (2 * math.pi * i) / n
        jitter = 1.0 + rng.uniform(-0.08, 0.08)
        rr = r * jitter
        points.append((cx + rr * math.cos(ang), cy + rr * math.sin(ang)))
    draw.polygon(points, fill=fill)


def draw_hole(
    overlay: Image.Image,
    cx: int,
    cy: int,
    radius: int,
    punched: bool,
    hole_index: int,
) -> None:
    draw = ImageDraw.Draw(overlay, "RGBA")
    # Outer ring (always) — empty punch-guide circle
    ring_w = max(2, radius // 8)
    bbox = [cx - radius, cy - radius, cx + radius, cy + radius]
    draw.ellipse(bbox, outline=HOLE_RING, width=ring_w)

    if not punched:
        # Soft inner shadow hint for unpunched
        inset = radius - ring_w - 1
        if inset > 2:
            ib = [cx - inset, cy - inset, cx + inset, cy + inset]
            draw.ellipse(ib, outline=(120, 110, 95, 40), width=1)
        return

    # Punched: dark torn core slightly smaller than ring
    core_r = int(radius * 0.92)
    _ragged_disk(draw, cx, cy, core_r, HOLE_CORE, seed=hole_index * 9973 + 17)
    # Inner irregular lighter flecks near edge
    rng = random.Random(hole_index * 13 + 5)
    for _ in range(4):
        ang = rng.uniform(0, 2 * math.pi)
        d = core_r * rng.uniform(0.55, 0.85)
        fx = cx + d * math.cos(ang)
        fy = cy + d * math.sin(ang)
        fr = max(1, int(radius * 0.08))
        draw.ellipse([fx - fr, fy - fr, fx + fr, fy + fr], fill=HOLE_CORE_LIGHT)
    # Tiny highlight arc (top-left) for depth
    hl_r = int(core_r * 0.75)
    draw.arc(
        [cx - hl_r, cy - hl_r, cx + hl_r, cy + hl_r],
        start=200,
        end=280,
        fill=HOLE_HIGHLIGHT,
        width=max(1, radius // 10),
    )


def _fit_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
) -> str:
    """Simple word-wrap to max_width; returns multiline string."""
    words = text.split()
    if not words:
        return ""
    lines: list[str] = []
    cur = words[0]
    for w in words[1:]:
        trial = f"{cur} {w}"
        if draw.textlength(trial, font=font) <= max_width:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    return "\n".join(lines)


def _paste_emoji(
    base: Image.Image,
    emoji: str,
    xy: tuple[int, int],
    target_px: int,
) -> int:
    """Draw emoji; returns width used. Falls back to text glyph if color font fails."""
    if not emoji:
        return 0
    font = load_emoji(target_px)
    # Render on temp RGBA then paste — color emoji often needs embedded_color
    tmp = Image.new("RGBA", (target_px * 3, target_px * 3), (0, 0, 0, 0))
    tdraw = ImageDraw.Draw(tmp)
    if font is not None:
        try:
            tdraw.text((target_px, target_px), emoji, font=font, embedded_color=True)
            bbox = tmp.getbbox()
            if bbox:
                cropped = tmp.crop(bbox)
                # Scale to target height
                h = cropped.height
                if h > 0 and h != target_px:
                    scale = target_px / h
                    cropped = cropped.resize(
                        (max(1, int(cropped.width * scale)), target_px),
                        Image.Resampling.LANCZOS,
                    )
                base.paste(cropped, xy, cropped)
                return cropped.width
        except Exception:
            pass
    # Fallback: draw as plain text with sans (may be tofu for emoji)
    sans = load_sans(max(12, target_px // 2))
    draw = ImageDraw.Draw(base)
    draw.text(xy, emoji, font=sans, fill=INK)
    return int(draw.textlength(emoji, font=sans))


def render_card(
    scene_path: Path | str,
    card_roi: dict[str, float] | list[float] | tuple[float, ...],
    *,
    holes: int,
    punched: int,
    emoji: str,
    person: str,
    goal: str,
    direction: str = "up",
    out_path: Path | str | None = None,
) -> Path:
    """
    Composite punches + labels onto a blank scene image.

    card_roi: normalized {x,y,w,h} fractions of image (0-1) for blank card face.
    holes: 1-7; punched: 0..holes; direction: up|down (label only in v1).
    """
    if not (1 <= holes <= 7):
        raise ValueError("holes must be 1..7")
    if not (0 <= punched <= holes):
        raise ValueError("punched must be 0..holes")
    direction = direction.lower().strip()
    if direction not in ("up", "down"):
        raise ValueError("direction must be 'up' or 'down'")

    scene_path = Path(scene_path)
    img = Image.open(scene_path).convert("RGBA")
    W, H = img.size
    rx, ry, rw, rh = parse_roi(card_roi)
    # Card face pixel box
    left = int(rx * W)
    top = int(ry * H)
    right = int((rx + rw) * W)
    bottom = int((ry + rh) * H)
    card_w = max(1, right - left)
    card_h = max(1, bottom - top)

    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))

    # Layout inside card face (margins ~6% of card)
    mx = int(card_w * 0.06)
    my = int(card_h * 0.07)
    content_left = left + mx
    content_right = right - mx
    content_top = top + my
    content_w = content_right - content_left

    # Hole row: single horizontal row in lower ~38% of card
    hole_cy = top + int(card_h * 0.68)
    max_holes = 7
    # Radius scales with card width and hole count so 7 still fits
    gap_budget = content_w * 0.92
    spacing = gap_budget / max(holes, 1)
    radius = int(min(spacing * 0.32, card_h * 0.12, card_w * 0.055))
    radius = max(8, radius)
    total_span = spacing * (holes - 1) if holes > 1 else 0
    start_x = content_left + (content_w - total_span) / 2

    for i in range(holes):
        cx = int(start_x + i * spacing) if holes > 1 else int(content_left + content_w / 2)
        draw_hole(overlay, cx, hole_cy, radius, punched=i < punched, hole_index=i)

    img = Image.alpha_composite(img, overlay)
    draw = ImageDraw.Draw(img)

    # Text band above holes — keep clear of hole tops
    hole_top = hole_cy - radius - int(card_h * 0.04)
    text_bottom = hole_top
    text_top = content_top

    # Person name (bold) + emoji to the left — glanceable fridge/partner face
    name_size = max(16, int(card_h * 0.13))
    goal_size = max(12, int(card_h * 0.085))
    name_font = load_sans(name_size, bold=True)
    goal_font = load_sans(goal_size, bold=False)

    emoji_px = max(18, int(name_size * 1.25))
    emoji_w = 0
    if emoji:
        emoji_w = _paste_emoji(img, emoji, (content_left, text_top), emoji_px)
        emoji_w += int(card_w * 0.02)

    name_x = content_left + emoji_w
    name_max_w = content_right - name_x
    # Shrink name if needed
    while name_size > 10 and draw.textlength(person, font=name_font) > name_max_w:
        name_size -= 1
        name_font = load_sans(name_size, bold=True)

    draw.text((name_x, text_top), person, font=name_font, fill=INK)
    name_bbox = draw.textbbox((name_x, text_top), person, font=name_font)
    name_bottom = name_bbox[3]

    # Direction hint + goal
    dir_label = "Punch up" if direction == "up" else "Punch down"
    meta = f"{dir_label} · {punched}/{holes}"
    meta_font = load_sans(max(9, goal_size - 2), bold=False)
    meta_y = name_bottom + int(card_h * 0.02)
    draw.text((content_left, meta_y), meta, font=meta_font, fill=INK_MUTED)
    meta_bbox = draw.textbbox((content_left, meta_y), meta, font=meta_font)

    goal_y = meta_bbox[3] + int(card_h * 0.025)
    wrapped = _fit_text(draw, goal, goal_font, content_w)
    # Ensure goal doesn't spill into holes
    goal_bbox = draw.multiline_textbbox((content_left, goal_y), wrapped, font=goal_font, spacing=4)
    if goal_bbox[3] > text_bottom:
        # Shrink goal font
        for gs in range(goal_size, 8, -1):
            goal_font = load_sans(gs, bold=False)
            wrapped = _fit_text(draw, goal, goal_font, content_w)
            goal_bbox = draw.multiline_textbbox(
                (content_left, goal_y), wrapped, font=goal_font, spacing=4
            )
            if goal_bbox[3] <= text_bottom:
                break
        # If still overflowing, truncate lines
        if goal_bbox[3] > text_bottom:
            lines = wrapped.split("\n")
            while lines and True:
                trial = "\n".join(lines)
                goal_bbox = draw.multiline_textbbox(
                    (content_left, goal_y), trial, font=goal_font, spacing=4
                )
                if goal_bbox[3] <= text_bottom or len(lines) <= 1:
                    wrapped = trial if goal_bbox[3] <= text_bottom else (lines[0][:40] + "…")
                    break
                lines.pop()

    draw.multiline_text(
        (content_left, goal_y), wrapped, font=goal_font, fill=INK, spacing=4
    )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if out_path is None:
        safe_person = "".join(c if c.isalnum() or c in "-_" else "_" for c in person)[:32]
        out_path = OUT_DIR / f"card_{safe_person}_{punched}of{holes}.png"
    else:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

    # Save as RGB PNG (drop alpha for chat-friendly output)
    rgb = Image.new("RGB", img.size, (255, 255, 255))
    rgb.paste(img, mask=img.split()[3])
    rgb.save(out_path, "PNG")
    return out_path


def synthesize_blank_scene(
    out_path: Path,
    width: int = 1000,
    height: int = 700,
) -> tuple[Path, dict[str, float]]:
    """
    Synthesize a wooden-table photo with a cream card in frame (no downloads).
    Returns path and card_roi fractions.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    img = Image.new("RGB", (width, height))
    px = img.load()
    rng = random.Random(42)

    # Wood grain background
    for y in range(height):
        for x in range(width):
            base = 118 + int(18 * math.sin(y / 27.0) + 10 * math.sin(x / 90.0))
            grain = int(8 * math.sin((x + y * 0.15) / 11.0))
            noise = rng.randint(-6, 6)
            r = max(0, min(255, base + grain + noise + 25))
            g = max(0, min(255, base + grain + noise - 5))
            b = max(0, min(255, base + grain + noise - 35))
            px[x, y] = (r, g, b)

    draw = ImageDraw.Draw(img, "RGBA")

    # Soft vignette
    vignette = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    vd = ImageDraw.Draw(vignette)
    for i in range(40):
        alpha = int(3 + i * 1.2)
        vd.rectangle([i, i, width - 1 - i, height - 1 - i], outline=(40, 25, 10, alpha))
    img = Image.alpha_composite(img.convert("RGBA"), vignette).convert("RGB")
    draw = ImageDraw.Draw(img)

    # Card placement — centered cream rectangle with soft shadow
    card_w, card_h = 800, 500
    cx0 = (width - card_w) // 2
    cy0 = (height - card_h) // 2 - 10

    # Shadow
    shadow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.rounded_rectangle(
        [cx0 + 8, cy0 + 12, cx0 + card_w + 8, cy0 + card_h + 12],
        radius=14,
        fill=(30, 20, 10, 90),
    )
    img = Image.alpha_composite(img.convert("RGBA"), shadow).convert("RGB")
    draw = ImageDraw.Draw(img)

    cream = (245, 236, 214)
    cream_edge = (228, 216, 190)
    draw.rounded_rectangle(
        [cx0, cy0, cx0 + card_w, cy0 + card_h],
        radius=12,
        fill=cream,
        outline=cream_edge,
        width=2,
    )
    # Subtle paper texture
    rng2 = random.Random(7)
    for _ in range(1200):
        x = rng2.randint(cx0 + 4, cx0 + card_w - 4)
        y = rng2.randint(cy0 + 4, cy0 + card_h - 4)
        n = rng2.randint(-6, 6)
        c = (
            max(0, min(255, cream[0] + n)),
            max(0, min(255, cream[1] + n)),
            max(0, min(255, cream[2] + n)),
        )
        draw.point((x, y), fill=c)

    img.save(out_path, "PNG")
    roi = {
        "x": cx0 / width,
        "y": cy0 / height,
        "w": card_w / width,
        "h": card_h / height,
    }
    return out_path, roi


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Render a Punchy weekly punchcard onto a scene.")
    p.add_argument("--scene", type=str, help="Path to blank scene PNG/JPEG")
    p.add_argument("--scene-id", type=str, help="Scene id from scenes/manifest.json")
    p.add_argument("--roi", type=str, help='JSON ROI {"x":..,"y":..,"w":..,"h":..} or x,y,w,h')
    p.add_argument("--holes", type=int, required=True)
    p.add_argument("--punched", type=int, required=True)
    p.add_argument("--emoji", type=str, default="")
    p.add_argument("--person", type=str, required=True)
    p.add_argument("--goal", type=str, required=True)
    p.add_argument("--direction", type=str, default="up", choices=["up", "down"])
    p.add_argument("--out", type=str, default=None, help="Output PNG path")
    p.add_argument(
        "--synthesize-blank",
        action="store_true",
        help="Write synthetic wooden-table blank to --scene path and use its ROI",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_argparser().parse_args(argv)

    if args.synthesize_blank:
        if not args.scene:
            args.scene = str(SCENES_DIR / "synthetic_table.png")
        path, roi = synthesize_blank_scene(Path(args.scene))
        print(f"synthesized blank: {path}", file=sys.stderr)
        print(f"card_roi: {json.dumps(roi)}", file=sys.stderr)
        scene_path = path
        card_roi: Any = roi
    elif args.scene_id:
        scene_path, card_roi = load_manifest_roi(args.scene_id)
    elif args.scene:
        scene_path = Path(args.scene)
        if not args.roi:
            print("--roi required when using --scene without --synthesize-blank", file=sys.stderr)
            return 2
        raw = args.roi.strip()
        if raw.startswith("{"):
            card_roi = json.loads(raw)
        else:
            parts = [float(x) for x in raw.split(",")]
            card_roi = {"x": parts[0], "y": parts[1], "w": parts[2], "h": parts[3]}
    else:
        print("Provide --scene, --scene-id, or --synthesize-blank", file=sys.stderr)
        return 2

    # Allow --roi to override manifest / synthesized
    if args.roi and not args.synthesize_blank:
        raw = args.roi.strip()
        if raw.startswith("{"):
            card_roi = json.loads(raw)
        else:
            parts = [float(x) for x in raw.split(",")]
            card_roi = {"x": parts[0], "y": parts[1], "w": parts[2], "h": parts[3]}

    out = render_card(
        scene_path,
        card_roi,
        holes=args.holes,
        punched=args.punched,
        emoji=args.emoji,
        person=args.person,
        goal=args.goal,
        direction=args.direction,
        out_path=args.out,
    )
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
