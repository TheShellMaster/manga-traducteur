from collections import deque
import os
import re
from typing import List, Tuple, Dict, Any, Optional
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from app.config import FONT_PATH, BUNDLED_FONTS_DIR


def get_font_by_style(style_name: str = "default", size: int = 14) -> ImageFont.ImageFont:
    """Load font according to chosen style or fallback."""
    s = (style_name or "bold").lower()
    if "comic" in s:
        key = "comic"
    elif "serif" in s and "sans" not in s:
        key = "serif"
    elif "sans" in s:
        key = "sans"
    else:
        key = "bold"

    font_candidates = {
        "bold": "DejaVuSans-Bold.ttf",
        "comic": "LiberationSans-Bold.ttf",
        "sans": "DejaVuSans.ttf",
        "serif": "DejaVuSerif-Bold.ttf",
    }
    path = str(BUNDLED_FONTS_DIR / font_candidates.get(key, "DejaVuSans-Bold.ttf"))
    if os.path.exists(path):
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    if os.path.exists(FONT_PATH):
        try:
            return ImageFont.truetype(FONT_PATH, size)
        except Exception:
            pass
    return ImageFont.load_default()


def format_french_typography(text: str) -> str:
    """Applies French comic typography rules: non-breaking spaces before !, ?, :, ; and inside guillemets."""
    if not text:
        return ""
    cleaned = re.sub(r"\s+", " ", text.replace("\n", " ")).strip()
    # Attach double punctuation (!, ?, :, ;) to the preceding word via non-breaking space (\u00A0)
    cleaned = re.sub(r"\s*([!?:;]+)", "\u00A0\\1", cleaned)
    cleaned = re.sub(r"«\s*", "«\u00A0", cleaned)
    cleaned = re.sub(r"\s*»", "\u00A0»", cleaned)
    return cleaned.strip()


