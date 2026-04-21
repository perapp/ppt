from __future__ import annotations

import argparse
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Render dist/install.sh from install.sh.template")
    parser.add_argument("--template", default="install.sh.template")
    parser.add_argument("--out", required=True)
    parser.add_argument("--repo-url", required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()

    template_path = Path(args.template)
    out_path = Path(args.out)
    text = template_path.read_text(encoding="utf-8")
    text = text.replace("{{PPT_REPO_URL}}", args.repo_url)
    text = text.replace("{{PPT_VERSION}}", args.version)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")
    out_path.chmod(0o755)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
