import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zipfile


ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('pcm_builder',ROOT/'Src'/'prepare_pcm_repository.py')
builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root=Path(self.directory.name)
        self.source=self.root/'Src';self.source.mkdir()
        self.output=self.root/'Publish';self.output.mkdir()
        self.metadata=json.loads((ROOT/'Src'/'metadata.json').read_bytes())
        (self.source/'metadata.json').write_bytes(builder.json_bytes(self.metadata))
        (self.source/'plugin.py').write_text('print("coil")\n',encoding='utf8')
        self.archive=self.output/builder.ARCHIVE_NAME
        with zipfile.ZipFile(self.archive,'w') as archive:
            for name in ('metadata.json','plugin.py'):archive.write(self.source/name,name)

    def test_index_hashes_sizes_and_metadata(self):
        original=copy.deepcopy(self.metadata)
        repository,package=builder.prepare_repository(self.source,self.output)
        version=package['versions'][0]
        self.assertEqual(version['download_sha256'],hashlib.sha256(self.archive.read_bytes()).hexdigest())
        self.assertEqual(version['download_size'],self.archive.stat().st_size)
        with zipfile.ZipFile(self.archive) as archive:
            self.assertEqual(version['install_size'],sum(entry.file_size for entry in archive.infolist()))
            self.assertEqual(json.loads(archive.read('metadata.json')),original)
        self.assertEqual(repository['packages']['sha256'],hashlib.sha256((self.output/'packages.json').read_bytes()).hexdigest())
        self.assertEqual(repository['packages']['url'],builder.BASE_URL+'/packages.json')
        self.assertEqual(version['download_url'],builder.BASE_URL+'/'+builder.ARCHIVE_NAME)

    def test_stale_zip_is_rejected(self):
        (self.source/'plugin.py').write_text('print("updated")\n',encoding='utf8')
        with self.assertRaisesRegex(ValueError,'Run publish.bat first'):
            builder.prepare_repository(self.source,self.output)
        self.assertFalse((self.output/'repository.json').exists())

    def test_repeated_generation_is_identical(self):
        builder.prepare_repository(self.source,self.output)
        first=[(self.output/name).read_bytes() for name in ('repository.json','packages.json')]
        builder.prepare_repository(self.source,self.output)
        self.assertEqual(first,[(self.output/name).read_bytes() for name in ('repository.json','packages.json')])


if __name__=='__main__':unittest.main()