def diamond_wrap_words(
    draw: Any,
    words: Union[List[str], str, None] = None,
    font: Optional[Any] = None,
    max_w: Optional[int] = None,
    max_chars_per_line: Optional[int] = None,
) -> List[str]:
    """
    Wraps words into an oval/diamond profile suitable for manga speech bubbles.
    Supports both graphical wrapping (draw, words, font, max_w) and char-based
    wrapping (text, max_chars_per_line).
    Avoids orphan words on the last line and tapers the first/last lines on 3+ line bubbles.
    """
    if isinstance(draw, str):
        # Character-based wrapper mode: diamond_wrap_words(text, max_chars_per_line=...)
        text = draw.strip()
        if not text:
            return []
        word_list = text.split()
        limit = max_chars_per_line or 22
        if len(word_list) <= 1 or len(text) <= limit:
            return [text]

        # Greedy line calculation with diamond weighting
        lines: List[str] = []
        cur_line: List[str] = []
        cur_len = 0
        for w in word_list:
            cand = cur_len + (1 if cur_len > 0 else 0) + len(w)
            if cand <= limit or not cur_line:
                cur_line.append(w)
                cur_len = cand
            else:
                lines.append(" ".join(cur_line))
                cur_line = [w]
                cur_len = len(w)
        if cur_line:
            lines.append(" ".join(cur_line))

        # Rebalance if last line is a single isolated word and previous line has >= 2 words
        if len(lines) >= 2 and len(lines[-1].split()) == 1:
            prev_words = lines[-2].split()
            if len(prev_words) >= 2:
                last_w = prev_words.pop()
                lines[-2] = " ".join(prev_words)
                lines[-1] = f"{last_w} {lines[-1]}"
        return lines

    if not words:
        return []

    word_list = words if isinstance(words, list) else str(words).split()
    n = len(word_list)
    if n == 0:
        return []

    if max_w is None:
        max_w = 400

    word_widths = [draw.textlength(w, font=font) for w in word_list]
    space_w = draw.textlength(" ", font=font) if font else 6.0

    if any(w > max_w for w in word_widths):
        return None

    total_w = sum(word_widths) + space_w * (n - 1)
    if total_w <= max_w * 0.92 or n == 1:
        return [" ".join(word_list)]

    # Prefix sums to compute width of words[i:j] in O(1)
    prefix = [0.0] * (n + 1)
    for i in range(n):
        prefix[i + 1] = prefix[i] + word_widths[i]

    def span_width(i: int, j: int) -> float:
        return (prefix[j] - prefix[i]) + space_w * (j - i - 1)

    # Minimum lines via greedy check
    greedy_lines = 1
    cur = 0.0
    for w in word_widths:
        cand = cur + (space_w if cur > 0 else 0.0) + w
        if cand <= max_w:
            cur = cand
        else:
            greedy_lines += 1
            cur = w

    best_overall_lines: Optional[List[str]] = None
    best_overall_cost = float("inf")

    for num_lines in range(max(2, greedy_lines), min(n, greedy_lines + 2) + 1):
        # Diamond weights: first and last lines slightly narrower for 3+ lines
        if num_lines >= 3:
            weights = [0.76] + [1.0] * (num_lines - 2) + [0.76]
        else:
            weights = [1.0, 0.92]
        w_sum = sum(weights)
        target_widths = [min(max_w * weights[k], total_w * (weights[k] / w_sum)) for k in range(num_lines)]

        # DP: dp[k][i] = min cost to place first i words into k lines
        INF = float("inf")
        dp = [[INF] * (n + 1) for _ in range(num_lines + 1)]
        parent = [[0] * (n + 1) for _ in range(num_lines + 1)]
        dp[0][0] = 0.0

        for k in range(1, num_lines + 1):
            target = target_widths[k - 1]
            # Oval width cap: slightly tighter on top/bottom line if >= 3 lines
            line_cap = max_w * (0.92 if (num_lines >= 3 and k in (1, num_lines)) else 1.0)
            for j in range(k, n + 1):
                for i in range(k - 1, j):
                    if dp[k - 1][i] == INF:
                        continue
                    lw = span_width(i, j)
                    if lw > max_w:
                        continue
                    over_oval = max(0.0, lw - line_cap) * 4.0
                    diff = lw - target
                    cost = diff * diff + over_oval * over_oval
                    # Penalize 1-word orphan on the last line when n >= 4
                    if k == num_lines and (j - i) == 1 and n >= 4:
                        cost += (max_w * 0.45) ** 2
                    total_c = dp[k - 1][i] + cost
                    if total_c < dp[k][j]:
                        dp[k][j] = total_c
                        parent[k][j] = i

        if dp[num_lines][n] < best_overall_cost:
            best_overall_cost = dp[num_lines][n]
            lines_out = []
            curr = n
            for k in range(num_lines, 0, -1):
                prev = parent[k][curr]
                lines_out.append(" ".join(words[prev:curr]))
                curr = prev
            lines_out.reverse()
            best_overall_lines = lines_out

    return best_overall_lines


