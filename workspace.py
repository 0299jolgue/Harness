"""Streaming file operations confined to projetos/."""
from pathlib import Path
import shutil
import zipfile

MAX_FILE_BYTES = 10 * 1024**3
MAX_AGENT_READ = 8 * 1024
MAX_AGENT_WRITE = 8 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 2000


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
        if item.is_symlink() or item.name.startswith(".upload-"): continue
        rows.append({"name": item.name, "path": item.relative_to(root).as_posix(),
                     "type": "directory" if item.is_dir() else "file",
                     "size": item.stat().st_size if item.is_file() else None})
    return rows


def file_info(root: Path, path: str):
    file = resolve(root, path)
    if not file.is_file(): raise ValueError("Ficheiro não encontrado.")
    return {"path": file.relative_to(root).as_posix(), "size": file.stat().st_size,
            "suffix": file.suffix.lower(), "is_text_candidate": file.suffix.lower() not in
            {".zip", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".pdf", ".mp4", ".mp3", ".gguf", ".bin"}}


def read_file(root: Path, path: str, offset: int = 0, limit: int = MAX_AGENT_READ):
    """Read a bounded UTF-8 slice from a potentially very large text file."""
    file = resolve(root, path)
    if not file.is_file(): raise ValueError("Ficheiro não encontrado.")
    size = file.stat().st_size
    if size > MAX_FILE_BYTES: raise ValueError("Ficheiro excede o limite de 10 GB.")
    if offset < 0 or offset > size: raise ValueError("Offset inválido.")
    limit = max(1, min(int(limit), MAX_AGENT_READ))
    with file.open("rb") as stream:
        stream.seek(offset)
        data = stream.read(limit)
    try: content = data.decode("utf-8")
    except UnicodeDecodeError: raise ValueError("Este ficheiro não é texto UTF-8. Usa a ferramenta apropriada, como list_archive para ZIP.") from None
    end = offset + len(data)
    return {"path": file.relative_to(root).as_posix(), "content": content,
            "offset": offset, "next_offset": end if end < size else None,
            "total_bytes": size, "truncated": end < size}


def read_pdf(root: Path, path: str, page: int = 1, pages: int = 1):
    """Extract text from a small page window of a PDF without loading all text into the prompt."""
    file = resolve(root, path)
    if not file.is_file() or file.suffix.lower() != ".pdf": raise ValueError("Indica um ficheiro PDF.")
    if file.stat().st_size > MAX_FILE_BYTES: raise ValueError("PDF excede o limite de 10 GB.")
    try:
        from pypdf import PdfReader
    except ImportError: raise ValueError("Leitura PDF indisponível: instala a dependência pypdf no servidor.") from None
    reader = PdfReader(str(file), strict=False)
    if reader.is_encrypted: raise ValueError("O PDF está protegido por palavra-passe.")
    start = max(1, int(page)); count = max(1, min(int(pages), 3))
    pieces = []
    for index in range(start - 1, min(len(reader.pages), start - 1 + count)):
        text = reader.pages[index].extract_text() or ""
        pieces.append(f"[Página {index + 1}]\n{text}")
    result = "\n\n".join(pieces)
    cap = MAX_AGENT_READ
    return {"path": file.relative_to(root).as_posix(), "page_count": len(reader.pages),
            "pages_read": min(count, max(0, len(reader.pages) - start + 1)),
            "text": result[:cap], "truncated": len(result) > cap,
            "next_page": start + count if start + count <= len(reader.pages) else None}


def write_file(root: Path, path: str, content: str, *, create_only=False):
    file = resolve(root, path)
    data = content.encode("utf-8")
    if len(data) > MAX_AGENT_WRITE: raise ValueError("Criação/edição pelo agente limitada a 8 MB. Usa upload para ficheiros maiores.")
    if create_only and file.exists(): raise ValueError("O ficheiro já existe.")
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_bytes(data)
    return {"path": file.relative_to(root).as_posix(), "bytes": file.stat().st_size}


def edit_file(root: Path, path: str, old_text: str, new_text: str):
    file = resolve(root, path)
    if not file.is_file(): raise ValueError("Ficheiro não encontrado.")
    if file.stat().st_size > 64 * 1024 * 1024:
        raise ValueError("Edição automática limitada a ficheiros até 64 MB; ficheiros maiores podem ser lidos por blocos.")
    content = file.read_text(encoding="utf-8")
    if not old_text or content.count(old_text) != 1: raise ValueError("O texto deve aparecer exatamente uma vez no ficheiro.")
    return write_file(root, path, content.replace(old_text, new_text, 1))


