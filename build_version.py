# build_version.py
import subprocess
import os
from datetime import datetime

# Compatibility fix for Python <3.11
try:
    from datetime import UTC
except ImportError:
    from datetime import timezone
    UTC = timezone.utc

commit = os.environ.get("MSO5000_BUILD_COMMIT") or subprocess.getoutput(
    "git rev-parse --short HEAD"
)
version = os.environ.get("MSO5000_BUILD_VERSION") or subprocess.getoutput(
    "git describe --tags --abbrev=0"
)
now = os.environ.get("MSO5000_BUILD_DATE") or datetime.now(UTC).strftime(
    "%Y-%m-%d %H:%M UTC"
)

print("commit:", commit)
print("version:", version)
print("now:", now)

try:
    with open("version.py", "w") as f:
        f.write(f'APP_NAME = "MSO5000 Live Monitor"\n')
        f.write(f'VERSION = "{version}"\n')
        f.write(f'GIT_COMMIT = "{commit}"\n')
        f.write(f'BUILD_DATE = "{now}"\n')
        f.write(f'AUTHOR = "ariDev1"\n')
        f.write(f'PROJECT_URL = "https://github.com/ariDev1/MSO5000_liveview"\n')
    print("version.py written successfully.")
except Exception as e:
    print("❌ Error writing version.py:", e)
