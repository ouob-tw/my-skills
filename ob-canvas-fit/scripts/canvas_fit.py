#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Measure Obsidian Canvas text nodes from real rendering and suggest heights."""

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

MEASURE_JS = Path(__file__).with_name("measure.js")
MARGIN_PX = 15
ROUND_TO_PX = 10
SECONDS_PER_NODE = 4
BASE_TIMEOUT_S = 40


class ToolError(Exception):
    """The tool could not run at all (exit 2)."""


def suggested_height(content: int) -> int:
    return math.ceil((content + MARGIN_PX) / ROUND_TO_PX) * ROUND_TO_PX


def _intersects(a: dict, b: dict) -> bool:
    return (
        a["x"] < b["x"] + b["width"]
        and b["x"] < a["x"] + a["width"]
        and a["y"] < b["y"] + b["height"]
        and b["y"] < a["y"] + a["height"]
    )


def _contains(outer: dict, inner: dict) -> bool:
    return (
        outer["x"] <= inner["x"]
        and outer["y"] <= inner["y"]
        and inner["x"] + inner["width"] <= outer["x"] + outer["width"]
        and inner["y"] + inner["height"] <= outer["y"] + outer["height"]
    )


def find_overlaps(nodes: list[dict]) -> list[tuple[str, str]]:
    plain = [n for n in nodes if n.get("type") != "group"]
    return [
        (a["id"], b["id"])
        for i, a in enumerate(plain)
        for b in plain[i + 1 :]
        if _intersects(a, b)
    ]


def find_group_overflows(nodes: list[dict]) -> list[tuple[str, str]]:
    """Pairs (node, group) where the node is partly inside the group."""
    groups = [n for n in nodes if n.get("type") == "group"]
    return [
        (n["id"], g["id"])
        for g in groups
        for n in nodes
        if n is not g and _intersects(n, g) and not _contains(g, n) and not _contains(n, g)
    ]


def set_heights(raw: str, heights: dict[str, int]) -> str:
    """Change only the height values in the file text, leaving every other byte alone."""
    start = re.search(r'"nodes"\s*:\s*\[', raw)
    if not start:
        raise ValueError("no nodes array in the canvas")
    decoder = json.JSONDecoder()
    pieces, cursor, pos, seen = [], 0, start.end(), set()
    while True:
        pos = re.compile(r"[\s,]*").match(raw, pos).end()
        if raw[pos] == "]":
            break
        item, end = decoder.raw_decode(raw, pos)
        if item.get("id") in heights:
            match = re.compile(r'"height"\s*:\s*(-?[\d.eE+-]+)').search(raw, pos, end)
            if not match:
                raise ValueError(f"node {item['id']} has no height")
            pieces += [raw[cursor : match.start(1)], str(heights[item["id"]])]
            cursor = match.end(1)
            seen.add(item["id"])
        pos = end
    pieces.append(raw[cursor:])
    missing = set(heights) - seen
    if missing:
        raise ValueError(f"nodes not found: {sorted(missing)}")

    result = "".join(pieces)
    expected = json.loads(raw)
    for node in expected["nodes"]:
        if node.get("id") in heights:
            node["height"] = heights[node["id"]]
    if json.loads(result) != expected:
        raise ValueError("the edit would change more than node heights")
    return result


def obsidian_eval(code: str, vault: str | None, timeout: float):
    command = ["obsidian"] + ([f"vault={vault}"] if vault else []) + ["eval", f"code={code}"]
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        raise ToolError("the obsidian command is not on PATH") from None
    except subprocess.TimeoutExpired:
        raise ToolError(
            f"Obsidian did not answer within {timeout:.0f}s; check it for a stray canvas tab"
        ) from None
    # The CLI can mix log lines from other running commands into its output.
    answers = [line for line in done.stdout.splitlines() if line.startswith("=> ")]
    if not answers:
        raise ToolError(f"Obsidian eval failed: {done.stdout.strip() or done.stderr.strip()}")
    return json.loads(answers[-1][3:])


def _resolve(canvas: str, base: Path) -> str:
    path = Path(canvas)
    if not path.is_absolute():
        return path.as_posix()
    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        raise ToolError(f"{canvas} is not inside the vault at {base}") from None


