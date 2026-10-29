import io
import json
import sys
import zipfile
from pathlib import Path
import pytest
from PIL import Image
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.cloud_vision import parse_and_validate_blocks, CloudVisionClient
from app.typesetter import render_manga_page
from app.archives import ArchiveHandler
from server import app, sessions, _run_translation_worker


# =====================================================================
# 1. Tests du Parser JSON (parse_and_validate_blocks)
# =====================================================================

def test_parser_normal_json():
    raw = json.dumps([
        {"box": [100, 150, 200, 120], "original": "こんにちは", "translation": "Bonjour !"}
    ])
    blocks = parse_and_validate_blocks(raw)
    assert len(blocks) == 1
    assert blocks[0]["box"] == (100.0, 150.0, 300.0, 270.0)
    assert blocks[0]["fr"] == "Bonjour !"
    assert blocks[0]["ja"] == "こんにちは"


def test_parser_markdown_fenced():
    raw = """Voici les bulles détectées :
```json
[
  {"box": [50, 60, 180, 90], "ja": "行くぞ", "fr": "On y va !"}
]
```
 Fin de réponse."""
    blocks = parse_and_validate_blocks(raw)
    assert len(blocks) == 1
    assert blocks[0]["box"] == (50.0, 60.0, 230.0, 150.0)
    assert blocks[0]["fr"] == "On y va !"


def test_parser_dict_blocks_wrapper():
    raw = json.dumps({
        "blocks": [
            {"bbox": [200, 300, 150, 100], "text": "Original", "french": "Traduit"}
        ]
    })
    blocks = parse_and_validate_blocks(raw)
    assert len(blocks) == 1
    assert blocks[0]["box"] == (200.0, 300.0, 350.0, 400.0)
    assert blocks[0]["fr"] == "Traduit"


def test_parser_filters_invalid_boxes():
    raw = json.dumps([
        {"box": [10, 10, -5, 50], "ja": "a", "fr": "b"},         # negative width
        {"box": [10, 10, 3, 3], "ja": "a", "fr": "b"},           # too tiny (< 6)
        {"box": [10, 10, 100, 100], "ja": "", "fr": ""},         # empty text
        {"box": [10, 10], "ja": "a", "fr": "b"},                 # malformed box
        "not_a_dict",                                             # non-dict entry
        {"box": [100, 100, 200, 100], "ja": "有効", "fr": "Valide"}
    ])
    blocks = parse_and_validate_blocks(raw)
    assert len(blocks) == 1
    assert blocks[0]["fr"] == "Valide"


# =====================================================================
# 2. Tests du Typesetter (4 masques x 4 polices, auto-fit & fixe)
# =====================================================================

@pytest.mark.parametrize("mask_style", ["rounded", "ellipse", "rectangle", "transparent"])
@pytest.mark.parametrize("font_style", ["bold", "comic", "sans", "serif"])
def test_typesetter_masks_and_fonts(mask_style, font_style):
    img = Image.new("RGB", (600, 900), color=(230, 230, 230))
    blocks = [
        {"box": (100.0, 100.0, 450.0, 280.0), "fr": "Ceci est un test de rendu typographique."},
    ]
    out = render_manga_page(
        img=img,
        blocks=blocks,
        font_style=font_style,
        fixed_font_size=None,
        text_color="#000000",
        mask_style=mask_style,
    )
    assert out.size == (600, 900)
    assert out.mode == "RGB"


def test_typesetter_fixed_vs_autofit():
    img = Image.new("RGB", (500, 700), color=(255, 255, 255))
    blocks = [{"box": (50.0, 50.0, 350.0, 200.0), "fr": "Texte avec taille fixe et auto-fit"}]

    out_auto = render_manga_page(img, blocks, fixed_font_size=0)
    out_fixed = render_manga_page(img, blocks, fixed_font_size=16)

    assert out_auto.size == (500, 700)
    assert out_fixed.size == (500, 700)


# =====================================================================
# 3. Tests du Gestionnaire d'Archives (CBZ, Image seule, Dossier)
# =====================================================================