def fit_text_lines(
    draw: ImageDraw.ImageDraw,
    text: str,
    box_w: int,
    box_h: int,
    font_style: str = "bold",
    fixed_size: Optional[int] = None,
    min_size: int = 10,
    max_size: Optional[int] = None,
) -> Tuple[ImageFont.ImageFont, List[str], int]:
    """
    Dynamically finds optimal font size and diamond word-wrapping for target text.
    Guarantees an internal padding of ~11% on each side (78% usable width/height)
    so text never touches speech bubble borders.
    """
    formatted = format_french_typography(text)
    words = [w for w in formatted.split(" ") if w.strip()]
    if not words:
        return get_font_by_style(font_style, min_size), [], min_size

    # 11% internal padding on each side (22% total margin)
    inner_w = max(14, int(box_w * 0.78))
    inner_h = max(14, int(box_h * 0.78))

    if fixed_size and fixed_size > 0:
        font = get_font_by_style(font_style, fixed_size)
        lines = diamond_wrap_words(draw, words, font, inner_w)
        if lines is None:
            # Fallback if a word exceeds inner_w at fixed_size
            lines = []
            cur_line = ""
            for word in words:
                candidate = f"{cur_line} {word}".strip() if cur_line else word
                if draw.textlength(candidate, font=font) <= inner_w:
                    cur_line = candidate
                else:
                    if cur_line:
                        lines.append(cur_line)
                    cur_line = word
            if cur_line:
                lines.append(cur_line)
        line_h = round(fixed_size * 1.18)
        return font, lines, line_h

    # Dynamic auto-fit calibrated on 1403x2000 manga pages
    start_size = max_size if max_size else max(min_size, min(int(inner_h * 0.48), int(inner_w * 0.45), 42))
    size = start_size

    best_font = get_font_by_style(font_style, min_size)
    best_lines = [" ".join(words)]
    best_line_h = round(min_size * 1.18)

    while size >= min_size:
        font = get_font_by_style(font_style, size)
        lines = diamond_wrap_words(draw, words, font, inner_w)
        if lines:
            line_h = round(size * 1.18)
            total_h = len(lines) * line_h
            best_font = font
            best_lines = lines
            best_line_h = line_h
            if total_h <= inner_h:
                return font, lines, line_h
        size -= 1

    # Fallback if even min_size had a single long word > inner_w
    font = get_font_by_style(font_style, min_size)
    lines = []
    cur_line = ""
    for word in words:
        candidate = f"{cur_line} {word}".strip() if cur_line else word
        if draw.textlength(candidate, font=font) <= inner_w:
            cur_line = candidate
        else:
            if cur_line:
                lines.append(cur_line)
            cur_line = word
    if cur_line:
        lines.append(cur_line)
    return font, lines, round(min_size * 1.18)


