"""One-command local batch + viewer. --setup installs missing build dependencies."""
import argparse
import importlib
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--setup', action='store_true', help='Allow first-time dependency installation')
    parser.add_argument('--batch-only', action='store_true')
    args = parser.parse_args()
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT / '.deps'))
    try:
        for name in ['pandas', 'pyarrow', 'networkx', 'community']:
            importlib.import_module(name)
    except (ImportError, AttributeError):
        if not args.setup:
            raise SystemExit('Install dependencies first: python start.py --setup')
        subprocess.run([sys.executable, '-m', 'pip', 'install', '--target', str(ROOT / '.deps'),
                        '--upgrade', '-r', str(ROOT / 'python/requirements.txt')], check=True)
    subprocess.run([sys.executable, '-X', 'utf8', str(ROOT / 'python/run_pipeline.py')], check=True)
    if args.batch_only:
        return
    node = shutil.which('node')
    if not node:
        raise SystemExit('Node.js 22+ is required. Install it, then run this command again.')
    if not (ROOT / 'server/node_modules/express').exists():
        if not args.setup:
            raise SystemExit('Install dependencies first: python start.py --setup')
        npm = shutil.which('npm') or shutil.which('npm.cmd')
        pnpm = shutil.which('pnpm') or shutil.which('pnpm.cmd')
        if npm:
            subprocess.run([npm, 'ci', '--prefix', str(ROOT / 'server')], check=True)
        elif pnpm:
            subprocess.run([pnpm, 'install', '--frozen-lockfile', '--dir', str(ROOT / 'server')], check=True)
        else:
            raise SystemExit('npm or pnpm is required for initial setup')
    subprocess.run([node, str(ROOT / 'server/build.js')], check=True)
    env = {**os.environ, 'PYTHON': sys.executable}
    subprocess.run([node, str(ROOT / 'server/index.js')], env=env, check=True)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