def _write_atomic(path: Path, text: str) -> None:
    real = Path(os.path.realpath(path))
    fd, tmp = tempfile.mkstemp(dir=real.parent, prefix=f".{real.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        os.chmod(tmp, real.stat().st_mode)
        os.replace(tmp, real)
    except BaseException:
        os.unlink(tmp)
        raise


def _short(text: str, width: int = 36) -> str:
    line = " ".join(text.split())
    return line if len(line) <= width else line[: width - 1] + "…"


def _layout_lines(title: str, nodes: list[dict]) -> list[str]:
    overlaps = find_overlaps(nodes)
    overflows = find_group_overflows(nodes)
    lines = [title]
    lines.append("  overlaps: none" if not overlaps else "  overlaps:")
    lines += [f"    {a} overlaps {b}" for a, b in overlaps]
    lines.append("  outside group: none" if not overflows else "  outside group:")
    lines += [f"    {n} sticks out of group {g}" for n, g in overflows]
    return lines


def run(canvas: str, vault: str | None, apply: bool, eval_js=obsidian_eval, emit=print) -> int:
    base = Path(eval_js("JSON.stringify(app.vault.adapter.basePath)", vault, 20))
    rel = _resolve(canvas, base)
    file = base / rel
    if not file.is_file():
        raise ToolError(f"no such canvas in the vault: {rel}")

    before = file.read_bytes()
    try:
        data = json.loads(before)
    except ValueError as error:
        raise ToolError(f"{rel} is not valid canvas JSON: {error}") from None
    nodes = data.get("nodes", [])
    texts = [n for n in nodes if n.get("type") == "text"]

    code = MEASURE_JS.read_text(encoding="utf-8").replace(
        "__ARGS__", json.dumps({"path": rel, "ids": [n["id"] for n in texts]})
    )
    # `obsidian eval` prints the awaited value as text, so the page hands back JSON.
    wrapped = f"Promise.resolve({code.strip()}).then(JSON.stringify)"
    result = eval_js(wrapped, vault, BASE_TIMEOUT_S + SECONDS_PER_NODE * len(texts))
    if result.get("fatal"):
        raise ToolError(result["fatal"])

    measured, failed, new_heights = {}, [], {}
    for node in texts:
        outcome = result["nodes"].get(node["id"])
        if outcome is None:
            failed.append((node, "no result"))
        elif outcome.get("error"):
            failed.append((node, outcome["error"]))
        elif not outcome.get("content"):
            failed.append((node, "measured 0"))
        else:
            measured[node["id"]] = outcome["content"]
            new_heights[node["id"]] = suggested_height(outcome["content"])

    emit(f"Canvas: {rel}  ({len(texts)} text nodes, {len(nodes) - len(texts)} other nodes not measured)")
    emit(f"{'node':<18} {'current':>7} {'content':>7} {'suggest':>7}  text")
    for node in texts:
        if node["id"] in measured:
            emit(
                f"{node['id']:<18} {node['height']:>7} {measured[node['id']]:>7} "
                f"{new_heights[node['id']]:>7}  {_short(node['text'])}"
            )

    exit_code = 0
    if failed:
        exit_code = 1
        emit(f"FAILED, {len(failed)} node(s) not measured and never written:")
        for node, reason in failed:
            emit(f"  {node['id']}: {reason}  [{_short(node['text'])}]")
    if result.get("stopped"):
        exit_code = 1
        emit(f"Measuring stopped early: {result['stopped']}")
    if result.get("shownForRun"):
        emit("The Obsidian window was hidden: shown without focus for this run and put back.")
    if not result.get("restored"):
        exit_code = 1
        emit("Obsidian was not restored: check its tabs and active tab by hand.")

    resized = [{**n, "height": new_heights.get(n["id"], n["height"])} for n in nodes]
    emit("")
    for line in _layout_lines("Layout now:", nodes) + _layout_lines("Layout with suggested heights:", resized):
        emit(line)
    emit("Check by eye: group labels and node labels are not covered. This tool cannot see them.")
    emit("")

    current = file.read_bytes()
    if current != before:
        emit(
            f"{rel} changed during measuring "
            f"({hashlib.sha256(before).hexdigest()[:12]} -> {hashlib.sha256(current).hexdigest()[:12]}): "
            "these numbers may be stale and nothing was written. Run again."
        )
        return 1
    changes = {
        n["id"]: new_heights[n["id"]]
        for n in texts
        if n["id"] in new_heights and new_heights[n["id"]] != n["height"]
    }
    if not apply:
        emit(f"Dry run: nothing written. {len(changes)} height(s) would change; add --apply to write them.")
        return exit_code
    if changes:
        new_text = set_heights(before.decode("utf-8"), changes)
        if file.read_bytes() != before:
            emit(f"{rel} changed during measuring: nothing was written. Run again.")
            return 1
        _write_atomic(file, new_text)
    emit(f"Applied: {len(changes)} height(s) written, nothing else in the file changed.")
    return exit_code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("canvas", help="canvas path, relative to the vault or absolute")
    parser.add_argument("--vault", help="vault name; default is the vault Obsidian focused last")
    parser.add_argument("--apply", action="store_true", help="write the suggested heights to the file")
    args = parser.parse_args()
    try:
        return run(args.canvas, args.vault, args.apply)
    except ToolError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
