# build_version.py
import subprocess
from datetime import datetime

# ✅ Compatibility fix for Python <3.11 (Ubuntu 22.04)
try:
    from datetime import UTC
except ImportError:
    from datetime import timezone
    UTC = timezone.utc

commit = subprocess.getoutput("git rev-parse --short HEAD")
version = subprocess.getoutput("git describe --tags --abbrev=0")
now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

with open("version.py", "w") as f:
    f.write(f'APP_NAME = "MSO5000 Live Monitor"\n')
    f.write(f'VERSION = "{version}"\n')
    f.write(f'GIT_COMMIT = "{commit}"\n')
    f.write(f'BUILD_DATE = "{now}"\n')
    f.write(f'AUTHOR = "ariDev1"\n')
    f.write(f'PROJECT_URL = "https://github.com/ariDev1/MSO5000_liveview"\n')
