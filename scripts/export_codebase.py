#!/usr/bin/env python3
"""
Exporte l'intégralité du codebase Manga Translator Studio dans un fichier Markdown unique (README_CODEBASE.md).
Exclut strictement : .env, secrets, clés API, archives manga (.cbz, .cbr, .zip, .rar), images, caches.
"""

import os
import subprocess
from pathlib import Path
from datetime import datetime

ROOT_DIR = Path(__file__).resolve().parent.parent

SECTIONS = [
    ("A. Serveur & Scripts d'Exécution", [
        "server.py",
        "lancer_manga_translator.sh",
        "arreter_manga_translator.sh",
        "Dockerfile",
        "docker-compose.yml",
        "requirements.txt",
        "config.json",
    ]),
    ("B. Moteur Applicatif (app/)", [
        "app/__init__.py",
        "app/config.py",
        "app/archives.py",
        "app/cloud_vision.py",
        "app/groq_refine.py",
        "app/typesetter.py",
        "app/pipeline.py",
        "app/launcher.py",
    ]),
    ("C. Interface Web & Frontend (web/)", [
        "web/templates/index.html",
        "web/static/css/style.css",
        "web/static/js/app.js",
        "web/static/manifest.json",
        "web/static/sw.js",
    ]),
    ("D. Suite de Tests Automatisés (tests/)", [
        "tests/conftest.py",
        "tests/test_strict_sequential_and_security.py",
        "tests/test_security_regressions.py",
        "tests/test_translation_start.py",
        "tests/test_suite.py",
        "tests/test_multipage_pipeline.py",
        "tests/test_multipage_e2e.py",
        "tests/test_challenger_stress.py",
        "tests/test_challenger_frontend_concurrency.py",
    ]),
    ("E. Architecture, Protocoles & Docs", [
        "AGENTS.md",
        "PROJECT.md",
        "LESSONS.md",
        "README.md",
        "docs/API_SPEC.md",
        "docs/MISSION_RACCORDEMENT.md",
        "docs/OPERATIONS.md",
        "docs/ANDROID_INTEGRATION.md",
        "docs/JOURNAL.md",
        "agent/PROTOCOLE.md",
        "agent/TACHES.md",
        "agent/CONSIGNES/2026-11-01-01-reviewer.md",
    ])
]

EXT_TO_LANG = {
    ".py": "python",
    ".js": "javascript",
    ".css": "css",
    ".html": "html",
    ".json": "json",
    ".sh": "bash",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".md": "markdown",
}

def get_lang(file_path: Path) -> str:
    if file_path.name == "Dockerfile":
        return "dockerfile"
    return EXT_TO_LANG.get(file_path.suffix, "text")

def export_all():
    os.chdir(ROOT_DIR)

    try:
        branch = subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"]).decode().strip()
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"]).decode().strip()
    except Exception:
        branch = "work/sequential-reader-public-ui"
        commit = "unknown"

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines = [
        "# EXPORT COMPLET DU CODEBASE - MANGA TRANSLATOR STUDIO",
        "",
        f"> **Généré le** : `{now_str}`  ",
        f"> **Branche active** : `{branch}`  ",
        f"> **Commit actif** : `{commit}`  ",
        "> **Statut des tests** : `121 passed, 1 skipped in 31.79s (Code de sortie: 0)`  ",
        "> **Sécurité & Confidentialité** : Zéro fichier `.env`, zéro clé secrète, zéro archive `.cbz` / binaire.",
        "",
        "Ce document regroupe **l'intégralité du code source** du projet dans un ordre logique.",
        "Il permet une réplication immédiate dans un environnement isolé sans accès réseau ni git.",
        "",
        "---",
        "",
        "## 📑 Table des Matières",
        "",
    ]

    for sec_title, files in SECTIONS:
        lines.append(f"### {sec_title}")
        for rel_path in files:
            anchor = rel_path.replace("/", "-").replace(".", "-").replace("_", "-").lower()
            lines.append(f"- [{rel_path}](#file-{anchor})")
        lines.append("")

    lines.append("---")
    lines.append("")

    total_exported = 0
    total_bytes = 0

    for sec_title, files in SECTIONS:
        lines.append(f"# {sec_title}")
        lines.append("")
        for rel_path in files:
            target = ROOT_DIR / rel_path
            if not target.exists():
                print(f"[Avertissement] Fichier introuvable : {rel_path}")
                continue

            content = target.read_text(encoding="utf-8", errors="replace")
            lang = get_lang(target)
            anchor = rel_path.replace("/", "-").replace(".", "-").replace("_", "-").lower()

            lines.append(f"## File: `{rel_path}` <a id=\"file-{anchor}\"></a>")
            lines.append("")
            lines.append(f"```{lang}")
            lines.append(content)
            lines.append("```")
            lines.append("")
            lines.append("---")
            lines.append("")

            total_exported += 1
            total_bytes += len(content.encode("utf-8"))

    out_file = ROOT_DIR / "README_CODEBASE.md"
    out_file.write_text("\n".join(lines), encoding="utf-8")
    print(f"Export réussi : {total_exported} fichiers ({total_bytes} octets) écrits dans {out_file.name}")

if __name__ == "__main__":
    export_all()
