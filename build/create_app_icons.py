#!/usr/bin/env python3
"""Render the AFZ SVG mark into the native icon files required for packaging."""
import struct
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets" / "afz-logo.svg"
OUTPUT = ROOT / "build" / "icons"


def render(size):
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    renderer = QSvgRenderer(str(SOURCE))
    source_size = renderer.defaultSize()
    scale = min(size / source_size.width(), size / source_size.height())
    width, height = source_size.width() * scale, source_size.height() * scale
    renderer.render(painter, QRectF((size - width) / 2, (size - height) / 2, width, height))
    painter.end()
    return image


def save(image, path, fmt=None):
    if not image.save(str(path), fmt):
        raise RuntimeError("Could not create %s" % path)


def png_bytes(image):
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buffer, "PNG"):
        raise RuntimeError("Could not render PNG icon data")
    return bytes(data)


def save_icns(path):
    """Write a modern ICNS container holding PNG chunks for every macOS size."""
    chunks = []
    for size, kind in ((16, b"icp4"), (32, b"icp5"), (64, b"icp6"),
                       (128, b"ic07"), (256, b"ic08"), (512, b"ic09"),
                       (1024, b"ic10")):
        payload = png_bytes(render(size))
        chunks.append(kind + struct.pack(">I", len(payload) + 8) + payload)
    body = b"".join(chunks)
    path.write_bytes(b"icns" + struct.pack(">I", len(body) + 8) + body)


def main():
    if not SOURCE.is_file():
        raise RuntimeError("Missing AFZ logo: %s" % SOURCE)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    # The source mark remains the single authority for all distributed icons.
    save(render(256), OUTPUT / "afz-logo.ico", "ICO")
    save_icns(OUTPUT / "afz-logo.icns")


if __name__ == "__main__":
    main()
