"""从代码导出 OpenAPI 快照，供离线使用或归档。

用法：
    uv run python scripts/export_openapi.py [--json PATH] [--yaml PATH]

默认导出到 docs/openapi/auto.openapi.json（JSON）。
运行时生成的 /redoc、/docs、/openapi.json 始终是最新契约，本脚本仅用于
团队想要一份离线快照/做 diff 对比时手动刷新，不替代运行时文档。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.main import app

DEFAULT_JSON = ROOT / "docs" / "openapi" / "auto.openapi.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="导出后端 OpenAPI 快照")
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON, help="JSON 输出路径")
    parser.add_argument("--yaml", type=Path, default=None, help="（可选）YAML 输出路径")
    args = parser.parse_args()

    spec = app.openapi()

    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(
        json.dumps(spec, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"OK: 已导出 {len(spec.get('paths', {}))} 个路径 -> {args.json}")

    if args.yaml:
        try:
            import yaml
        except ImportError as exc:
            raise SystemExit("写 YAML 需要 pyyaml，可运行: uv add pyyaml") from exc
        args.yaml.parent.mkdir(parents=True, exist_ok=True)
        args.yaml.write_text(
            yaml.safe_dump(spec, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        print(f"OK: 已导出 YAML -> {args.yaml}")


if __name__ == "__main__":
    main()
