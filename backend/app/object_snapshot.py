"""Stream database-referenced S3 objects to and from a checksummed ZIP archive."""
from argparse import ArgumentParser
from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
from zipfile import ZipFile

from minio.error import S3Error

from .database import SessionLocal
from .verify_restore import object_digest, object_references, object_stores


MAX_INVENTORY_BYTES = 64 * 1024 * 1024


def _copy(source, target=None) -> tuple[int, str]:
    size = 0
    digest = sha256()
    while chunk := source.read(1024 * 1024):
        size += len(chunk)
        digest.update(chunk)
        if target is not None:
            target.write(chunk)
    return size, digest.hexdigest()


def backup(path: Path) -> int:
    stores = object_stores()
    inventory = []
    with SessionLocal() as db, ZipFile(path, "x", allowZip64=True) as archive:
        for index, reference in enumerate(object_references(db, attachment_bucket=stores["attachments"].bucket)):
            entry = f"objects/{index}"
            reader = stores[reference.kind].open(reference.key)
            try:
                with closing(reader), archive.open(entry, "w", force_zip64=True) as dest:
                    size, digest = _copy(reader, dest)
            finally:
                reader.release_conn()
            if ((reference.size is not None and size != reference.size)
                    or (reference.digest is not None and digest != reference.digest)):
                raise ValueError("An object is inconsistent with its database record")
            inventory.append({"kind": reference.kind, "key": reference.key, "size": size, "sha256": digest})
        manifest = json.dumps(inventory, ensure_ascii=False).encode("utf-8")
        if len(manifest) > MAX_INVENTORY_BYTES:
            raise ValueError("Object inventory exceeds the supported size")
        archive.writestr("manifest.json", manifest)
    return len(inventory)


def restore(path: Path, *, check_only: bool = False) -> int:
    stores = {} if check_only else object_stores()
    with ZipFile(path, "r", allowZip64=True) as archive:
        if archive.getinfo("manifest.json").file_size > MAX_INVENTORY_BYTES:
            raise ValueError("Object inventory exceeds the supported size")
        inventory = json.loads(archive.read("manifest.json"))
        if not isinstance(inventory, list):
            raise ValueError("Object inventory must be a list")
        seen = set()
        for index, obj in enumerate(inventory):
            if (not isinstance(obj, dict) or obj.get("kind") not in {"attachments", "knowledge_base"}
                    or not isinstance(obj.get("key"), str)):
                raise ValueError("An object inventory entry is invalid")
            identity = (obj["kind"], obj["key"])
            if identity in seen:
                raise ValueError("Object inventory contains duplicate keys")
            seen.add(identity)
            with archive.open(f"objects/{index}") as source:
                if _copy(source) != (obj.get("size"), obj.get("sha256")):
                    raise ValueError("An archived object failed its integrity check")

        if check_only:
            return len(inventory)
        for index, obj in enumerate(inventory):
            store = stores[obj["kind"]]
            try:
                existing_size = store.size(obj["key"])
            except S3Error as exc:
                if exc.code not in {"NoSuchKey", "NoSuchBucket", "NotFound"}:
                    raise
            else:
                if existing_size != obj["size"] or object_digest(store, obj["key"]) != obj["sha256"]:
                    raise ValueError("Target storage contains a different object with the same key")
                continue
            with archive.open(f"objects/{index}") as source:
                store.put(obj["key"], source, obj["size"], "application/octet-stream")
    return len(inventory)


def main() -> None:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("backup", "check", "restore"))
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    try:
        count = backup(args.path) if args.action == "backup" else restore(args.path, check_only=args.action == "check")
    except Exception as exc:
        raise SystemExit(f"Object snapshot {args.action} failed ({type(exc).__name__})") from None
    print(f"Object snapshot {args.action}: {count} verified objects")


if __name__ == "__main__":
    main()
