#!/usr/bin/env python3
"""Genera assets/ui_preview.png (1280x720) estilo prototipo Obsidian."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "ui_preview.png"

BG = (5, 5, 5)
PANEL = (13, 13, 13)
ACCENT = (0, 242, 255)
TEXT = (217, 217, 217)
MUTED = (138, 138, 138)
BUBBLE = (6, 34, 42)


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    w, h = 1280, 720
    img = Image.new("RGB", (w, h), BG)
    dr = ImageDraw.Draw(img)

    try:
        font_title = ImageFont.truetype("segoeui.ttf", 22)
        font_small = ImageFont.truetype("consola.ttf", 13)
        font_body = ImageFont.truetype("segoeui.ttf", 14)
    except Exception:
        font_title = ImageFont.load_default()
        font_small = ImageFont.load_default()
        font_body = ImageFont.load_default()

    dr.rectangle([12, 12, w - 340, h - 12], outline=(26, 26, 26), fill=PANEL)
    dr.rectangle([w - 328, 12, w - 12, h - 12], outline=(26, 26, 26), fill=PANEL)

    dr.text((28, 20), "EDA | CORE", fill=ACCENT, font=font_title)
    dr.text((980, 24), "STT: READY", fill=(57, 255, 20), font=font_small)

    bx1, by1, bx2, by2 = 36, 70, 820, 160
    dr.rounded_rectangle([bx1, by1, bx2, by2], radius=6, fill=BUBBLE, outline=(26, 26, 26))
    dr.text((bx1 + 12, by1 + 10), "SYSTEM", fill=ACCENT, font=font_small)
    dr.text(
        (bx1 + 12, by1 + 32),
        "Protocolo de seguridad ejecutado. ¿Deseas iniciar rotación de llaves?",
        fill=TEXT,
        font=font_body,
    )

    dr.rectangle([36, h - 96, w - 352, h - 36], outline=(26, 26, 26), fill=(10, 10, 10))
    dr.text((48, h - 74), "Escribe tu comando...", fill=MUTED, font=font_body)

    rx = w - 320
    dr.text((rx, 36), "RECURSOS", fill=MUTED, font=font_small)
    dr.text((rx, 58), "CPU 12%", fill=ACCENT, font=font_small)
    dr.rectangle([rx, 78, rx + 260, 82], fill=(17, 17, 17))
    dr.rectangle([rx, 78, rx + 40, 82], fill=ACCENT)
    dr.text((rx, 94), "RAM 4.2 / 7.8 GB", fill=(57, 255, 20), font=font_small)
    dr.rectangle([rx, 114, rx + 260, 118], fill=(17, 17, 17))
    dr.rectangle([rx, 114, rx + 180, 118], fill=(57, 255, 20))

    dr.text((rx, 138), "ACCIONES RÁPIDAS", fill=MUTED, font=font_small)
    labels = [
        ("Limpiar Disco", False),
        ("Render GPU", False),
        ("Generar CV", False),
        ("Rotar Llaves", True),
    ]
    cell_w, cell_h, gap = 155, 34, 8
    base_y = 168
    for idx, (label, hl) in enumerate(labels):
        gc, gr = idx % 2, idx // 2
        bx = rx + gc * (cell_w + gap)
        by = base_y + gr * (cell_h + gap)
        fg = ACCENT if hl else (15, 15, 15)
        tc = (0, 19, 24) if hl else TEXT
        dr.rounded_rectangle(
            [bx, by, bx + cell_w, by + cell_h],
            radius=4,
            fill=fg,
            outline=ACCENT if hl else (26, 26, 26),
            width=2 if hl else 1,
        )
        dr.text((bx + 10, by + 8), label, fill=tc, font=font_small)

    dr.text((rx, 310), "ÚLTIMOS LOGS", fill=MUTED, font=font_small)
    dr.text((rx, 332), "• [17:42] UI: INPUT: hola", fill=MUTED, font=font_small)

    img.save(OUT, format="PNG")
    print(f"Wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
