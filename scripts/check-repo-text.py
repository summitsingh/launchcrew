"""Explicit tracked-source grep checks, including staged additions."""
import subprocess
for label, pattern in [('em_dash', chr(0x2014)), ('legacy_brand', 'Company' + ' OS')]:
    result = subprocess.run(['git', 'grep', '-I', '-n', '-i', '-F', pattern, '--', '.', ':!**/__pycache__/**', ':!.git/**'], capture_output=True, text=True)
    if result.returncode not in (0, 1):
        raise SystemExit(result.returncode)
    count = len(result.stdout.splitlines())
    print(label + ': ' + str(count))
    if count:
        raise SystemExit(1)
