"""读取 locust `--csv` 输出的 statistics.csv，汇总并（可选）按预算断言。"""

import csv
import sys
from contextlib import suppress
from pathlib import Path


def _load_stats(prefix: str) -> list[dict[str, str]]:
    """定位 locust 输出的 statistics csv。优先 `{prefix}_stats.csv`(locust2 默认),
    兼容 `{prefix}_statistics.csv` 与裸 `{prefix}.csv`。"""
    candidates = [
        Path(prefix + "_stats.csv"),
        Path(prefix + "_statistics.csv"),
        Path(prefix).with_suffix(".csv"),
    ]
    for path in candidates:
        if path.exists():
            with path.open(encoding="utf-8") as f:
                return list(csv.DictReader(f))
    print(
        f"[check_bench] 未找到 locust statistics csv: {prefix}",
        file=sys.stderr,
    )
    sys.exit(2)
    return []


def _budget_map(csv_path: str) -> dict[str, tuple[float, float]]:
    """预算表 `path,p95_max_ms,rps_min` → {path:(p95, rps)}。用于门禁断言。"""
    result: dict[str, tuple[float, float]] = {}
    if not csv_path:
        return result
    with Path(csv_path).open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            path = (row.get("path") or "").strip()
            if not path:
                continue
            result[path] = (float(row["p95_max_ms"]), float(row["rps_min"]))
    return result


def main() -> int:
    prefix = sys.argv[1]
    budget_csv = sys.argv[2] if len(sys.argv) > 2 else ""
    rows = _load_stats(prefix)
    budget = _budget_map(budget_csv)
    # locust stats csv 列名（2.x）：Type / Name / Request Count / Failure Count /
    print(
        f"{'Method':<6}{'Name':<52}{'#Req':>8}{'Fail%':>8} {'P95(ms)':>9}{'RPS':>12}"
    )
    violations = 0
    for r in rows:
        name = r.get("Name", "") or ""
        n_req = r.get("Request Count", "0") or "0"
        fails = r.get("Failure Count", "0") or "0"
        p95 = r.get("95%", "-") or "-"
        rps_raw = r.get("Requests/s", "0") or "0"
        fail_p = "n/a"
        with suppress(ValueError, ZeroDivisionError):
            fail_p = f"{float(fails) / max(float(n_req), 1) * 100:.1f}"
        try:
            rps = f"{float(rps_raw):.2f}"
        except ValueError:
            rps = rps_raw
        print(
            f"{r.get('Type', '?') or '?':<6}"
            f"{name:<52}{n_req:>8}{fail_p:>8} {p95:>10}{rps:>10}"
        )
        # 门禁：预算命中则断言 P95 上限与 RPS 下限
        b = budget.get(name)
        if b is None:
            continue
        p95_max, rps_min = b
        try:
            ok_p95 = float(p95) <= p95_max
            ok_rps = float(rps_raw) >= rps_min
        except ValueError:
            continue
        if not (ok_p95 and ok_rps):
            violations += 1
            print(f"[CHECK] VIOLATION {name}: P95={p95}ms(>={p95_max}) RPS={rps}(>= {rps_min})")
    if budget and violations:
        print(f"[CHECK] 预算门禁失败：{violations} 项超预算", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
