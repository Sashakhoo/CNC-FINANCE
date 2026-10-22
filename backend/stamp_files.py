"""
File storage for the Digital Stamp module (original PDFs, stamped PDFs,
stamp images, signatures).

Everything goes through the small `Storage` interface below, so an
S3-compatible backend can be added later by writing one more class and
switching `get_storage()` — nothing else in the app touches the filesystem.

Files are stored under random server-generated keys. A user's filename is
never used as a path, and keys are validated before any disk access, so a
request can't traverse out of the storage directory.
"""
import os
import re
import secrets

import storage as db_storage

_KEY_RE = re.compile(r"^[a-f0-9]{32}\.(pdf|png)$")


class StorageError(Exception):
    pass


class Storage:
    """Interface: put bytes, get bytes back by key."""

    def put(self, data: bytes, ext: str) -> str:
        raise NotImplementedError

    def get(self, key: str) -> bytes:
        raise NotImplementedError

    def exists(self, key: str) -> bool:
        raise NotImplementedError


class LocalStorage(Storage):
    def __init__(self, root: str):
        self.root = os.path.abspath(root)
        os.makedirs(self.root, exist_ok=True)

    def _path(self, key: str) -> str:
        if not key or not _KEY_RE.match(key):
            raise StorageError("invalid storage key")
        path = os.path.abspath(os.path.join(self.root, key[:2], key))
        if os.path.commonpath([path, self.root]) != self.root:
            raise StorageError("invalid storage key")
        return path

    def put(self, data: bytes, ext: str) -> str:
        if ext not in ("pdf", "png"):
            raise StorageError("unsupported file type")
        key = f"{secrets.token_hex(16)}.{ext}"
        path = self._path(key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".part"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
        return key

    def get(self, key: str) -> bytes:
        path = self._path(key)
        if not os.path.isfile(path):
            raise StorageError("file not found")
        with open(path, "rb") as f:
            return f.read()

    def exists(self, key: str) -> bool:
        try:
            return os.path.isfile(self._path(key))
        except StorageError:
            return False


_storage = None


def storage_root() -> str:
    """Defaults to a folder beside the database, so on Railway it lives on
    the same persistent /data volume as cnc.db and survives deploys."""
    explicit = os.environ.get("STAMP_STORAGE_PATH", "").strip()
    if explicit:
        return explicit
    return os.path.join(os.path.dirname(os.path.abspath(db_storage.DB_PATH)), "stamp_files")


def get_storage() -> Storage:
    global _storage
    if _storage is None:
        _storage = LocalStorage(storage_root())
    return _storage


def reset_storage():
    """Tests point DB_PATH somewhere new and need a fresh instance."""
    global _storage
    _storage = None