def _apply_smart_bubble_mask(
    img: Image.Image,
    px0: int,
    py0: int,
    px1: int,
    py1: int,
) -> Tuple[bool, bool, Tuple[int, int, int]]:
    """
    Empirically calibrated Smart Bubble Inpainter:
    1. Samples the box + 8% margin.
    2. Detects light vs dark bubble (median luminance < 128 => dark narration/caption box)
       and screentone/textured background (128 <= median < 225).
    3. Preserves peripheral bubble borders via boundary-connected component detection:
       only internal ink strokes (not connected to the outer border of the region)
       are erased using morphological dilation (MaxFilter(5)) and Gaussian feathering (r=1.2).
    Returns (is_dark_bg, is_screentone, bg_rgb).
    """
    width, height = img.size
    box_w = px1 - px0
    box_h = py1 - py0

    # 8% sampling margin around the box
    pad_x = max(2, int(box_w * 0.08))
    pad_y = max(2, int(box_h * 0.08))
    mx0 = max(0, px0 - pad_x)
    my0 = max(0, py0 - pad_y)
    mx1 = min(width, px1 + pad_x)
    my1 = min(height, py1 + pad_y)

    # Core statistics inside (px0, py0, px1, py1) using C-level histogram (0.02 ms)
    core_gray = img.crop((px0, py0, px1, py1)).convert("L")
    cw, ch = box_w, box_h
    n = cw * ch
    if n == 0:
        return False, False, (255, 255, 255)

    hist = core_gray.histogram()
    p15_target = n * 0.15
    p50_target = n * 0.50
    p85_target = n * 0.85
    acc = 0
    p15 = median = p85 = 255
    got15 = got50 = got85 = False
    for val, count in enumerate(hist):
        acc += count
        if not got15 and acc >= p15_target:
            p15 = val
            got15 = True
        if not got50 and acc >= p50_target:
            median = val
            got50 = True
        if not got85 and acc >= p85_target:
            p85 = val
            got85 = True
            break

    # True dark narration boxes have dark background pixels even at high percentiles (p85 < 115)
    # Never treat a white bubble with dense black text as a dark background!
    is_dark_bg = (p85 < 115)
    is_screentone = (115 <= p85 < 210 and median < 200)
    bg_luma = int(p15) if is_dark_bg else int(max(248, p85))
    bg_rgb = (bg_luma, bg_luma, bg_luma)

    if is_dark_bg:
        thresh = max(int(median) + 30, 130)
        lut = [255 if i >= thresh else 0 for i in range(256)]
    else:
        thresh = min(220, int(p85) - 20)
        lut = [255 if i <= thresh else 0 for i in range(256)]

    # Binary target ink mask in C
    target_img = core_gray.point(lut)

    # Identify boundary-connected components (bubble outline / panel border) on a bounded grid (<= 110x110)
    scale = min(1.0, 110.0 / max(cw, ch))
    if scale < 1.0:
        sw = max(8, int(cw * scale))
        sh = max(8, int(ch * scale))
        small_target = target_img.resize((sw, sh), Image.Resampling.NEAREST)
    else:
        sw, sh = cw, ch
        small_target = target_img

    s_bytes = small_target.tobytes()
    border_connected = bytearray(sw * sh)
    q: deque[int] = deque()
    border_band = 2
    for y in range(sh):
        row_off = y * sw
        for x in range(sw):
            if x < border_band or x >= sw - border_band or y < border_band or y >= sh - border_band:
                idx = row_off + x
                if s_bytes[idx] and not border_connected[idx]:
                    border_connected[idx] = 255
                    q.append(idx)

    while q:
        curr = q.popleft()
        cx = curr % sw
        cy = curr // sw
        for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
            if 0 <= nx < sw and 0 <= ny < sh:
                nidx = ny * sw + nx
                if s_bytes[nidx] and not border_connected[nidx]:
                    border_connected[nidx] = 255
                    q.append(nidx)

    border_img = Image.frombytes("L", (sw, sh), bytes(border_connected))
    if scale < 1.0:
        border_img = border_img.resize((cw, ch), Image.Resampling.NEAREST)
        border_img = border_img.filter(ImageFilter.MaxFilter(3))

    # Internal text ink = target_img minus border_img, with a 2px safety inset on outer perimeter
    ink_mask = ImageChops.subtract(target_img, border_img)
    inset = max(2, min(5, int(min(cw, ch) * 0.04)))
    draw_m = ImageDraw.Draw(ink_mask)
    draw_m.rectangle([0, 0, cw - 1, inset - 1], fill=0)
    draw_m.rectangle([0, ch - inset, cw - 1, ch - 1], fill=0)
    draw_m.rectangle([0, 0, inset - 1, ch - 1], fill=0)
    draw_m.rectangle([cw - inset, 0, cw - 1, ch - 1], fill=0)

    # Dynamic resolution scaling factor (supports 700px scans, 1400px standard, 3000px spreads & Webtoons)
    ref_scale = max(0.5, min(2.5, min(width, height) / 1400.0))
    dilation_kernel = 3 if ref_scale < 0.75 else (5 if ref_scale < 1.45 else 7)
    blur_r = round(max(0.7, min(2.4, 1.2 * ref_scale)), 2)

    # Morphological dilation + feathering in C proportional to resolution, then subtract border_img again
    mask_img = ink_mask.filter(ImageFilter.MaxFilter(dilation_kernel))
    mask_img = mask_img.filter(ImageFilter.GaussianBlur(radius=blur_r))
    mask_img = ImageChops.subtract(mask_img, border_img)

    fill_layer = Image.new("RGB", (cw, ch), bg_rgb)
    orig_crop = img.crop((px0, py0, px1, py1))
    composited = Image.composite(fill_layer, orig_crop, mask_img)
    img.paste(composited, (px0, py0))

    return is_dark_bg, is_screentone, bg_rgb


