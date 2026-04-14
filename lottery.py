#!/usr/bin/env python3
"""公司抽奖程序（命令行版）

功能：
1. 从 CSV 或 TXT 文件导入员工名单
2. 支持配置多个奖项及每个奖项的名额
3. 无重复抽奖，自动从剩余候选人中抽取
4. 将抽奖结果保存为 JSON 文件

示例：
python3 lottery.py --participants participants.csv --prize 一等奖:1 --prize 二等奖:2 --seed 42
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class Prize:
    name: str
    count: int


def load_participants(file_path: Path) -> list[str]:
    """加载参与者名单，支持 .csv / .txt。"""
    if not file_path.exists():
        raise FileNotFoundError(f"名单文件不存在: {file_path}")

    participants: list[str] = []
    suffix = file_path.suffix.lower()

    if suffix == ".csv":
        with file_path.open("r", encoding="utf-8") as f:
            reader = csv.reader(f)
            for row in reader:
                if not row:
                    continue
                name = row[0].strip()
                if name and name.lower() != "name":
                    participants.append(name)
    else:
        with file_path.open("r", encoding="utf-8") as f:
            for line in f:
                name = line.strip()
                if name:
                    participants.append(name)

    unique = []
    seen = set()
    for p in participants:
        if p not in seen:
            seen.add(p)
            unique.append(p)

    if not unique:
        raise ValueError("参与者名单为空，请检查输入文件")

    return unique


def parse_prizes(raw_prizes: Iterable[str]) -> list[Prize]:
    """解析奖项参数，格式为 奖项名:名额。"""
    prizes: list[Prize] = []
    for item in raw_prizes:
        if ":" not in item:
            raise ValueError(f"奖项格式错误: {item}，应为 奖项名:名额")
        name, raw_count = item.split(":", 1)
        name = name.strip()
        if not name:
            raise ValueError(f"奖项名称不能为空: {item}")
        try:
            count = int(raw_count)
        except ValueError as exc:
            raise ValueError(f"名额必须是整数: {item}") from exc
        if count <= 0:
            raise ValueError(f"名额必须大于 0: {item}")
        prizes.append(Prize(name=name, count=count))

    if not prizes:
        raise ValueError("至少需要设置一个奖项")

    return prizes


def draw_lottery(participants: list[str], prizes: list[Prize], seed: int | None = None) -> dict[str, list[str]]:
    """执行抽奖并返回结果。"""
    total_slots = sum(p.count for p in prizes)
    if total_slots > len(participants):
        raise ValueError(
            f"总名额 ({total_slots}) 超过参与者数量 ({len(participants)})，请减少奖项名额"
        )

    rng = random.Random(seed)
    remaining = participants[:]
    result: dict[str, list[str]] = {}

    for prize in prizes:
        winners = rng.sample(remaining, prize.count)
        result[prize.name] = winners
        remaining = [p for p in remaining if p not in winners]

    return result


def save_result(result: dict[str, list[str]], output_file: Path) -> None:
    """保存抽奖结果。"""
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "results": result,
    }
    output_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def print_result(result: dict[str, list[str]]) -> None:
    """打印抽奖结果。"""
    print("\n===== 抽奖结果 =====")
    for prize, winners in result.items():
        print(f"{prize} ({len(winners)}人): {', '.join(winners)}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="公司抽奖程序")
    parser.add_argument(
        "--participants",
        type=Path,
        required=True,
        help="参与者名单文件路径（CSV 第一列或 TXT 每行一个姓名）",
    )
    parser.add_argument(
        "--prize",
        action="append",
        required=True,
        help="奖项配置，格式：奖项名:名额。可重复传入多个，例如 --prize 一等奖:1 --prize 二等奖:2",
    )
    parser.add_argument("--seed", type=int, default=None, help="随机种子（可选，用于复现结果）")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("lottery_result.json"),
        help="结果输出文件路径，默认 lottery_result.json",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    participants = load_participants(args.participants)
    prizes = parse_prizes(args.prize)

    result = draw_lottery(participants, prizes, seed=args.seed)
    print_result(result)
    save_result(result, args.output)
    print(f"\n结果已保存到: {args.output.resolve()}")


if __name__ == "__main__":
    main()
