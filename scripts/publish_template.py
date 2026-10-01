"""Build a committed template release and publish immutable artifacts to S3."""
import argparse
import base64
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import zipfile

from botocore.exceptions import ClientError

MAX_ZIP = 10 * 1024 * 1024
MAX_EXPANDED = 60 * 1024 * 1024
MAX_CATALOG = 1024 * 1024
SEMVER = re.compile(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)")
ID = re.compile(r"[a-z][a-z0-9_-]{0,63}")
DENIED = {".git", ".github", ".secrets", ".runtime", ".venv", "venv", "node_modules",
          "dist", "__pycache__", ".pytest_cache", ".ruff_cache", "coverage", "release-dist"}
PUBLISH_FILES = {"scripts/publish_template.py", "scripts/test_publish_template.py",
                 "scripts/requirements-publish.txt"}


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def version(value):
    value = value.removeprefix("v")
    if not SEMVER.fullmatch(value):
        raise ValueError("Use a stable version such as v0.1.0; prereleases are not published.")
    return value


def excluded(name):
    p = PurePosixPath(name)
    return (bool(set(p.parts) & DENIED) or name in PUBLISH_FILES
            or any(part.startswith('.env') and part != '.env.example' for part in p.parts)
            or any(part.startswith('.preview-') for part in p.parts)
            or p.name == '.DS_Store' or p.name == 'compose.override.yaml'
            or p.suffix in {'.pem', '.key', '.p12', '.pfx', '.pyc', '.sqlite3', '.db', '.dump', '.log'}
            or 'service-account' in p.name.lower() or 'serviceaccount' in p.name.lower()
            or 'firebase-adminsdk' in p.name.lower())


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args])


def build(root, ref, release_version, repository):
    release_version = version(release_version)
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
        raise ValueError('Repository must be OWNER/REPO.')
    commit = git(root, 'rev-parse', '--verify', '--end-of-options', ref + '^{commit}').decode().strip()
    metadata = json.loads(git(root, 'show', commit + ':template.json'))
    if not isinstance(metadata, dict) or not ID.fullmatch(metadata.get('id', '')):
        raise ValueError('Invalid template ID.')
    for key in ['name', 'category', 'summary', 'description', 'scope_note']:
        if not isinstance(metadata.get(key), str) or not metadata[key].strip():
            raise ValueError('Missing template description field: ' + key)
    if not isinstance(metadata.get('features'), list) or not all(isinstance(s, str) for s in metadata['features']):
        raise ValueError('features must be a list of strings.')
    files = {}
    total = 0
    with zipfile.ZipFile(io.BytesIO(git(root, 'archive', '--format=zip', commit))) as source:
        for item in source.infolist():
            name = item.filename
            if item.is_dir() or excluded(name):
                continue
            p = PurePosixPath(name)
            if p.is_absolute() or '..' in p.parts or '\\' in name:
                raise ValueError('Unsafe archive path.')
            mode = item.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise ValueError('Template archives cannot contain symbolic links: ' + name)
            data = source.read(item)
            if b'-----BEGIN PRIVATE KEY-----' in data or b'-----BEGIN RSA PRIVATE KEY-----' in data:
                raise ValueError('Private key material found in tracked source: ' + name)
            total += len(data)
            if total > MAX_EXPANDED or len(files) >= 5000:
                raise ValueError('Template exceeds Runtime archive limits.')
            files[name] = (data, 0o755 if mode & 0o111 else 0o644)
    required = ['runtime.json', 'backend/manage.py', 'backend/Dockerfile', 'frontend/Dockerfile']
    if any(name not in files for name in required):
        raise ValueError('Missing required Runtime files.')
    contract = json.loads(files['runtime.json'][0])
    if (contract.get('version') != 1 or contract.get('backend') != 'django'
            or contract.get('frontend') != 'static'):
        raise ValueError('Unsupported Runtime contract.')
    if contract.get('mcp') and 'mcp/Dockerfile' not in files:
        raise ValueError('Missing MCP Dockerfile.')
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, (data, mode) in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=(2000, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | mode) << 16
            archive.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    content = output.getvalue()
    if len(content) > MAX_ZIP:
        raise ValueError('Template ZIP exceeds Runtime 10 MiB limit.')
    prefix = f"templates/{metadata['id']}/{release_version}"
    entry = {key: metadata[key] for key in ['id', 'name', 'category', 'summary', 'description', 'features', 'scope_note']}
    entry.update(version=release_version, archive_key=prefix + '/source.zip',
                 sha256=hashlib.sha256(content).hexdigest(), size_bytes=len(content),
                 source_commit=commit, source_repository='https://github.com/' + repository)
    return content, entry


def read_object(s3, bucket, key, limit):
    response = s3.get_object(Bucket=bucket, Key=key)
    stream = response['Body']
    try:
        content = stream.read(limit + 1)
    finally:
        stream.close()
    if len(content) > limit:
        raise ValueError('S3 object exceeds the allowed size: ' + key)
    return content, response['ETag']


def conflict(error):
    return error.response.get('Error', {}).get('Code') in {'PreconditionFailed', 'ConditionalRequestConflict', '412', '409'}


