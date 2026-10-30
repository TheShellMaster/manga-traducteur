import io
import os
import re
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional
from PIL import Image

from app.config import IMAGE_EXTENSIONS


def natural_sort_key(s: str) -> List[Any]:
    """Sort strings with embedded numbers naturally (e.g. 1, 2, 10 instead of 1, 10, 2)."""
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r"(\d+)", s)]


class ArchiveItem:
    """Represents a single entry inside an archive, directory, or standalone image."""
    def __init__(self, relative_name: str, is_image: bool, raw_bytes: Optional[bytes] = None, source_path: Optional[Path] = None):
        self.relative_name = relative_name
        self.is_image = is_image
        self.raw_bytes = raw_bytes
        self.source_path = source_path

    def get_image(self) -> Image.Image:
        if self.raw_bytes is not None:
            img = Image.open(io.BytesIO(self.raw_bytes))
        elif self.source_path is not None:
            img = Image.open(self.source_path)
        else:
            raise ValueError(f"No source data for {self.relative_name}")
        img.load()
        return img


class ArchiveHandler:
    """Handles universal reading and writing of Manga archives (CBZ, CBR, RAR, Folder, Image)."""

    @staticmethod
    def detect_format(path: Path) -> str:
        if not path.exists():
            raise ValueError(f"Fichier introuvable : {path}")
        if path.is_dir():
            return "folder"
        if path.stat().st_size == 0:
            raise ValueError(f"Le fichier '{path.name}' est vide (0 octet).")

        suffix = path.suffix.lower()
        if suffix in (".cbz", ".zip"):
            return "cbz"
        if suffix in (".cbr", ".rar"):
            return "rar"
        if suffix in IMAGE_EXTENSIONS:
            return "image"

        # Check magic bytes for ambiguous extensions
        try:
            with open(path, "rb") as f:
                header = f.read(16)
                if header.startswith(b"PK\x03\x04"):
                    return "cbz"
                if header.startswith(b"Rar!\x1a\x07"):
                    return "rar"
                if header.startswith(b"\x89PNG\r\n\x1a\n") or header.startswith(b"\xff\xd8\xff") or header.startswith(b"RIFF") or header.startswith(b"BM"):
                    return "image"
        except Exception:
            pass
        raise ValueError(f"Format non supporté ou fichier non reconnu : {path.name}")

    @staticmethod
    def extract(path: Path, work_dir: Path) -> Tuple[str, List[ArchiveItem]]:
        fmt = ArchiveHandler.detect_format(path)
        items: List[ArchiveItem] = []

        if fmt == "image":
            items.append(ArchiveItem(
                relative_name=path.name,
                is_image=True,
                source_path=path,
            ))
            return fmt, items

        if fmt == "folder":
            for root, _, files in os.walk(path):
                rel_dir = Path(root).relative_to(path)
                for f in sorted(files, key=natural_sort_key):
                    file_path = Path(root) / f
                    rel_name = str((rel_dir / f).as_posix())
                    is_img = file_path.suffix.lower() in IMAGE_EXTENSIONS
                    items.append(ArchiveItem(
                        relative_name=rel_name,
                        is_image=is_img,
                        source_path=file_path,
                    ))
            return fmt, items

        if fmt == "cbz":
            cbz_extract_dir = work_dir / "cbz_extracted"
            cbz_extract_dir.mkdir(parents=True, exist_ok=True)
            resolved_work_dir = cbz_extract_dir.resolve()

            try:
                with zipfile.ZipFile(path, "r") as z:
                    names = sorted(z.namelist(), key=natural_sort_key)
                    for name in names:
                        if name.endswith("/") or name.endswith("\\"):
                            continue
                        clean_parts = [p for p in name.replace("\\", "/").split("/") if p not in ("", ".")]
                        if ".." in clean_parts:
                            raise ValueError(f"Sécurité : Détection de Path Traversal (Zip-Slip) dans l'archive '{path.name}' : {name}")

                        safe_rel = Path(*clean_parts)
                        dest_file = (cbz_extract_dir / safe_rel).resolve()
                        if not dest_file.is_relative_to(resolved_work_dir):
                            raise ValueError(f"Sécurité : Détection d'évasion de répertoire (Zip-Slip) : {name}")

                        dest_file.parent.mkdir(parents=True, exist_ok=True)
                        with z.open(name) as src, open(dest_file, "wb") as dst:
                            shutil.copyfileobj(src, dst)

                        is_img = dest_file.suffix.lower() in IMAGE_EXTENSIONS
                        items.append(ArchiveItem(
                            relative_name=name,
                            is_image=is_img,
                            source_path=dest_file,
                        ))
            except zipfile.BadZipFile as e:
                raise ValueError(f"L'archive '{path.name}' est corrompue ou n'est pas un fichier ZIP/CBZ valide.") from e

            return fmt, items

        if fmt == "rar":
            # Extract RAR using unrar utility to temporary directory
            rar_extract_dir = work_dir / "rar_extracted"
            rar_extract_dir.mkdir(parents=True, exist_ok=True)
            resolved_rar_dir = rar_extract_dir.resolve()
            res = subprocess.run(
                ["unrar", "x", "-y", "-inul", str(path), str(rar_extract_dir)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            if res.returncode != 0:
                # Try fallback 7z if unrar had issues
                res7 = subprocess.run(
                    ["7z", "x", "-y", f"-o{rar_extract_dir}", str(path)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                if res7.returncode != 0:
                    raise ValueError(f"Échec de l'extraction de l'archive RAR '{path.name}' (fichier possiblement corrompu ou protégé par mot de passe).")

            for root, _, files in os.walk(rar_extract_dir):
                rel_dir = Path(root).relative_to(rar_extract_dir)
                for f in sorted(files, key=natural_sort_key):
                    file_path = (Path(root) / f).resolve()
                    if not file_path.is_relative_to(resolved_rar_dir):
                        raise ValueError(f"Sécurité : Détection de Path Traversal dans l'archive RAR : {file_path}")
                    rel_name = str((rel_dir / f).as_posix())
                    is_img = file_path.suffix.lower() in IMAGE_EXTENSIONS
                    items.append(ArchiveItem(
                        relative_name=rel_name,
                        is_image=is_img,
                        source_path=file_path,
                    ))
            return fmt, items

        raise ValueError(f"Format non supporté : {fmt}")

    @staticmethod
    def pack(
        fmt: str,
        input_path: Path,
        output_path: Path,
        items: List[ArchiveItem],
        rendered_images: Dict[str, Image.Image],
    ) -> Path:
        """Packs the items into the exact target format, preserving non-image files."""
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if fmt == "image":
            img = rendered_images.get(items[0].relative_name) or items[0].get_image()
            ArchiveHandler._save_image(img, output_path)
            return output_path

        if fmt == "folder":
            output_path.mkdir(parents=True, exist_ok=True)
            for item in items:
                dest_file = output_path / item.relative_name
                dest_file.parent.mkdir(parents=True, exist_ok=True)
                if item.relative_name in rendered_images:
                    ArchiveHandler._save_image(rendered_images[item.relative_name], dest_file)
                else:
                    if item.source_path:
                        shutil.copy2(item.source_path, dest_file)
                    elif item.raw_bytes:
                        dest_file.write_bytes(item.raw_bytes)
            return output_path

        if fmt == "cbz":
            sorted_items = sorted(items, key=lambda it: natural_sort_key(it.relative_name))
            with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zout:
                for item in sorted_items:
                    comp_type = zipfile.ZIP_STORED if item.is_image else zipfile.ZIP_DEFLATED
                    if item.relative_name in rendered_images:
                        buf = io.BytesIO()
                        ArchiveHandler._save_image(rendered_images[item.relative_name], buf, suffix=Path(item.relative_name).suffix)
                        zout.writestr(item.relative_name, buf.getvalue(), compress_type=comp_type)
                    else:
                        if item.raw_bytes is not None:
                            zout.writestr(item.relative_name, item.raw_bytes, compress_type=comp_type)
                        elif item.source_path is not None:
                            zout.write(item.source_path, arcname=item.relative_name, compress_type=comp_type)
            return output_path

        if fmt == "rar":
            # Check if native 'rar' binary is available
            has_rar = shutil.which("rar") is not None
            if has_rar:
                # Create RAR with rar tool
                temp_folder = output_path.parent / f"_temp_rar_{os.getpid()}"
                temp_folder.mkdir(parents=True, exist_ok=True)
                try:
                    for item in items:
                        dest_file = temp_folder / item.relative_name
                        dest_file.parent.mkdir(parents=True, exist_ok=True)
                        if item.relative_name in rendered_images:
                            ArchiveHandler._save_image(rendered_images[item.relative_name], dest_file)
                        elif item.source_path:
                            shutil.copy2(item.source_path, dest_file)
                        elif item.raw_bytes:
                            dest_file.write_bytes(item.raw_bytes)
                    subprocess.run(
                        ["rar", "a", "-r", "-inul", str(output_path), "."],
                        cwd=temp_folder,
                        check=True,
                    )
                finally:
                    shutil.rmtree(temp_folder, ignore_errors=True)
                return output_path
            else:
                # Standard comic archive fallback: Comic readers open CBZ/CBR zip containers
                # Output standard zip-based container (or .cbz) so it's 100% readable everywhere
                with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zout:
                    for item in items:
                        if item.relative_name in rendered_images:
                            buf = io.BytesIO()
                            ArchiveHandler._save_image(rendered_images[item.relative_name], buf, suffix=Path(item.relative_name).suffix)
                            zout.writestr(item.relative_name, buf.getvalue())
                        else:
                            if item.raw_bytes is not None:
                                zout.writestr(item.relative_name, item.raw_bytes)
                            elif item.source_path is not None:
                                zout.write(item.source_path, arcname=item.relative_name)
                return output_path

        raise ValueError(f"Format inconnu pour l'export : {fmt}")

    @staticmethod
    def _save_image(img: Any, dest: Any, suffix: str = ".jpg"):
        if isinstance(dest, Path):
            suffix = dest.suffix.lower()
        suffix = suffix.lower()
        if isinstance(img, Path):
            if isinstance(dest, Path) and img.suffix.lower() == suffix:
                shutil.copy2(img, dest)
                return
            with Image.open(img) as opened:
                rgb = opened.convert("RGB")
                if suffix == ".png":
                    rgb.save(dest, format="PNG")
                elif suffix == ".webp":
                    rgb.save(dest, format="WEBP", quality=94)
                else:
                    rgb.save(dest, format="JPEG", quality=93)
            return
        img = img.convert("RGB")
        if suffix == ".png":
            img.save(dest, format="PNG")
        elif suffix == ".webp":
            img.save(dest, format="WEBP", quality=94)
        else:
            img.save(dest, format="JPEG", quality=93)
