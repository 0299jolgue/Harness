"""File operations confined to the project's projetos/ directory."""
from pathlib import Path
import os
import shutil

MAX_FILE_BYTES = 150 * 1024


def resolve(root: Path, relative: str = ".") -> Path:
    root = root.resolve()
    candidate = (root / relative).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError("O caminho tem de ficar dentro de projetos/.")
    if candidate.is_symlink():
        raise ValueError("Atalhos simbólicos não são permitidos.")
    return candidate


def list_files(root: Path, path: str = "."):
    folder = resolve(root, path)
    if not folder.is_dir(): raise ValueError("Pasta não encontrada.")
    rows = []
    for item in sorted(folder.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        if item.is_symlink(): continue
        rows.append({"name": item.name, "path": item.relative_to(root).as_posix(),
                     "type": "directory" if item.is_dir() else "file",
                     "size": item.stat().st_size if item.is_file() else None})
    return rows


def read_file(root: Path, path: str):
    file = resolve(root, path)
    if not file.is_file(): raise ValueError("Ficheiro não encontrado.")
    if file.stat().st_size > MAX_FILE_BYTES: raise ValueError("Ficheiro excede o limite de 150 KB.")
    return file.read_text(encoding="utf-8")


def write_file(root: Path, path: str, content: str, *, create_only=False):
    file = resolve(root, path)
    if len(content.encode("utf-8")) > MAX_FILE_BYTES: raise ValueError("Conteúdo excede 150 KB.")
    if create_only and file.exists(): raise ValueError("O ficheiro já existe.")
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(content, encoding="utf-8")
    return {"path": file.relative_to(root).as_posix(), "bytes": file.stat().st_size}


def edit_file(root: Path, path: str, old_text: str, new_text: str):
    content = read_file(root, path)
    if not old_text or old_text not in content: raise ValueError("Texto a substituir não encontrado.")
    if content.count(old_text) != 1: raise ValueError("Texto aparece mais de uma vez; torna a edição específica.")
    return write_file(root, path, content.replace(old_text, new_text, 1))


def search_files(root: Path, query: str, path: str = "."):
    base = resolve(root, path)
    found = []
    for file in base.rglob("*"):
        if file.is_symlink() or not file.is_file() or file.stat().st_size > MAX_FILE_BYTES: continue
        try: lines = file.read_text(encoding="utf-8").splitlines()
        except (UnicodeError, OSError): continue
        for number, line in enumerate(lines, 1):
            if query.casefold() in line.casefold():
                found.append({"path": file.relative_to(root).as_posix(), "line": number, "text": line[:500]})
                if len(found) >= 100: return found
    return found


def create_folder(root: Path, path: str):
    folder = resolve(root, path)
    folder.mkdir(parents=True, exist_ok=True)
    return {"path": folder.relative_to(root).as_posix()}


def move_file(root: Path, source: str, destination: str):
    src, dst = resolve(root, source), resolve(root, destination)
    if not src.exists(): raise ValueError("Origem não encontrada.")
    if dst.exists(): raise ValueError("Destino já existe.")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    return {"from": src.relative_to(root).as_posix(), "to": dst.relative_to(root).as_posix()}


def delete_file(root: Path, path: str):
    target = resolve(root, path)
    if not target.exists(): raise ValueError("Caminho não encontrado.")
    if target.is_dir(): raise ValueError("O agente só pode apagar ficheiros, não pastas.")
    target.unlink()
    return {"deleted": target.relative_to(root).as_posix()}
