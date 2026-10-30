# E2E Test Infra: Manga Translator Studio

## Test Philosophy
- Opaque-box, requirement-driven. No dependency on implementation internals.
- Methodology: Category-Partition + BVA + Pairwise + Workload Testing.
- Focus: Multi-page chapter translation, failover on 429 quota exhaustion, archive extraction/repackaging resilience, live UI status, comparison slider/split-view.

## Feature Inventory
| # | Feature | Source (requirement) | Tier 1 | Tier 2 | Tier 3 |
|---|---------|---------------------|:------:|:------:|:------:|
| 1 | Vision Model Selection & API Keys | ORIGINAL_REQUEST §R1 | 5 | 5 | ✓ |
| 2 | HTTP 429 Rate Limit & Quota Failover | ORIGINAL_REQUEST §R1 | 5 | 5 | ✓ |
| 3 | Pipeline CLI Execution | ORIGINAL_REQUEST §R1, R2 | 5 | 5 | ✓ |
| 4 | Multi-Page Archive Parsing (CBZ/CBR/ZIP/Dir) | ORIGINAL_REQUEST §R2 | 5 | 5 | ✓ |
| 5 | Natural Sorting & Page Order | ORIGINAL_REQUEST §R2 | 5 | 5 | ✓ |
| 6 | macOS `__MACOSX/` & AppleDouble Resilience | ORIGINAL_REQUEST §R2 | 5 | 5 | ✓ |
| 7 | Inpaint & Smart Bubble Masking | ORIGINAL_REQUEST §R2 | 5 | 5 | ✓ |
| 8 | Typography Diamond Wrap & French Quotes/Spaces | ORIGINAL_REQUEST §R2 | 5 | 5 | ✓ |
| 9 | Partial Page Error Resilience (No Chapter Crash) | ORIGINAL_REQUEST §R2 | 5 | 5 | ✓ |
| 10 | Complete Chapter Repackaging & Metadata | ORIGINAL_REQUEST §R2 | 5 | 5 | ✓ |
| 11 | Web Reader Modes (Original, Trans, Split, Slider) | ORIGINAL_REQUEST §R3 | 5 | 5 | ✓ |
| 12 | Live Processing Status & Polling | ORIGINAL_REQUEST §R3 | 5 | 5 | ✓ |

## Test Architecture
- Test runner: `pytest tests/test_multipage_e2e.py`
- Test fixtures: `Otome Game Sekai wa Mob ni Kibishii Sekai desu/Official_Chapter 41.5.cbz` (3 pages), synthetic multi-page CBZ with ComicInfo.xml and macOS `__MACOSX/` artifacts.
- In-memory mock & live mock harnesses for provider failover (OpenRouter 429 -> NVIDIA NIM 200).

## Real-World Application Scenarios (Tier 4)
| # | Scenario | Features Exercised | Complexity |
|---|----------|--------------------|------------|
| 1 | Full Chapter Multi-Page E2E Translation | F4, F5, F7, F8, F10 | High |
| 2 | Simulated Quota Exhaustion & Transparent NIM Failover | F1, F2, F9, F10 | High |
| 3 | Corrupted Page Isolation in Multi-Page Archive | F4, F9, F10 | Medium |
| 4 | Dirty macOS Archive Extraction & Translation | F4, F5, F6, F10 | Medium |
| 5 | Reader Split-View & Slider DOM State Consistency | F11, F12 | Medium |

## Coverage Thresholds
- Tier 1: ≥5 per feature
- Tier 2: ≥5 per feature (where boundaries exist)
- Tier 3: pairwise coverage of major feature interactions
- Tier 4: ≥5 realistic application scenarios
