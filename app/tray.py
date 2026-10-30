#!/usr/bin/env python3
"""
Manga Translator Studio - System Tray (Barre des Tâches PC)
Permet de contrôler, surveiller et arrêter le serveur local depuis la barre des tâches.
"""
import os
import sys
import time
import signal
import webbrowser
import subprocess
import threading
from pathlib import Path

try:
    import pystray
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("[Manga Tray] Erreur: pystray ou Pillow n'est pas installé.")
    sys.exit(1)

BASE_DIR = Path(__file__).resolve().parent.parent
SERVER_URL = "http://127.0.0.1:8000"
OUTPUT_DIR = BASE_DIR / "data" / "output"


def create_tray_image(size=(64, 64), is_online=True):
    """Génère une icône nette pour la barre des tâches."""
    img = Image.new("RGBA", size, color=(0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Fond arrondi dégradé manga (Magenta / Violet)
    margin = 4
    draw.rounded_rectangle(
        [margin, margin, size[0] - margin, size[1] - margin],
        radius=14,
        fill=(244, 63, 94, 255) if is_online else (100, 116, 139, 255),
        outline=(255, 255, 255, 220),
        width=2,
    )

    # Symbole livre / planche de manga stylisée
    # Page gauche
    draw.rectangle([16, 18, 30, 46], fill=(255, 255, 255, 240))
    # Page droite
    draw.rectangle([34, 18, 48, 46], fill=(255, 255, 255, 240))
    # Reliure centrale
    draw.line([(32, 18), (32, 46)], fill=(139, 92, 246, 255), width=2)
    # Lignes de texte manga simulées
    draw.line([(19, 24), (27, 24)], fill=(244, 63, 94, 200), width=2)
    draw.line([(19, 30), (27, 30)], fill=(244, 63, 94, 200), width=2)
    draw.line([(19, 36), (25, 36)], fill=(244, 63, 94, 200), width=2)
    draw.line([(37, 24), (45, 24)], fill=(139, 92, 246, 200), width=2)
    draw.line([(37, 30), (45, 30)], fill=(139, 92, 246, 200), width=2)

    # Point indicateur vert ou gris (statut)
    indicator_color = (16, 185, 129, 255) if is_online else (239, 68, 68, 255)
    draw.ellipse([size[0] - 18, size[1] - 18, size[0] - 4, size[1] - 4], fill=indicator_color, outline=(255, 255, 255, 255), width=2)

    return img


def is_server_alive():
    """Vérifie si le serveur répond sur le port 8000."""
    try:
        import urllib.request
        with urllib.request.urlopen(f"{SERVER_URL}/api/system/check_update", timeout=1.5) as res:
            return res.status == 200
    except Exception:
        return False


def action_open_browser(icon, item):
    """Ouvre l'interface web dans le navigateur."""
    try:
        webbrowser.open(SERVER_URL)
    except Exception as e:
        print(f"[Manga Tray] Erreur ouverture navigateur: {e}")


def action_open_output(icon, item):
    """Ouvre le dossier des mangas traduits."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(["xdg-open", str(OUTPUT_DIR)], check=False)
    except Exception as e:
        print(f"[Manga Tray] Erreur ouverture dossier: {e}")


def action_stop_server(icon, item):
    """Arrête proprement le serveur local et ferme l'icône de la barre des tâches."""
    print("[Manga Tray] Arrêt du serveur demandé...")
    # 1. Appel HTTP à l'API shutdown
    try:
        import urllib.request
        req = urllib.request.Request(f"{SERVER_URL}/api/system/shutdown", method="POST")
        with urllib.request.urlopen(req, timeout=2):
            pass
    except Exception:
        pass

    # 2. Kill de sécurité sur le processus uvicorn
    try:
        subprocess.run(["pkill", "-f", "uvicorn server:app"], check=False)
    except Exception:
        pass

    # 3. Notification de bureau
    try:
        subprocess.run([
            "notify-send",
            "Manga Translator Studio",
            "Le serveur local a été arrêté avec succès.",
            "-i", "dialog-information"
        ], check=False)
    except Exception:
        pass

    # Fermer l'icône
    icon.stop()


def action_restart_server(icon, item):
    """Redémarre le serveur local."""
    action_stop_server(icon, item)
    time.sleep(1)
    subprocess.Popen([str(BASE_DIR / "lancer_manga_translator.sh")], cwd=str(BASE_DIR))


def build_menu():
    """Construit le menu contextuel du tray."""
    alive = is_server_alive()
    status_label = "🟢 Serveur : En ligne (Port 8000)" if alive else "🔴 Serveur : Hors ligne"

    return pystray.Menu(
        pystray.MenuItem(status_label, lambda icon, item: None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("📖 Ouvrir Manga Translator Studio", action_open_browser, default=True),
        pystray.MenuItem("📁 Ouvrir le dossier des Mangas", action_open_output),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("🛑 Arrêter le Serveur Local", action_stop_server),
        pystray.MenuItem("❌ Quitter l'icône seule", lambda icon, item: icon.stop()),
    )


def main():
    img = create_tray_image(is_online=True)
    icon = pystray.Icon(
        name="manga_translator_studio",
        icon=img,
        title="Manga Translator Studio (Port 8000)",
        menu=build_menu,
    )

    # Thread périodique pour rafraîchir l'icône selon l'état du serveur
    def monitor_loop():
        last_state = None
        while icon.visible:
            alive = is_server_alive()
            if alive != last_state:
                icon.icon = create_tray_image(is_online=alive)
                icon.title = f"Manga Translator Studio ({'En ligne' if alive else 'Hors ligne'})"
                icon.menu = build_menu()
                last_state = alive
            time.sleep(3)

    monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
    monitor_thread.start()

    print("[Manga Tray] Icône de la barre des tâches démarrée.")
    icon.run()


if __name__ == "__main__":
    main()
