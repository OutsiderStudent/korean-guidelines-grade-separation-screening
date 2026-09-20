$ErrorActionPreference = "Stop"
$Python = "C:\Users\yuhyu\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
& $Python -m PyInstaller --noconfirm --clean "interchange_review.spec"
