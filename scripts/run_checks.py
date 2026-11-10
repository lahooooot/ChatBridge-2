"""Run source checks without starting desktop services or a real site session."""
import py_compile
import subprocess
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

def run(argv):
    print('+', ' '.join(map(str, argv)), flush=True)
    subprocess.run(argv, cwd=ROOT, check=True)

for folder in ('desktop', 'tests', 'scripts'):
    for path in (ROOT/folder).rglob('*.py'):
        py_compile.compile(str(path), doraise=True)
print('Python syntax: OK', flush=True)
for path in (ROOT/'desktop').rglob('*.js'):
    run(['node', '--check', str(path)])
for name in ('ver_check.py','ui_dom_check.py'):
    run([sys.executable, str(ROOT/'scripts'/name)])
run([sys.executable, '-m', 'pytest', '-q'])
for name in ('visual_check_agent.py','visual_check_ui.py'):
    run([sys.executable, str(ROOT/'scripts'/name)])
print('All available automated checks passed. Windows/manual checks are separate.', flush=True)
