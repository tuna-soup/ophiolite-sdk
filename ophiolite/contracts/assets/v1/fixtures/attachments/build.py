"""E191 s0 C1: write the figure fixtures (synthetic, invented numbers only) once; the committed bytes are the fixtures,
the tests never rebuild them, and their lengths and SHA-256 digests in expected.json were counted by hand
(`wc -c`, `sha256sum`), not by this script.

    files/figure.png       a 400 x 250 chart of invented values over a synthetic amplitude strip (about 40 kB)
    files/figure.jpg       a small chart as a baseline JPEG (written with Pillow)
    files/report.pdf       a two-page report of invented text, uncompressed
    files/drawing.svg      an SVG drawing: not a PNG, JPEG or PDF
    files/page-as-png.png  an HTML page saved under a .png name: not a PNG, JPEG or PDF
    files/polyglot.png     a valid PNG whose tEXt chunk holds <script>: refused as readable as a web page
    files/header-only.png  a PNG signature and header, and nothing else: refused as damaged

Run from the Integration root with the lane's Python (Pillow for the JPEG only):

    python ophiolite-platform/contracts/assets/v1/fixtures/attachments/build.py
"""
import struct
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
FILES = HERE / 'files'
WIDTH, HEIGHT, STRIP = 400, 250, 64
VALUES = (12.0, 14.5, 13.2, 17.8, 21.4, 19.9, 24.6, 28.1, 26.7, 31.3, 35.0, 33.4)  # invented


def chunk(kind, data):
    return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))


def png(rows, width, height, text=None):
    """An 8-bit RGB PNG of `rows` (each width * 3 bytes), one IDAT, optionally one tEXt chunk before it."""
    raw = b''.join(b'\x00' + row for row in rows)
    head = chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
    extra = chunk(b'tEXt', text) if text is not None else b''
    return b'\x89PNG\r\n\x1a\n' + head + extra + chunk(b'IDAT', zlib.compress(raw, 9)) + chunk(b'IEND', b'')


def chart(width, height, strip):
    """White canvas, a grid, two axes, the invented values as a dark polyline with square marks, and below the plot a
    strip of grey amplitudes from a fixed linear congruential sequence (so the file is about 40 kB)."""
    pixels = [[255, 255, 255] * width for _ in range(height)]

    def dot(x, y, colour):
        if 0 <= x < width and 0 <= y < height: pixels[y][3 * x:3 * x + 3] = colour

    plot = height - strip - 20
    for y in range(10, plot, 20):
        for x in range(30, width - 10): dot(x, y, [225, 225, 225])
    for y in range(10, plot + 1): dot(30, y, [0, 0, 0])
    for x in range(30, width - 10): dot(x, plot, [0, 0, 0])
    step, top = (width - 50) / (len(VALUES) - 1), max(VALUES)
    points = [(30 + round(i * step), plot - round(v / top * (plot - 20))) for i, v in enumerate(VALUES)]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        for t in range(101):
            dot(round(x0 + (x1 - x0) * t / 100), round(y0 + (y1 - y0) * t / 100), [20, 60, 140])
    for x, y in points:
        for dx in range(-2, 3):
            for dy in range(-2, 3): dot(x + dx, y + dy, [200, 60, 20])
    state = 20261123
    for y in range(height - strip, height):
        for x in range(width):
            state = (1103515245 * state + 12345) % 2 ** 31
            grey = state >> 23
            dot(x, y, [grey, grey, grey])
    return [bytes(row) for row in pixels]


def pdf(pages):
    """A PDF 1.7 of one Helvetica text line per page, uncompressed, with a classic cross-reference table."""
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>',
               b'<< /Type /Pages /Kids [%s] /Count %d >>' % (b' '.join(b'%d 0 R' % (4 + 2 * i) for i in range(len(pages))), len(pages)),
               b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    for i, line in enumerate(pages):
        content = b'BT /F1 18 Tf 72 720 Td (%s) Tj ET' % line
        objects.append(b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> /Contents %d 0 R >>' % (5 + 2 * i))
        objects.append(b'<< /Length %d >>\nstream\n%s\nendstream' % (len(content), content))
    out, offsets = b'%PDF-1.7\n', []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b'%d 0 obj\n%s\nendobj\n' % (number, body)
    xref = len(out)
    out += b'xref\n0 %d\n0000000000 65535 f \n' % (len(objects) + 1) + b''.join(b'%010d 00000 n \n' % o for o in offsets)
    return out + b'trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n' % (len(objects) + 1, xref)


def jpeg():
    from io import BytesIO
    from PIL import Image
    rows = chart(160, 100, 0)
    image = Image.frombytes('RGB', (160, 100), b''.join(rows))
    out = BytesIO()
    image.save(out, 'JPEG', quality=85, optimize=False, progressive=False)
    return out.getvalue()


def main():
    FILES.mkdir(exist_ok=True)
    small = chart(48, 32, 0)
    out = {
        'figure.png': png(chart(WIDTH, HEIGHT, STRIP), WIDTH, HEIGHT),
        'figure.jpg': jpeg(),
        'report.pdf': pdf([b'Synthetic residual report, page 1 of 2 (invented values).',
                           b'Synthetic residual report, page 2 of 2 (no observed data).']),
        'drawing.svg': b'<?xml version="1.0" encoding="UTF-8"?>\n<svg xmlns="http://www.w3.org/2000/svg" width="40" height="20">'
                       b'<rect width="40" height="20" fill="#14508c"/></svg>\n',
        'page-as-png.png': b'<!DOCTYPE html>\n<html><head><title>Figure</title></head><body><script>document.title = "x";</script>'
                           b'</body></html>\n',
        'polyglot.png': png(small, 48, 32, text=b'Comment\x00<script>document.title = "x";</script>'),
        'header-only.png': b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 48, 32, 8, 2, 0, 0, 0)),
    }
    for name, data in out.items():
        (FILES / name).write_bytes(data)


if __name__ == '__main__':
    main()
