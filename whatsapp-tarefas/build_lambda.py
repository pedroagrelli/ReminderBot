import shutil
import subprocess
import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent
PACKAGE_DIR = PROJECT_DIR / "lambda_package"


def main() -> None:
    if PACKAGE_DIR.exists():
        shutil.rmtree(PACKAGE_DIR)
    PACKAGE_DIR.mkdir(exist_ok=True)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--requirement",
            str(PROJECT_DIR / "requirements-lambda.txt"),
            "--target",
            str(PACKAGE_DIR),
        ],
        check=True,
    )
    shutil.copy2(PROJECT_DIR / "aws_app.py", PACKAGE_DIR / "aws_app.py")
    shutil.copy2(PROJECT_DIR / "bot.py", PACKAGE_DIR / "bot.py")
    print(f"Pacote da Lambda preparado em {PACKAGE_DIR}")


if __name__ == "__main__":
    main()
