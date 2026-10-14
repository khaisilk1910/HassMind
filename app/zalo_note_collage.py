"""Read-only, on-demand photo grids for a single Zalo image message.

The original note attachments are never mutated or replaced. A short-lived
signed HTTP endpoint exposes the generated JPEG exclusively to Zalo Server.
"""
from __future__ import annotations

from io import BytesIO
from math import ceil

from PIL import Image, ImageDraw, ImageOps

from . import notes

MAX_TILES = notes.MAX_IMAGES
CANVAS_WIDTH = 1440
CELL_WIDTH = 680
CELL_HEIGHT = 600
GAP = 24
MARGIN = 28


def render_note_collage(note_id: str) -> bytes:
    """Build one image containing *all* attachments, without cropping photos."""
    note = notes.get_note(note_id)
    if not note or len(note['images']) < 2 or len(note['images']) > MAX_TILES:
        raise ValueError('Note must have two to five available photos')

    images = note['images']
    rows = ceil(len(images) / 2)
    height = MARGIN * 2 + rows * CELL_HEIGHT + (rows - 1) * GAP
    with Image.new('RGB', (CANVAS_WIDTH, height), '#f0f2f5') as canvas:
        brush = ImageDraw.Draw(canvas)
        for position, entry in enumerate(images):
            detail = notes.image_info(entry['id'])
            if not detail:
                raise ValueError('One of the note photos is missing')
            filename, _mime = detail
            with Image.open(filename) as source:
                source.load()
                if source.width * source.height > notes.MAX_PIXELS:
                    raise ValueError('Photo dimensions exceed limit')
                fitted = ImageOps.contain(source.convert('RGB'), (CELL_WIDTH, CELL_HEIGHT), Image.Resampling.LANCZOS)
                try:
                    row, column = divmod(position, 2)
                    # Center the last item for albums containing an odd number.
                    x = (CANVAS_WIDTH - CELL_WIDTH) // 2 if position == len(images) - 1 and column == 0 else MARGIN + column * (CELL_WIDTH + GAP)
                    y = MARGIN + row * (CELL_HEIGHT + GAP)
                    brush.rounded_rectangle((x - 3, y - 3, x + CELL_WIDTH + 3, y + CELL_HEIGHT + 3), radius=16, fill='#ffffff')
                    canvas.paste(fitted, (x + (CELL_WIDTH - fitted.width) // 2, y + (CELL_HEIGHT - fitted.height) // 2))
                finally:
                    fitted.close()
        output = BytesIO()
        canvas.save(output, format='JPEG', quality=88, optimize=True, progressive=True)
        return output.getvalue()
