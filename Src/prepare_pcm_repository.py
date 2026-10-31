"""Generate a KiCad PCM repository index for the already-built plugin ZIP."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import zipfile


ROOT=Path(__file__).resolve().parents[1]
ARCHIVE_NAME='Rogowski_TI_Gerber_PCM_KiCad10.zip'
BASE_URL='https://raw.githubusercontent.com/ktw1525/KiCAD_RogowskiCoil/main/Publish'


def json_bytes(value):
    return (json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode('utf-8')


def prepare_repository(source,output,base_url=BASE_URL):
    source=Path(source);output=Path(output)
    archive_path=output/ARCHIVE_NAME
    archive_bytes=archive_path.read_bytes()
    with zipfile.ZipFile(archive_path) as archive:
        if archive.testzip() is not None: raise ValueError('Plugin ZIP is corrupt.')
        package=json.loads(archive.read('metadata.json'))
        # Publishing an index for an old ZIP would silently distribute stale code.
        for entry in archive.infolist():
            if entry.is_dir(): continue
            expected=(source/entry.filename).resolve()
            if not expected.is_relative_to(source.resolve()): raise ValueError('Invalid archive path.')
            if not expected.is_file() or archive.read(entry)!=expected.read_bytes():
                raise ValueError('ZIP differs from source: %s. Run publish.bat first.'%entry.filename)
        install_size=sum(entry.file_size for entry in archive.infolist())
    if len(package['versions'])!=1: raise ValueError('The ZIP must describe exactly one version.')
    base_url=base_url.rstrip('/')
    version=package['versions'][0]
    version.update(download_url=base_url+'/'+ARCHIVE_NAME,
                   download_sha256=hashlib.sha256(archive_bytes).hexdigest(),
                   download_size=len(archive_bytes),install_size=install_size)
    packages=json_bytes({'packages':[package]})
    timestamp=int(archive_path.stat().st_mtime)
    repository={
        'name':'ktw1525 Rogowski Coil',
        'schema_version':2,
        'maintainer':package['author'],
        'packages':{
            'url':base_url+'/packages.json',
            'sha256':hashlib.sha256(packages).hexdigest(),
            'update_timestamp':timestamp,
            'update_time_utc':datetime.fromtimestamp(timestamp,timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
        },
    }
    # Hash the exact UTF-8 bytes written, independent of Windows newline settings.
    (output/'packages.json').write_bytes(packages)
    (output/'repository.json').write_bytes(json_bytes(repository))
    return repository,package


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'Publish')
    parser.add_argument('--base-url',default=BASE_URL)
    args=parser.parse_args()
    try:
        _,package=prepare_repository(ROOT/'Src',args.output,args.base_url)
    except (OSError,ValueError,KeyError,zipfile.BadZipFile) as exc:
        parser.exit(1,'[ERROR] %s\n'%exc)
    print('[OK] PCM index for %s v%s'%(package['identifier'],package['versions'][0]['version']))
    print('Commit and push the ZIP, repository.json and packages.json together.')
    print('PCM repository URL (available after pushing): '+args.base_url.rstrip('/')+'/repository.json')


if __name__=='__main__': main()
