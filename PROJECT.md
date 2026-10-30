# Project: Manga Translator Studio — Finalization & Polish

## Architecture
- **Backend**: FastAPI (`server.py`) with background task orchestration (`ThreadPoolExecutor`), multi-page archive processor (`app/archives.py`), cloud vision engine router (`app/cloud_vision.py`), typography & inpaint engine (`app/typesetter.py`), Groq dialogue refiner (`app/groq_refine.py`), pipeline CLI (`app/pipeline.py`).
- **Frontend**: Lightweight vanilla Web UI (`web/templates/index.html`, `web/static/js/app.js`, `web/static/css/style.css`), live polling mechanism (~400ms-700ms), dynamic canvas renderer, CSS clip-path comparison slider, and split-view dual stage.
- **Inference Providers**: NVIDIA NIM (primary vision), OpenRouter (vision + fallback), Groq (fast dialogue refinement), OpenAI-compatible custom endpoints.

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Vision Model Catalog & Discovery | Remove dead vision models (Groq), fix OpenRouter model IDs (Qwen2.5-VL), validate NIM endpoints | M1 | Survey 1 |
| 2 | Pipeline Client Signature Fix | Fix `CloudVisionClient` parameter mismatch (`preferred_provider` -> `provider`) in `app/pipeline.py` | M1 | Survey 1 |
| 3 | Cloud Vision System Prompt & Reasoning Extraction | Pass strict system message for JSON schema and handle Nemotron reasoning tokens | M1 | Survey 1 |
| 4 | HTTP 429 Quota Failover | Automatically failover from exhausted OpenRouter to NVIDIA NIM without crashing | M1 | Survey 1 |
| 5 | Archive Handling & macOS Resilience | Filter `__MACOSX/` and `._*` files, natural sort, safe zip extraction | M2 | Survey 2 |
| 6 | Multi-Page Concurrency & Thread Safety | Thread-safe inter-page context propagation during parallel page processing | M2 | Survey 2 |
| 7 | Single-Page Cache Invalidation | Allow forced re-translation of individual pages without stale cache lock | M2 | Survey 2 |
| 8 | CBR/CBZ Repackaging Robustness | Clean packaging and metadata preservation with ZIP-CBR fallback | M2 | Survey 2 |
| 9 | Reader Comparison Modes (Split-View & Slider) | Re-integrate side-by-side split view and interactive CSS clip-path A/B slider | M3 | Survey 3 |
| 10 | Settings Modal Flexbox Fix | Fix `.settings-tabs` compression via `flex-shrink: 0` | M3 | Survey 3 |
| 11 | Live Animation Queue & Typography Consistency | Non-skipping reveal queue (~1.8s) for parallel pages and font-style preview alignment | M3 | Survey 3 |
| 12 | E2E Multi-Page Test Suite | Comprehensive tests covering multi-page chapters, fallback, archive integrity, and UI | T1 | E2E Track |
| 13 | Final E2E 100% Pass & Adversarial Hardening | Full multi-page chapter validation and coverage audit | M4 | Final Milestone |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| T1 | E2E Testing Track | Design multi-page test harness, mock/live fallback tests, publish TEST_READY.md | none | IN_PROGRESS |
| M1 | Engine Reliability & Failover (R1) | Fix pipeline signature, clean model catalogs, system prompts, 429 NIM failover | none | IN_PROGRESS |
| M2 | Multi-Page Pipeline Hardening (R2) | macOS AppleDouble filter, thread-safe context, cache invalidation, repackaging | M1 | PLANNED |
| M3 | Live Animations & Reader Modes (R3) | Split-view, CSS clip-path slider, animation queue tuning, settings modal fix | none | PLANNED |
| M4 | Final E2E Pass & Hardening | Pass 100% E2E tests on multi-page chapters, adversarial coverage audit | T1, M1, M2, M3 | PLANNED |

## Interface Contracts
### `app/cloud_vision.py` ↔ `app/pipeline.py` & `server.py`
- `CloudVisionClient.__init__(provider: str = "auto", api_key: Optional[str] = None, model: Optional[str] = None, ...)`
- `detect_bubbles(image_bytes: bytes) -> List[Dict[str, Any]]`: returns list of dicts with `{"box_2d": [ymin, xmin, ymax, xmax], "text": str, "translation": str}`.
- Fallback contract: If HTTP 429 / InsufficientQuota on provider, automatically attempt fallback to NVIDIA NIM (`meta/llama-3.2-11b-vision-instruct`) if configured.

### `app/archives.py` ↔ `server.py`
- `ArchiveHandler.extract(archive_path: Path, dest_dir: Path) -> List[Path]`: must ignore all `__MACOSX/` directories and `._*` resource fork files.
- `ArchiveHandler.repackage(orig_path: Path, pages: List[Path], output_path: Path) -> Path`: must produce complete archive matching original count.

### `web/templates/index.html` ↔ `web/static/js/app.js` ↔ `web/static/css/style.css`
- `#view-mode` buttons: `data-mode="translated"`, `data-mode="original"`, `data-mode="split"`, `data-mode="slider"`.
- Slider: container `#slider-container` with `#slider-orig`, `#slider-trans` (clip-path `inset(0 calc(100% - var(--slider-pos, 50%)) 0 0)`), `#slider-handle`.
- Split-view: `#stage.mode-split` displays both original and translated canvas side-by-side.

## Code Layout
- `app/config.py`: Provider presets, model definitions, `.env` loader.
- `app/cloud_vision.py`: Cloud vision HTTP client, prompt templates, JSON parsing, fallback logic.
- `app/pipeline.py`: Standalone CLI pipeline orchestrator.
- `app/archives.py`: Archive extraction, natural sorting, repackaging.
- `app/typesetter.py`: Inpainting, bubble masking, diamond wrap typography.
- `server.py`: FastAPI server, session endpoints, live image serving, re-rendering.
- `web/templates/index.html`: Web interface DOM structure.
- `web/static/css/style.css`: Visual styling, animations, split-view & slider styles.
- `web/static/js/app.js`: Client state, live polling, animation reveal queue, interaction handlers.
- `tests/test_suite.py`: Unit and integration test suite.
- `tests/test_multipage_e2e.py`: New multi-page end-to-end tests.