def test_archive_cbz_roundtrip(tmp_path):
    cbz_in = tmp_path / "chapter.cbz"
    page_names = ["010.jpg", "001.jpg", "002.png"]
    with zipfile.ZipFile(cbz_in, "w", zipfile.ZIP_DEFLATED) as z:
        for idx, name in enumerate(page_names):
            buf = io.BytesIO()
            fmt = "PNG" if name.endswith(".png") else "JPEG"
            Image.new("RGB", (200 + idx * 10, 300), color=(100, 150, 200)).save(buf, format=fmt)
            z.writestr(name, buf.getvalue())
        z.writestr("ComicInfo.xml", b"<ComicInfo><Title>Test</Title></ComicInfo>")

    work_dir = tmp_path / "work"
    work_dir.mkdir()
    fmt, items = ArchiveHandler.extract(cbz_in, work_dir)
    assert fmt == "cbz"
    assert len(items) == 4

    img_items = [it for it in items if it.is_image]
    assert [it.relative_name for it in img_items] == ["001.jpg", "002.png", "010.jpg"]

    rendered = {
        "001.jpg": Image.new("RGB", (210, 300), color=(255, 0, 0)),
    }
    cbz_out = tmp_path / "chapter_fr.cbz"
    ArchiveHandler.pack(fmt, cbz_in, cbz_out, items, rendered)

    assert cbz_out.exists()
    fmt2, items2 = ArchiveHandler.extract(cbz_out, tmp_path / "work2")
    assert fmt2 == "cbz"
    assert len(items2) == 4
    assert [it.relative_name for it in items2 if it.is_image] == ["001.jpg", "002.png", "010.jpg"]


def test_archive_single_image_roundtrip(tmp_path):
    img_in = tmp_path / "page.png"
    Image.new("RGB", (320, 480), color=(10, 20, 30)).save(img_in, format="PNG")

    fmt, items = ArchiveHandler.extract(img_in, tmp_path / "work")
    assert fmt == "image"
    assert len(items) == 1
    assert items[0].is_image is True

    img_out = tmp_path / "page_fr.png"
    rendered = {"page.png": Image.new("RGB", (320, 480), color=(200, 200, 200))}
    ArchiveHandler.pack(fmt, img_in, img_out, items, rendered)
    assert img_out.exists()
    with Image.open(img_out) as loaded:
        assert loaded.size == (320, 480)


def test_archive_folder_roundtrip(tmp_path):
    src_dir = tmp_path / "raw_chapter"
    src_dir.mkdir()
    Image.new("RGB", (150, 200), color="white").save(src_dir / "2.jpg")
    Image.new("RGB", (150, 200), color="white").save(src_dir / "1.jpg")
    (src_dir / "notes.txt").write_text("credits", encoding="utf-8")

    fmt, items = ArchiveHandler.extract(src_dir, tmp_path / "work")
    assert fmt == "folder"
    img_names = [it.relative_name for it in items if it.is_image]
    assert img_names == ["1.jpg", "2.jpg"]

    dst_dir = tmp_path / "raw_chapter_fr"
    rendered = {"1.jpg": Image.new("RGB", (150, 200), color="black")}
    ArchiveHandler.pack(fmt, src_dir, dst_dir, items, rendered)
    assert (dst_dir / "1.jpg").exists()
    assert (dst_dir / "2.jpg").exists()
    assert (dst_dir / "notes.txt").read_text(encoding="utf-8") == "credits"


# =====================================================================
# 4. Tests API FastAPI (TestClient)
# =====================================================================

client = TestClient(app)


def test_api_index_and_settings():
    r = client.get("/")
    assert r.status_code == 200
    assert "Manga Translator" in r.text

    r_get = client.get("/api/settings")
    assert r_get.status_code == 200
    data = r_get.json()
    assert "provider" in data

    r_post = client.post("/api/settings", json={"font_style": "bold"})
    assert r_post.status_code == 200
    assert r_post.json()["status"] == "ok"


def test_api_upload_real_cbz_and_endpoints():
    real_cbz = Path(__file__).resolve().parent.parent / "Otome Game Sekai wa Mob ni Kibishii Sekai desu" / "Official_Chapter 37.cbz"
    assert real_cbz.exists(), f"Fichier CBZ de test introuvable : {real_cbz}"

    with open(real_cbz, "rb") as f:
        r_up = client.post("/api/upload", files={"file": (real_cbz.name, f, "application/octet-stream")})

    assert r_up.status_code == 200
    up_data = r_up.json()
    session_id = up_data["session_id"]
    assert up_data["total_pages"] > 0
    assert up_data["format"] == "cbz"

    # Original image 0
    r_img = client.get(f"/api/image/{session_id}/original/0")
    assert r_img.status_code == 200
    assert r_img.headers["content-type"] == "image/jpeg"

    # Download returns valid ZIP/CBZ
    r_dl = client.get(f"/api/download/{session_id}")
    assert r_dl.status_code == 200
    assert zipfile.is_zipfile(io.BytesIO(r_dl.content))


