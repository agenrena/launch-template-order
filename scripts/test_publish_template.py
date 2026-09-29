"""Release/archive behavior using disposable Git repositories and a fake S3."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile

from botocore.exceptions import ClientError
from publish_template import build, json_bytes, merge_catalog, publish, version


def aws_error(code):
    return ClientError({'Error': {'Code': code}}, 'PutObject')


class FakeS3:
    def __init__(self):
        self.objects = {'catalog.json': b'[]'}
        self.writes = []
        self.race = None
        self.fail_zip = False
        self.conflict_once = False

    def get_object(self, *, Bucket, Key):
        if Key not in self.objects:
            raise aws_error('NoSuchKey')
        data = self.objects[Key]
        return {'Body': io.BytesIO(data), 'ETag': hashlib.sha256(data).hexdigest()}

    def put_object(self, *, Bucket, Key, Body, **kwargs):
        self.writes.append(Key)
        if Key.endswith('.zip') and self.fail_zip:
            raise aws_error('AccessDenied')
        if self.conflict_once:
            self.conflict_once = False
            raise aws_error('ConditionalRequestConflict')
        if Key == 'catalog.json' and self.race:
            race, self.race = self.race, None
            race(self)
        if kwargs.get('IfNoneMatch') == '*' and Key in self.objects:
            raise aws_error('PreconditionFailed')
        if 'IfMatch' in kwargs and hashlib.sha256(self.objects[Key]).hexdigest() != kwargs['IfMatch']:
            raise aws_error('PreconditionFailed')
        self.objects[Key] = Body


def entry(version='0.1.0', content=b'zip'):
    return dict(id='business_core', name='Business Core', version=version,
                archive_key=f'templates/business_core/{version}/source.zip',
                sha256=hashlib.sha256(content).hexdigest(), size_bytes=len(content),
                source_commit='a' * 40, source_repository='https://github.com/example/business-core')


class PublishTests(unittest.TestCase):
    def test_artifacts_precede_catalog_and_retry_is_idempotent(self):
        s3 = FakeS3()
        publish(s3, 'bucket', 'catalog.json', b'zip', entry())
        self.assertEqual(s3.writes, ['templates/business_core/0.1.0/source.zip',
                                    'templates/business_core/0.1.0/manifest.json', 'catalog.json'])
        original = dict(s3.objects)
        publish(s3, 'bucket', 'catalog.json', b'zip', entry())
        self.assertEqual(original, s3.objects)

    def test_same_version_cannot_be_overwritten(self):
        s3 = FakeS3()
        publish(s3, 'bucket', 'catalog.json', b'zip', entry())
        original = dict(s3.objects)
        with self.assertRaisesRegex(ValueError, 'different content'):
            publish(s3, 'bucket', 'catalog.json', b'new', entry(content=b'new'))
        self.assertEqual(original, s3.objects)

    def test_failed_zip_upload_does_not_touch_catalog(self):
        s3 = FakeS3()
        s3.fail_zip = True
        with self.assertRaises(ClientError):
            publish(s3, 'bucket', 'catalog.json', b'zip', entry())
        self.assertEqual(s3.objects, {'catalog.json': b'[]'})

    def test_checksum_mismatch_does_not_write(self):
        s3 = FakeS3()
        with self.assertRaisesRegex(ValueError, 'checksum'):
            publish(s3, 'bucket', 'catalog.json', b'other', entry())
        self.assertEqual(s3.writes, [])

    def test_concurrent_other_template_publication_is_preserved(self):
        s3 = FakeS3()
        other = dict(id='booking', version='1.0.0', name='Booking')
        s3.race = lambda store: store.objects.update({'catalog.json': json_bytes([other])})
        publish(s3, 'bucket', 'catalog.json', b'zip', entry())
        self.assertEqual(json.loads(s3.objects['catalog.json']), [other, entry()])
        self.assertEqual(s3.writes.count('catalog.json'), 2)

    def test_older_release_cannot_replace_newer_catalog_version(self):
        s3 = FakeS3()
        publish(s3, 'bucket', 'catalog.json', b'zip', entry('0.2.0'))
        publish(s3, 'bucket', 'catalog.json', b'zip', entry('0.1.0'))
        self.assertEqual(json.loads(s3.objects['catalog.json'])[0]['version'], '0.2.0')
        self.assertIn('templates/business_core/0.1.0/manifest.json', s3.objects)

    def test_bad_catalog_is_not_overwritten(self):
        for bad in [{}, [{'id': 'booking'}, {'id': 'booking'}]]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                merge_catalog(bad, entry())

    def test_existing_version_metadata_cannot_change(self):
        with self.assertRaisesRegex(ValueError, 'different metadata'):
            merge_catalog([dict(entry(), name='Old name')], entry())

    def test_conditional_upload_conflict_retries(self):
        s3 = FakeS3()
        s3.conflict_once = True
        publish(s3, 'bucket', 'catalog.json', b'zip', entry())
        self.assertEqual(json.loads(s3.objects['catalog.json']), [entry()])

    def test_release_must_be_stable_semver(self):
        self.assertEqual(version('v1.2.3'), '1.2.3')
        for value in ['main', 'v1.2', '1.2.3-rc.1', '../1.2.3', '01.2.3']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                version(value)


class PackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.git('init', '--quiet')
        self.git('config', 'user.name', 'Template tests')
        self.git('config', 'user.email', 'tests@example.invalid')
        files = {'runtime.json': json.dumps({'version': 1, 'backend': 'django', 'frontend': 'static', 'mcp': True}),
                 'template.json': json.dumps({'id': 'business_core', 'name': 'Core', 'category': 'Base',
                    'summary': 'Summary', 'description': 'Description', 'features': ['Team'], 'scope_note': 'Scope'}),
                 'backend/manage.py': '# manage', 'backend/Dockerfile': 'FROM python:3.13-slim',
                 'frontend/Dockerfile': 'FROM nginx:alpine', 'mcp/Dockerfile': 'FROM node:22-slim',
                 '.env': 'secret=not-for-release', 'backend/.env.production': 'secret=not-for-release',
                 '.env.example': 'SECRET_KEY=', '.secrets/arbitrary.json': '{}',
                 'credentials/service-account.json': '{}', 'node_modules/private.txt': 'x',
                 '.runtime/data.json': '{}', '.github/workflows/release.yml': '# publisher',
                 'README.md': 'committed content'}
        for name, content in files.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        self.commit()

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args], stderr=subprocess.DEVNULL)

    def commit(self):
        self.git('add', '.')
        self.git('commit', '--quiet', '-m', 'fixture')

    def build(self):
        return build(self.root, 'HEAD', 'v0.1.0', 'example/business-core')

    def test_archive_uses_commit_excludes_secrets_and_is_repeatable(self):
        (self.root/'README.md').write_text('uncommitted change')
        (self.root/'untracked.txt').write_text('not in commit')
        content, manifest = self.build()
        self.assertEqual((content, manifest), self.build())
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            self.assertEqual(archive.read('README.md'), b'committed content')
            self.assertIn('.env.example', archive.namelist())
            for name in ['.env', 'backend/.env.production', '.runtime/data.json',
                         'credentials/service-account.json', '.secrets/arbitrary.json',
                         'node_modules/private.txt', '.github/workflows/release.yml', 'untracked.txt']:
                self.assertNotIn(name, archive.namelist())
        self.assertEqual(manifest['sha256'], hashlib.sha256(content).hexdigest())
        self.assertEqual(manifest['source_commit'], self.git('rev-parse', 'HEAD').decode().strip())

    def test_symlink_is_rejected(self):
        (self.root/'link').symlink_to('README.md')
        self.commit()
        with self.assertRaisesRegex(ValueError, 'symbolic links'):
            self.build()

    def test_tracked_private_key_is_rejected_even_under_unknown_name(self):
        (self.root/'unexpected.txt').write_text('-----BEGIN PRIVATE KEY-----\nfixture\n')
        self.commit()
        with self.assertRaisesRegex(ValueError, 'Private key'):
            self.build()

    def test_missing_runtime_files_are_rejected(self):
        (self.root/'backend/Dockerfile').unlink()
        self.commit()
        with self.assertRaisesRegex(ValueError, 'required Runtime files'):
            self.build()


if __name__ == '__main__':
    unittest.main()