def immutable_put(s3, bucket, key, content, content_type):
    for _ in range(5):
        try:
            s3.put_object(Bucket=bucket, Key=key, Body=content, ContentType=content_type,
                          IfNoneMatch='*', ChecksumSHA256=base64.b64encode(hashlib.sha256(content).digest()).decode())
            return
        except ClientError as exc:
            if not conflict(exc):
                raise
            # A 409 can occur without an existing object; retry that conditional write.
            if exc.response['Error']['Code'] in {'ConditionalRequestConflict', '409'}:
                continue
            existing, _ = read_object(s3, bucket, key, max(len(content), 1))
            if existing != content:
                raise ValueError('Version already exists with different content; publish a new version.') from exc
            return
    raise ValueError('Repeated concurrent artifact writes; retry the workflow.')


def merge_catalog(catalog, entry):
    if not isinstance(catalog, list):
        raise ValueError('catalog.json must be a JSON array.')
    seen = set()
    current = None
    for item in catalog:
        if not isinstance(item, dict) or not isinstance(item.get('id'), str) or item['id'] in seen:
            raise ValueError('Invalid or duplicate catalog entry.')
        seen.add(item['id'])
        if item['id'] == entry['id']:
            current = item
    if current:
        old = tuple(map(int, version(current['version']).split('.')))
        new = tuple(map(int, version(entry['version']).split('.')))
        if old > new:
            return catalog  # A delayed old workflow must not replace the latest release.
        if old == new:
            if current != entry:
                raise ValueError('Catalog version already exists with different metadata.')
            return catalog
    return sorted([item for item in catalog if item['id'] != entry['id']] + [entry], key=lambda item: item['id'])


def publish(s3, bucket, catalog_key, content, entry):
    if entry['sha256'] != hashlib.sha256(content).hexdigest() or entry['size_bytes'] != len(content):
        raise ValueError('Artifact checksum/size does not match the release manifest.')
    expected_key = f"templates/{entry['id']}/{version(entry['version'])}/source.zip"
    if not ID.fullmatch(entry['id']) or entry['archive_key'] != expected_key:
        raise ValueError('Invalid release object key.')
    if catalog_key.startswith('templates/') or catalog_key.endswith('/'):
        raise ValueError('Keep the catalog outside immutable template prefixes.')
    # Objects and immutable release metadata must exist before they become discoverable.
    immutable_put(s3, bucket, expected_key, content, 'application/zip')
    immutable_put(s3, bucket, expected_key.removesuffix('source.zip') + 'manifest.json', json_bytes(entry), 'application/json')
    for _ in range(8):
        original, etag = read_object(s3, bucket, catalog_key, MAX_CATALOG)
        catalog = json.loads(original)
        updated = merge_catalog(catalog, entry)
        if updated == catalog:
            return
        payload = json_bytes(updated)
        if len(payload) > MAX_CATALOG:
            raise ValueError('Catalog exceeds 1 MiB.')
        try:
            s3.put_object(Bucket=bucket, Key=catalog_key, Body=payload,
                          ContentType='application/json', CacheControl='max-age=60', IfMatch=etag)
            return
        except ClientError as exc:
            if not conflict(exc):
                raise
    raise ValueError('Catalog changed repeatedly; retry the workflow. Uploaded artifacts are safe to reuse.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    pack = sub.add_parser('pack')
    pack.add_argument('--ref', default='HEAD')
    pack.add_argument('--version', required=True)
    pack.add_argument('--repository', required=True)
    pack.add_argument('--output', type=Path, default=Path('release-dist'))
    upload = sub.add_parser('publish')
    upload.add_argument('--artifact-dir', type=Path, default=Path('release-dist'))
    upload.add_argument('--bucket', required=True)
    upload.add_argument('--catalog-key', default='catalog.json')
    upload.add_argument('--region', default='us-east-1')
    args = parser.parse_args()
    try:
        if args.command == 'pack':
            content, entry = build(Path(__file__).resolve().parents[1], args.ref, args.version, args.repository)
            args.output.mkdir(parents=True, exist_ok=True)
            (args.output / 'source.zip').write_bytes(content)
            (args.output / 'manifest.json').write_bytes(json_bytes(entry))
            print(f"Packed {entry['id']} {entry['version']} at {entry['source_commit']} ({len(content)} bytes).")
        else:
            import boto3
            from botocore.config import Config
            s3 = boto3.client('s3', region_name=args.region,
                             config=Config(connect_timeout=5, read_timeout=30, retries={'mode': 'standard', 'max_attempts': 3}))
            entry = json.loads((args.artifact_dir / 'manifest.json').read_text())
            publish(s3, args.bucket, args.catalog_key, (args.artifact_dir / 'source.zip').read_bytes(), entry)
            print(f"Published {entry['id']} {entry['version']}; catalog is current.")
    except ClientError as exc:
        raise SystemExit('S3 publish failed: ' + exc.response.get('Error', {}).get('Code', 'Unknown')) from None
    except (ValueError, OSError) as exc:
        raise SystemExit(str(exc)) from None


if __name__ == '__main__':
    main()
