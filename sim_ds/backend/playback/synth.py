"""Deterministic synthetic channel payloads for demo playback sources."""

from __future__ import annotations

import math
from typing import Any


def chunk_payload(
    name: str, kind: str, fps: int, start: int, end: int, channel: dict[str, Any]
) -> dict[str, Any]:
    span_ms = end - start
    base = channel.get("baseline", {})
    if kind in {"timeseries", "pose"}:
        count = max(1, int(fps * span_ms / 1000))
        samples = []
        for index in range(count):
            ts = start + int(index * 1000 / fps)
            phase = ts / 1000.0
            samples.append(
                {
                    "ts": ts,
                    "value": round(base.get("value", 10.0) + math.sin(phase) * 2.5, 4),
                    "x": round(math.cos(phase / 4) * 20, 3),
                    "y": round(math.sin(phase / 4) * 20, 3),
                    "yaw": round((phase / 4) % (2 * math.pi), 4),
                }
            )
        return {"channel": name, "type": kind, "start_ms": start, "end_ms": end, "samples": samples}
    count = max(1, int(fps * span_ms / 1000))
    if kind == "pointcloud":
        frames = []
        for index in range(count):
            ts = start + int(index * 1000 / fps)
            points = []
            for point in range(24):
                angle = (point / 24.0) * 2 * math.pi + ts / 4000.0
                radius = 4 + (point % 5)
                points.append(
                    {
                        "x": round(math.cos(angle) * radius, 3),
                        "y": round(math.sin(angle) * radius, 3),
                        "z": round((point % 3) * 0.4, 3),
                        "i": round(0.4 + (point % 4) * 0.15, 3),
                    }
                )
            frames.append({"ts": ts, "points": points})
        return {"channel": name, "type": kind, "start_ms": start, "end_ms": end, "frames": frames}
    frames = [
        {"ts": start + int(index * 1000 / fps), "objects": objects(start + int(index * 1000 / fps))}
        for index in range(count)
    ]
    return {"channel": name, "type": "video", "start_ms": start, "end_ms": end, "frames": frames}


def objects(ts: int) -> list[dict[str, Any]]:
    cars = []
    for index in range(3):
        cars.append(
            {
                "id": f"veh-{index}",
                "x": round(0.2 + ((ts / 1000 + index * 7) % 20) / 20, 3),
                "y": round(0.35 + index * 0.12, 3),
                "w": 0.09,
                "h": 0.14,
                "color": ["#2f6feb", "#1a7f4b", "#c0392b"][index],
            }
        )
    return cars


def frame_svg(frame: dict[str, Any]) -> str:
    objects_svg = "".join(
        f'<rect x="{float(item["x"]) * 640:.1f}" y="{float(item["y"]) * 360:.1f}" '
        f'width="{float(item["w"]) * 640:.1f}" height="{float(item["h"]) * 360:.1f}" '
        f'fill="{item.get("color", "#2f6feb")}" rx="3"/>'
        for item in frame.get("objects", [])
    )
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 360">'
        '<rect width="640" height="360" fill="#1b2430"/>'
        '<path d="M280 360 L320 40 L360 360" stroke="#4b5a6b" stroke-width="2" fill="none"/>'
        '<path d="M0 250 H640" stroke="#3a4757" stroke-dasharray="12 10"/>'
        f"{objects_svg}"
        '<text x="12" y="24" fill="#aab6c5" font-size="14">sim camera · front</text>'
        "</svg>"
    )
