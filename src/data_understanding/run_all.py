import sys
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
STEPS = ['01_analyze_data.py', '02_visualize.py']


def main():
    for s in STEPS:
        print(f'===== {s} =====', flush=True)
        r = subprocess.run([sys.executable, str(HERE / s)])
        if r.returncode:
            sys.exit(r.returncode)


if __name__ == '__main__':
    main()
