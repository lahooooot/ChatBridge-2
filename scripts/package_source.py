"""Package reproducible source with a SHA-256 manifest, excluding local state."""
import hashlib
import json
import sys
import zipfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
output = Path(sys.argv[1]).resolve() if len(sys.argv)>1 else ROOT.parent/'ChatBridge-2.60.0-source.zip'
excluded = {'.venv','__pycache__','.pytest_cache','.git','node_modules','dist','build','installer-output','.chatbridge'}
files = [p for p in ROOT.rglob('*') if p.is_file() and not any(part in excluded for part in p.relative_to(ROOT).parts) and p.suffix not in {'.pyc','.log'} and p.name not in {'.env','source-manifest.json'}]
manifest = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}
manifest_path = ROOT/'source-manifest.json'
manifest_path.write_text(json.dumps({'version':'2.60.0','sha256':manifest}, indent=2)+'\n', encoding='utf-8')
with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
    for path in sorted(files)+[manifest_path]:
        archive.write(path, 'chatbridge/'+path.relative_to(ROOT).as_posix())
with zipfile.ZipFile(output) as archive:
    assert archive.testzip() is None
print(output)
print('Files:',len(files)+1,'ZIP bytes:',output.stat().st_size)
