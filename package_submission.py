"""Package source, raw data and verified exports; omit local runtimes/secrets."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

root = Path(__file__).resolve().parent
target = root / 'money-graph-submission.zip'
selected = [root / name for name in ['README.md', '.gitignore', 'start.py', 'package_submission.py']]
for name in ['python', 'server', 'public', 'tests', 'docs', 'data/raw', 'data/output']:
    for file in (root / name).rglob('*'):
        if file.is_file() and 'node_modules' not in file.parts and '__pycache__' not in file.parts and file.name != '.env':
            selected.append(file)
with ZipFile(target, 'w', compression=ZIP_DEFLATED) as archive:
    for file in sorted(selected):
        archive.write(file, 'money-graph/' + file.relative_to(root).as_posix())
with ZipFile(target) as archive:
    assert archive.testzip() is None
    print(f'{target.name}: {len(archive.namelist())} files, {target.stat().st_size} bytes, CRC verified')