def test_api_upload_folder_endpoint():
    buf1 = io.BytesIO()
    Image.new("RGB", (120, 160), color="white").save(buf1, format="JPEG")
    buf1.seek(0)

    buf2 = io.BytesIO()
    Image.new("RGB", (120, 160), color="white").save(buf2, format="JPEG")
    buf2.seek(0)

    r = client.post(
        "/api/upload_folder",
        files=[
            ("files", ("mon_chapitre/001.jpg", buf1, "image/jpeg")),
            ("files", ("mon_chapitre/002.jpg", buf2, "image/jpeg")),
        ],
    )
    assert r.status_code == 200
    data = r.json()
    assert data["format"] == "folder"
    assert data["total_pages"] == 2


def test_api_unknown_session_returns_404():
    assert client.get("/api/status/inconnue999").status_code == 404
    assert client.get("/api/image/inconnue999/original/0").status_code == 404
    assert client.get("/api/download/inconnue999").status_code == 404
    assert client.post("/api/translate/cancel/inconnue999").status_code == 404


# =====================================================================
# 5. Test du Worker avec Vision Mockée
# =====================================================================

def test_worker_mocked_translation(monkeypatch):
    # Create a tiny 2-page CBZ in memory
    cbz_buf = io.BytesIO()
    with zipfile.ZipFile(cbz_buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name in ("001.jpg", "002.jpg"):
            ibuf = io.BytesIO()
            Image.new("RGB", (300, 400), color="white").save(ibuf, format="JPEG")
            z.writestr(name, ibuf.getvalue())
    cbz_buf.seek(0)

    r_up = client.post("/api/upload", files={"file": ("mini.cbz", cbz_buf, "application/octet-stream")})
    assert r_up.status_code == 200
    session_id = r_up.json()["session_id"]

    def fake_detect_and_translate(self, img, max_side=1600, context_history=None):
        return (
            [{"box": (100.0, 100.0, 250.0, 180.0), "ja": "テスト", "fr": "Bulle traduite"}],
            "mock/vision-v1",
        )

    monkeypatch.setattr(CloudVisionClient, "detect_and_translate", fake_detect_and_translate)
    monkeypatch.setattr("server.refine_translations_with_groq", lambda blocks, **kw: None)

    _run_translation_worker(session_id, {"provider": "auto"})

    st = sessions[session_id]
    assert st["status"] == "finished"
    assert all(p["status"] == "done" for p in st["pages"])
    assert all(p["blocks_count"] == 1 for p in st["pages"])

    pages_dir = Path(st["session_dir"]) / "pages"
    assert (pages_dir / "page_000_trans.jpg").exists()
    assert (pages_dir / "page_001_trans.jpg").exists()


# =====================================================================
# 6. Tests Scanlation Pro (Tâche 4bis : Bbox, Smart Mask, Groq, Rerender)
# =====================================================================

def test_bbox_disambiguation_xmin_vs_xywh():
    raw = json.dumps([
        {"xmin": 100, "ymin": 200, "xmax": 300, "ymax": 400, "original": "A", "translation": "Un"},
        {"x": 100, "y": 200, "w": 200, "h": 200, "original": "B", "translation": "Deux"},
        # Auto-correction case where LLM returned xmax=850, ymax=920 inside w, h (600 + 850 > 1000)
        {"x": 600, "y": 700, "w": 850, "h": 920, "original": "C", "translation": "Trois"},
    ])
    blocks = parse_and_validate_blocks(raw)
    assert len(blocks) == 3
    assert blocks[0]["box"] == (100.0, 200.0, 300.0, 400.0)
    assert blocks[1]["box"] == (100.0, 200.0, 300.0, 400.0)
    assert blocks[2]["box"] == (600.0, 700.0, 850.0, 920.0)


def test_smart_mask_dark_bubble_and_border_preservation():
    from PIL import ImageDraw
    # 1. Dark narration box (black background) -> should keep dark background & write bright/white text
    dark_img = Image.new("RGB", (400, 400), color=(15, 15, 15))
    out_dark = render_manga_page(
        img=dark_img,
        blocks=[{"box": (100, 100, 900, 500), "fr": "Narration sombre importante !"}],
        font_style="bold",
        mask_style="smart",
    )
    crop_dark = out_dark.crop((40, 40, 360, 200)).convert("L")
    vals_dark = sorted(crop_dark.get_flattened_data() if hasattr(crop_dark, "get_flattened_data") else list(crop_dark.getdata()))
    # Background median remains dark (< 50), while text pixels are bright (> 200)
    assert vals_dark[len(vals_dark) // 2] < 50
    assert vals_dark[-1] > 200

    # 2. White bubble with a thick black border along the box perimeter -> border must NOT be destroyed
    bubble_img = Image.new("RGB", (400, 400), color=(255, 255, 255))
    d = ImageDraw.Draw(bubble_img)
    # Draw black border right along pixel coords (40, 40, 360, 200) -> normalized (100, 100, 900, 500)
    d.rectangle([40, 40, 359, 199], outline=(0, 0, 0), width=3)
    # Draw fake Japanese ink strokes in the middle (not touching the border)
    d.rectangle([150, 90, 250, 130], fill=(0, 0, 0))

    out_bubble = render_manga_page(
        img=bubble_img,
        blocks=[{"box": (100, 100, 900, 500), "fr": "Salut !"}],
        font_style="bold",
        mask_style="smart",
    )
    # Verify the black border pixel at top edge (200, 41) is still black!
    assert out_bubble.getpixel((200, 41)) == (0, 0, 0)
    assert out_bubble.getpixel((41, 120)) == (0, 0, 0)


def test_groq_refine_polishes_all_bubbles_even_with_draft(monkeypatch):
    import app.groq_refine as gr

    class FakeChoice:
        def __init__(self, content):
            self.message = type("M", (), {"content": content})()

    class FakeCompletions:
        def create(self, **kwargs):
            return type("R", (), {"choices": [FakeChoice('["Mais qu\'est-ce que tu racontes ?!", "Dégage de là !"]')]})()

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = type("C", (), {"completions": FakeCompletions()})()

    monkeypatch.setattr(gr, "OpenAI", FakeOpenAI)

    blocks = [
        {"box": (10, 10, 200, 100), "ja": "何を言っているんだ", "fr": "Brouillon littéral 1"},
        {"box": (10, 120, 200, 200), "ja": "あっちへ行け", "fr": "Brouillon littéral 2"},
    ]
    gr.refine_translations_with_groq(blocks, groq_api_key="fake_groq_test_key", target_lang="French")
    assert blocks[0]["fr"] == "Mais qu'est-ce que tu racontes ?!"
    assert blocks[1]["fr"] == "Dégage de là !"


def test_api_rerender_live_bubble_editor_under_200ms():
    import time
    ibuf = io.BytesIO()
    Image.new("RGB", (600, 800), color="white").save(ibuf, format="JPEG")
    ibuf.seek(0)

    r_up = client.post("/api/upload", files={"file": ("page.jpg", ibuf, "image/jpeg")})
    assert r_up.status_code == 200
    session_id = r_up.json()["session_id"]

    t0 = time.perf_counter()
    r_rerender = client.post(
        f"/api/rerender/{session_id}/0",
        json={
            "blocks": [
                {"box": [100, 100, 500, 300], "ja": "原文", "fr": "Texte modifié en direct !"}
            ],
            "mask_style": "smart",
        },
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    assert r_rerender.status_code == 200
    data = r_rerender.json()
    assert data["status"] == "done"
    assert data["blocks_count"] == 1
    assert data["blocks"][0]["fr"] == "Texte modifié en direct !"
    assert elapsed_ms < 200.0


def test_multi_manga_resolution_and_webtoon_generalization():
    from app.typesetter import render_manga_page
    from app.cloud_vision import encode_image_for_vision

    # 1. Small 700px scan
    small_img = Image.new("RGB", (700, 1000), color="white")
    out_small = render_manga_page(
        small_img,
        [{"box": (50, 50, 280, 180), "fr": "Petit scan ancien"}],
        mask_style="smart",
    )
    assert out_small.size == (700, 1000)

    # 2. High-res 3000px double-page spread
    spread_img = Image.new("RGB", (3000, 2100), color="white")
    raw_s, b64_spread = encode_image_for_vision(spread_img, max_side=1600)
    assert len(raw_s) > 100 and len(b64_spread) > 100
    out_spread = render_manga_page(
        spread_img,
        [{"box": (200, 200, 900, 600), "fr": "Double page haute définition !"}],
        mask_style="smart",
    )
    assert out_spread.size == (3000, 2100)

    # 3. Tall Webtoon vertical strip (800 x 3200)
    webtoon_img = Image.new("RGB", (800, 3200), color="white")
    raw_wt, b64_wt = encode_image_for_vision(webtoon_img, max_side=1600)
    assert len(raw_wt) > 100 and len(b64_wt) > 100
    out_wt = render_manga_page(
        webtoon_img,
        [{"box": (100, 400, 700, 800), "fr": " Bande verticale Webtoon / Manhwa "}],
        mask_style="smart",
    )
    assert out_wt.size == (800, 3200)


