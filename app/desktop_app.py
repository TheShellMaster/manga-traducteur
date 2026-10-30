#!/usr/bin/env python3
"""
Manga Translator Studio - Application Bureau & Contrôleur de Tâches
Fenêtre native qui intègre l'application dans la barre des tâches / dock des applications actives de l'OS.
Permet d'ouvrir, surveiller et surtout arrêter le serveur local en 1 clic ou en fermant l'app depuis la barre des tâches.
"""

import os
import sys
import time
import signal
import subprocess
import threading
import webbrowser
import urllib.request
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox

BASE_DIR = Path(__file__).resolve().parent.parent
SERVER_URL = "http://127.0.0.1:8000"
OUTPUT_DIR = BASE_DIR / "data" / "output"
ICON_PATH = BASE_DIR / "web" / "static" / "icons" / "icon-192.png"


def is_server_alive():
    """Vérifie si le serveur local répond sur le port 8000."""
    try:
        req = urllib.request.Request(f"{SERVER_URL}/api/system/check_update")
        with urllib.request.urlopen(req, timeout=1.2) as res:
            return res.status == 200
    except Exception:
        return False


class MangaDesktopApp:
    def __init__(self, root):
        self.root = root
        self.server_proc = None
        self.is_stopping = False

        # Configuration de la fenêtre native pour l'intégration dans la barre des tâches
        self.root.title("Manga Translator Studio")
        self.root.geometry("460x320")
        self.root.minsize(420, 290)
        self.root.resizable(False, False)
        self.root.configure(bg="#0b0f19")

        # Icône native dans la barre des tâches de l'OS
        if ICON_PATH.exists():
            try:
                self.icon_photo = tk.PhotoImage(file=str(ICON_PATH))
                self.root.iconphoto(True, self.icon_photo)
            except Exception as e:
                print(f"[Desktop App] Note icône: {e}")

        # Capture de la fermeture de la fenêtre (clic sur la croix [X], Alt+F4 ou 'Quitter' depuis le Dock)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close_requested)

        self._build_ui()
        self._ensure_server_running()

        # Surveillance périodique du statut du serveur
        self._start_status_watcher()

    def _build_ui(self):
        # Header avec Logo & Titre
        header_frame = tk.Frame(self.root, bg="#0b0f19", pady=16)
        header_frame.pack(fill="x", padx=20)

        title_label = tk.Label(
            header_frame,
            text="📖 Manga Translator Studio",
            font=("DejaVu Sans", 16, "bold"),
            fg="#f8fafc",
            bg="#0b0f19",
        )
        title_label.pack(anchor="center")

        subtitle = tk.Label(
            header_frame,
            text="100% Cloud Vision • Zéro Modèle Local • Application Active",
            font=("DejaVu Sans", 9),
            fg="#94a3b8",
            bg="#0b0f19",
        )
        subtitle.pack(anchor="center", pady=(2, 0))

        # Carte d'état du serveur
        status_card = tk.Frame(self.root, bg="#131b2e", bd=1, relief="solid", padx=16, pady=12)
        status_card.pack(fill="x", padx=20, pady=(0, 14))

        self.status_dot = tk.Label(
            status_card,
            text="●",
            font=("DejaVu Sans", 14),
            fg="#10b981",
            bg="#131b2e",
        )
        self.status_dot.pack(side="left", padx=(0, 8))

        status_text_frame = tk.Frame(status_card, bg="#131b2e")
        status_text_frame.pack(side="left", fill="both", expand=True)

        self.status_title = tk.Label(
            status_text_frame,
            text="Serveur Local Actif",
            font=("DejaVu Sans", 10, "bold"),
            fg="#f8fafc",
            bg="#131b2e",
            anchor="w",
        )
        self.status_title.pack(fill="x")

        self.status_desc = tk.Label(
            status_text_frame,
            text=f"En écoute sur {SERVER_URL} (RAM < 50 Mo)",
            font=("DejaVu Sans", 8),
            fg="#94a3b8",
            bg="#131b2e",
            anchor="w",
        )
        self.status_desc.pack(fill="x")

        # Boutons d'action principaux
        btn_frame = tk.Frame(self.root, bg="#0b0f19")
        btn_frame.pack(fill="both", expand=True, padx=20)

        # Bouton Ouvrir Studio Web
        btn_open = tk.Button(
            btn_frame,
            text="🌐 Ouvrir l'Interface Studio (Navigateur)",
            font=("DejaVu Sans", 10, "bold"),
            bg="#2563eb",
            fg="#ffffff",
            activebackground="#1d4ed8",
            activeforeground="#ffffff",
            bd=0,
            padx=12,
            pady=8,
            cursor="hand2",
            command=self.open_browser,
        )
        btn_open.pack(fill="x", pady=4)

        # Ligne de boutons secondaires
        row_frame = tk.Frame(btn_frame, bg="#0b0f19")
        row_frame.pack(fill="x", pady=4)

        btn_folder = tk.Button(
            row_frame,
            text="📁 Mangas Traduits",
            font=("DejaVu Sans", 9),
            bg="#1e293b",
            fg="#cbd5e1",
            activebackground="#334155",
            activeforeground="#ffffff",
            bd=0,
            padx=10,
            pady=6,
            cursor="hand2",
            command=self.open_output_folder,
        )
        btn_folder.pack(side="left", fill="x", expand=True, padx=(0, 4))

        btn_restart = tk.Button(
            row_frame,
            text="🔄 Redémarrer",
            font=("DejaVu Sans", 9),
            bg="#1e293b",
            fg="#cbd5e1",
            activebackground="#334155",
            activeforeground="#ffffff",
            bd=0,
            padx=10,
            pady=6,
            cursor="hand2",
            command=self.restart_server,
        )
        btn_restart.pack(side="right", fill="x", expand=True, padx=(4, 0))

        # Bouton rouge vif : Arrêter le serveur & fermer l'application
        self.btn_stop = tk.Button(
            btn_frame,
            text="🛑 Arrêter le Serveur & Quitter l'Application",
            font=("DejaVu Sans", 10, "bold"),
            bg="#dc2626",
            fg="#ffffff",
            activebackground="#b91c1c",
            activeforeground="#ffffff",
            bd=0,
            padx=12,
            pady=8,
            cursor="hand2",
            command=self.on_close_requested,
        )
        self.btn_stop.pack(fill="x", pady=(8, 0))

    def _ensure_server_running(self):
        """Démarre le serveur FastAPI en tâche de fond s'il n'est pas déjà lancé."""
        if not is_server_alive():
            print("[Desktop App] Démarrage du serveur uvicorn...")
            venv_python = BASE_DIR / "venv" / "bin" / "python3"
            python_bin = str(venv_python) if venv_python.exists() else sys.executable
            self.server_proc = subprocess.Popen(
                [python_bin, "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", "8000", "--log-level", "warning"],
                cwd=str(BASE_DIR),
            )
            # Attendre que le serveur réponde
            for _ in range(25):
                if is_server_alive():
                    break
                time.sleep(0.2)

        # Ouvre automatiquement l'interface web dans le navigateur
        threading.Thread(target=self._delayed_browser_open, daemon=True).start()

    def _delayed_browser_open(self):
        time.sleep(1.0)
        self.open_browser()

    def open_browser(self):
        try:
            webbrowser.open(SERVER_URL)
        except Exception as e:
            print(f"[Desktop App] Erreur ouverture navigateur: {e}")

    def open_output_folder(self):
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.run(["xdg-open", str(OUTPUT_DIR)], check=False)
        except Exception as e:
            print(f"[Desktop App] Erreur ouverture dossier: {e}")

    def restart_server(self):
        self.status_title.config(text="Redémarrage du serveur...")
        self.status_dot.config(fg="#f59e0b")
        threading.Thread(target=self._restart_thread, daemon=True).start()

    def _restart_thread(self):
        self._stop_backend_processes()
        time.sleep(1.0)
        self._ensure_server_running()

    def _start_status_watcher(self):
        def watcher():
            while not self.is_stopping:
                alive = is_server_alive()
                if alive:
                    self.status_dot.config(fg="#10b981")
                    self.status_title.config(text="Serveur Local Actif")
                    self.status_desc.config(text=f"En écoute sur {SERVER_URL} (RAM < 50 Mo)")
                else:
                    self.status_dot.config(fg="#ef4444")
                    self.status_title.config(text="Serveur Hors Ligne")
                    self.status_desc.config(text="Le serveur local ne répond pas.")
                time.sleep(2.5)

        threading.Thread(target=watcher, daemon=True).start()

    def _stop_backend_processes(self):
        """Envoie l'ordre d'extinction propre et tue les processus uvicorn résiduels."""
        # 1. Appel HTTP à l'API shutdown
        try:
            req = urllib.request.Request(f"{SERVER_URL}/api/system/shutdown", method="POST")
            with urllib.request.urlopen(req, timeout=1.5):
                pass
        except Exception:
            pass

        # 2. Terminaison du processus enfant si nous l'avons lancé
        if self.server_proc and self.server_proc.poll() is None:
            try:
                self.server_proc.terminate()
                self.server_proc.wait(timeout=2)
            except Exception:
                try:
                    self.server_proc.kill()
                except Exception:
                    pass

        # 3. Sécurité : pkill sur tout uvicorn restant sur ce projet
        try:
            subprocess.run(["pkill", "-f", "uvicorn server:app"], check=False)
        except Exception:
            pass

        # 4. Arrêt de l'icône de tray éventuelle
        try:
            subprocess.run(["pkill", "-f", "app/tray.py"], check=False)
        except Exception:
            pass

    def on_close_requested(self):
        """
        Déclenché quand l'utilisateur clique sur la croix [X], Alt+F4,
        ou sélectionne 'Quitter' depuis la barre des tâches / Dock des applications actives.
        """
        if self.is_stopping:
            return
        self.is_stopping = True

        self.btn_stop.config(text="Arrêt en cours...", state="disabled", bg="#7f1d1d")
        self.status_title.config(text="Extinction du serveur...")
        self.status_dot.config(fg="#ef4444")

        # Arrêter les processus en arrière-plan
        self._stop_backend_processes()

        # Notification de bureau
        try:
            subprocess.run([
                "notify-send",
                "Manga Translator Studio",
                "Serveur local et application arrêtés avec succès.",
                "-i", "process-stop"
            ], check=False)
        except Exception:
            pass

        # Fermer la fenêtre native
        self.root.after(300, self.root.destroy)


def main():
    root = tk.Tk(className="manga-translator-studio")
    app = MangaDesktopApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
