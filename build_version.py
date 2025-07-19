# build_version.py
import subprocess
from datetime import datetime, UTC

commit = subprocess.getoutput("git rev-parse --short HEAD")
now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

with open("version.py", "w") as f:
    f.write(f'APP_NAME = "MSO5000 Live Monitor"\n')
    f.write(f'VERSION = "v0.9.4"\n')
    f.write(f'GIT_COMMIT = "{commit}"\n')
    f.write(f'BUILD_DATE = "{now}"\n')
    f.write(f'AUTHOR = "ariDev1"\n')
    f.write(f'PROJECT_URL = "https://github.com/ariDev1/MSO5000_liveview"\n')