def search_files(root: Path, query: str, path: str = "."):
    base = resolve(root, path)
    found = []
    ignored = {".zip", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".pdf", ".mp4", ".mp3", ".gguf", ".bin"}
    for file in base.rglob("*"):
        if file.is_symlink() or not file.is_file() or file.suffix.lower() in ignored: continue
        try:
            with file.open("r", encoding="utf-8", errors="replace") as stream:
                for number, line in enumerate(stream, 1):
                    if query.casefold() in line.casefold():
                        found.append({"path": file.relative_to(root).as_posix(), "line": number, "text": line[:500]})
                        if len(found) >= 100: return found
        except OSError: continue
    return found


def list_archive(root: Path, path: str):
    archive = resolve(root, path)
    if not archive.is_file() or archive.suffix.lower() != ".zip": raise ValueError("Indica um ficheiro .zip válido.")
    with zipfile.ZipFile(archive) as zf:
        infos = zf.infolist()
        return [{"name": i.filename, "size": i.file_size, "compressed_size": i.compress_size,
                 "is_directory": i.is_dir()} for i in infos[:MAX_ARCHIVE_ENTRIES]]


def read_archive_file(root: Path, path: str, member: str, offset: int = 0, limit: int = MAX_AGENT_READ):
    archive = resolve(root, path)
    if not archive.is_file() or archive.suffix.lower() != ".zip": raise ValueError("Indica um ficheiro .zip válido.")
    limit = max(1, min(int(limit), MAX_AGENT_READ))
    with zipfile.ZipFile(archive) as zf:
        info = zf.getinfo(member)
        if info.is_dir() or info.file_size > MAX_FILE_BYTES: raise ValueError("Entrada inválida ou acima de 10 GB.")
        if offset < 0 or offset > info.file_size: raise ValueError("Offset inválido.")
        with zf.open(info) as stream:
            remaining = offset
            while remaining:
                block = stream.read(min(1024 * 1024, remaining))
                if not block: break
                remaining -= len(block)
            data = stream.read(limit)
    try: text = data.decode("utf-8")
    except UnicodeDecodeError: raise ValueError("A entrada ZIP não é texto UTF-8.") from None
    end = offset + len(data)
    return {"member": member, "content": text, "offset": offset,
            "next_offset": end if end < info.file_size else None,
            "total_bytes": info.file_size, "truncated": end < info.file_size}


def extract_archive(root: Path, path: str, destination: str = "."):
    archive = resolve(root, path); target_root = resolve(root, destination)
    if not archive.is_file() or archive.suffix.lower() != ".zip": raise ValueError("Indica um ficheiro .zip válido.")
    total = 0; extracted = 0
    with zipfile.ZipFile(archive) as zf:
        infos = zf.infolist()
        if len(infos) > MAX_ARCHIVE_ENTRIES: raise ValueError("O ZIP tem mais de 2000 entradas.")
        total = sum(i.file_size for i in infos)
        if total > MAX_FILE_BYTES: raise ValueError("O conteúdo descomprimido ultrapassaria 10 GB.")
        for info in infos:
            relative = Path(info.filename)
            if relative.is_absolute() or ".." in relative.parts: raise ValueError("O ZIP contém um caminho inseguro.")
            out = resolve(target_root, relative.as_posix())
            if info.is_dir(): out.mkdir(parents=True, exist_ok=True); continue
            out.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, out.open("wb") as dst:
                shutil.copyfileobj(src, dst, length=1024 * 1024)
            extracted += 1
    return {"archive": archive.relative_to(root).as_posix(), "destination": target_root.relative_to(root).as_posix(), "files": extracted, "uncompressed_bytes": total}


def create_folder(root: Path, path: str):
    folder = resolve(root, path); folder.mkdir(parents=True, exist_ok=True)
    return {"path": folder.relative_to(root).as_posix()}


def move_file(root: Path, source: str, destination: str):
    src, dst = resolve(root, source), resolve(root, destination)
    if not src.exists(): raise ValueError("Origem não encontrada.")
    if dst.exists(): raise ValueError("Destino já existe.")
    dst.parent.mkdir(parents=True, exist_ok=True); shutil.move(str(src), str(dst))
    return {"from": src.relative_to(root).as_posix(), "to": dst.relative_to(root).as_posix()}


def delete_file(root: Path, path: str):
    target = resolve(root, path)
    if not target.exists(): raise ValueError("Caminho não encontrado.")
    if target.is_dir(): raise ValueError("O agente só pode apagar ficheiros, não pastas.")
    target.unlink(); return {"deleted": target.relative_to(root).as_posix()}