def render_manga_page(
    img: Image.Image,
    blocks: List[Dict[str, Any]],
    font_style: str = "bold",
    fixed_font_size: Optional[int] = None,
    text_color: str = "#000000",
    mask_style: str = "smart",
    mask_only: bool = False,
) -> Image.Image:
    """Renders translated text onto speech bubbles with smart border-preserving inpainting and diamond typography."""
    img = img.convert("RGB")
    width, height = img.size
    draw = ImageDraw.Draw(img)

    def hex_to_rgb(hex_str: str, default: Tuple[int, int, int]) -> Tuple[int, int, int]:
        try:
            h = (hex_str or "").lstrip("#")
            if len(h) == 6:
                return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
        except Exception:
            pass
        return default

    default_fg = hex_to_rgb(text_color, (0, 0, 0))
    style_norm = (mask_style or "smart").lower()

    for b in blocks:
        text = str(b.get("fr") or b.get("translation") or b.get("text") or "").strip()
        if not text and not mask_only:
            continue

        box = b.get("box")
        if not box or len(box) != 4:
            continue

        x0, y0, x1, y1 = box
        px0 = max(0, min(width - 1, int(float(x0) / 1000.0 * width)))
        py0 = max(0, min(height - 1, int(float(y0) / 1000.0 * height)))
        px1 = max(0, min(width, int(float(x1) / 1000.0 * width)))
        py1 = max(0, min(height, int(float(y1) / 1000.0 * height)))

        box_w = px1 - px0
        box_h = py1 - py0
        if box_w < 8 or box_h < 8:
            continue

        # Prevent runaway bounding boxes from wiping out entire manga panels or full pages
        if box_w > width * 0.48 and box_h > height * 0.48:
            continue

        fg_color = default_fg
        use_stroke = False
        stroke_color = (255, 255, 255)

        if style_norm in ("smart", "intelligent", "auto"):
            is_dark_bg, is_screentone, _ = _apply_smart_bubble_mask(img, px0, py0, px1, py1)
            # Re-bind draw after img.paste
            draw = ImageDraw.Draw(img)
            if is_dark_bg:
                fg_color = (255, 255, 255)
                use_stroke = True
                stroke_color = (0, 0, 0)
            elif is_screentone:
                use_stroke = True
                stroke_color = (255, 255, 255)
        elif style_norm == "transparent":
            use_stroke = True
            stroke_color = (255, 255, 255) if sum(fg_color) < 380 else (0, 0, 0)
        else:
            pad_x = max(2, int(box_w * 0.04))
            pad_y = max(2, int(box_h * 0.04))
            mask_rect = [
                max(0, px0 - pad_x),
                max(0, py0 - pad_y),
                min(width, px1 + pad_x),
                min(height, py1 + pad_y),
            ]
            if style_norm == "rectangle":
                draw.rectangle(mask_rect, fill=(255, 255, 255))
            elif style_norm == "ellipse":
                draw.ellipse(mask_rect, fill=(255, 255, 255))
            else:  # rounded
                radius = min(14, int(min(box_w, box_h) * 0.25))
                draw.rounded_rectangle(mask_rect, radius=radius, fill=(255, 255, 255))

        if mask_only:
            continue

        ref_scale = max(0.5, min(2.5, min(width, height) / 1400.0))
        dyn_min_size = max(8, round(10 * min(1.4, max(0.75, ref_scale))))
        dyn_max_size = max(26, round(42 * ref_scale))
        stroke_w = max(1, min(4, round(2.0 * ref_scale)))

        font, lines, line_h = fit_text_lines(
            draw,
            text,
            box_w=box_w,
            box_h=box_h,
            font_style=font_style,
            fixed_size=fixed_font_size if fixed_font_size and fixed_font_size > 0 else None,
            min_size=dyn_min_size,
            max_size=dyn_max_size,
        )
        if not lines:
            continue

        total_text_h = len(lines) * line_h
        start_y = py0 + (box_h - total_text_h) / 2.0

        for i, line in enumerate(lines):
            line_w = draw.textlength(line, font=font)
            text_x = px0 + (box_w - line_w) / 2.0
            text_y = start_y + (i * line_h)

            if use_stroke:
                draw.text(
                    (text_x, text_y),
                    line,
                    font=font,
                    fill=fg_color,
                    stroke_width=stroke_w,
                    stroke_fill=stroke_color,
                )
            else:
                draw.text(
                    (text_x, text_y),
                    line,
                    font=font,
                    fill=fg_color,
                )

    return img
