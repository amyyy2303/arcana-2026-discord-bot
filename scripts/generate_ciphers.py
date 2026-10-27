import os
import zlib
import struct
import json

FONT = {
    ' ': [0, 0, 0, 0, 0, 0, 0],
    'A': [0x0c, 0x12, 0x12, 0x1e, 0x12, 0x12, 0x00],
    'B': [0x1c, 0x12, 0x1c, 0x12, 0x12, 0x1c, 0x00],
    'C': [0x0e, 0x10, 0x10, 0x10, 0x10, 0x0e, 0x00],
    'D': [0x1c, 0x12, 0x12, 0x12, 0x12, 0x1c, 0x00],
    'E': [0x1f, 0x10, 0x1e, 0x10, 0x10, 0x1f, 0x00],
    'F': [0x1f, 0x10, 0x1e, 0x10, 0x10, 0x10, 0x00],
    'G': [0x0e, 0x10, 0x13, 0x11, 0x11, 0x0f, 0x00],
    'H': [0x12, 0x12, 0x1e, 0x12, 0x12, 0x12, 0x00],
    'I': [0x0e, 0x04, 0x04, 0x04, 0x04, 0x0e, 0x00],
    'J': [0x07, 0x02, 0x02, 0x02, 0x12, 0x0c, 0x00],
    'K': [0x12, 0x14, 0x18, 0x14, 0x12, 0x12, 0x00],
    'L': [0x10, 0x10, 0x10, 0x10, 0x10, 0x1f, 0x00],
    'M': [0x11, 0x1b, 0x15, 0x11, 0x11, 0x11, 0x00],
    'N': [0x11, 0x19, 0x15, 0x13, 0x11, 0x11, 0x00],
    'O': [0x0e, 0x11, 0x11, 0x11, 0x11, 0x0e, 0x00],
    'P': [0x1e, 0x11, 0x1e, 0x10, 0x10, 0x10, 0x00],
    'Q': [0x0e, 0x11, 0x11, 0x15, 0x12, 0x0d, 0x00],
    'R': [0x1e, 0x11, 0x1e, 0x14, 0x12, 0x11, 0x00],
    'S': [0x0f, 0x10, 0x0e, 0x01, 0x01, 0x1e, 0x00],
    'T': [0x1f, 0x04, 0x04, 0x04, 0x04, 0x04, 0x00],
    'U': [0x11, 0x11, 0x11, 0x11, 0x11, 0x0e, 0x00],
    'V': [0x11, 0x11, 0x11, 0x11, 0x0a, 0x04, 0x00],
    'W': [0x11, 0x11, 0x15, 0x15, 0x1b, 0x11, 0x00],
    'X': [0x11, 0x0a, 0x04, 0x0a, 0x11, 0x11, 0x00],
    'Y': [0x11, 0x0a, 0x04, 0x04, 0x04, 0x04, 0x00],
    'Z': [0x1f, 0x01, 0x02, 0x04, 0x08, 0x1f, 0x00],
    '0': [0x0e, 0x13, 0x15, 0x19, 0x11, 0x0e, 0x00],
    '1': [0x04, 0x0c, 0x04, 0x04, 0x04, 0x0e, 0x00],
    '2': [0x0e, 0x11, 0x01, 0x06, 0x08, 0x1f, 0x00],
    '3': [0x1e, 0x01, 0x06, 0x01, 0x11, 0x0e, 0x00],
    '4': [0x02, 0x06, 0x0a, 0x12, 0x1f, 0x02, 0x00],
    '5': [0x1f, 0x10, 0x1e, 0x01, 0x11, 0x0e, 0x00],
    '6': [0x06, 0x08, 0x1e, 0x11, 0x11, 0x0e, 0x00],
    '7': [0x1f, 0x01, 0x02, 0x04, 0x04, 0x04, 0x00],
    '8': [0x0e, 0x11, 0x0e, 0x11, 0x11, 0x0e, 0x00],
    '9': [0x0e, 0x11, 0x0f, 0x01, 0x02, 0x0c, 0x00],
    ':': [0x00, 0x0c, 0x0c, 0x00, 0x0c, 0x0c, 0x00],
    '-': [0x00, 0x00, 0x1f, 0x00, 0x00, 0x00, 0x00],
    '.': [0x00, 0x00, 0x00, 0x00, 0x0c, 0x0c, 0x00],
    '/': [0x01, 0x02, 0x04, 0x08, 0x10, 0x00, 0x00],
    '#': [0x0a, 0x1f, 0x0a, 0x0a, 0x1f, 0x0a, 0x00],
    '|': [0x04, 0x04, 0x04, 0x04, 0x04, 0x04, 0x00],
    '=': [0x00, 0x1f, 0x00, 0x1f, 0x00, 0x00, 0x00],
    '<': [0x02, 0x04, 0x08, 0x04, 0x02, 0x00, 0x00],
    '>': [0x08, 0x04, 0x02, 0x04, 0x08, 0x00, 0x00],
    '[': [0x0e, 0x08, 0x08, 0x08, 0x08, 0x0e, 0x00],
    ']': [0x0e, 0x02, 0x02, 0x02, 0x02, 0x0e, 0x00],
    '+': [0x00, 0x04, 0x0e, 0x04, 0x00, 0x00, 0x00],
}


class Canvas:
    def __init__(self, width: int, height: int, bg_color=(15, 23, 42)):
        self.width = width
        self.height = height
        self.pixels = [list(bg_color) for _ in range(width * height)]

    def set_pixel(self, x: int, y: int, color):
        if 0 <= x < self.width and 0 <= y < self.height:
            self.pixels[y * self.width + x] = list(color)

    def fill_rect(self, x1, y1, x2, y2, color):
        for y in range(max(0, y1), min(self.height, y2 + 1)):
            for x in range(max(0, x1), min(self.width, x2 + 1)):
                self.pixels[y * self.width + x] = list(color)

    def draw_rect(self, x1, y1, x2, y2, color, thickness=1):
        for t in range(thickness):
            for x in range(x1, x2 + 1):
                self.set_pixel(x, y1 + t, color)
                self.set_pixel(x, y2 - t, color)
            for y in range(y1, y2 + 1):
                self.set_pixel(x1 + t, y, color)
                self.set_pixel(x2 - t, y, color)

    def draw_text(self, x: int, y: int, text: str, color=(255, 255, 255), scale=2):
        curr_x = x
        for char in text.upper():
            glyph = FONT.get(char, FONT.get(' ', [0]*7))
            for row_idx, row in enumerate(glyph):
                for col_idx in range(5):
                    if (row >> (4 - col_idx)) & 1:
                        for sy in range(scale):
                            for sx in range(scale):
                                self.set_pixel(curr_x + col_idx * scale + sx, y + row_idx * scale + sy, color)
            curr_x += 6 * scale

    def to_png_bytes(self) -> bytes:
        raw = bytearray()
        for y in range(self.height):
            raw.append(0)  # filter type 0: None
            row_start = y * self.width
            for x in range(self.width):
                r, g, b = self.pixels[row_start + x]
                raw.extend((r, g, b, 255))
        compressed = zlib.compress(bytes(raw), level=6)

        def chunk(tag: bytes, data: bytes) -> bytes:
            return struct.pack('>I', len(data)) + tag + data + struct.pack('>I', zlib.crc32(tag + data) & 0xffffffff)

        png = b'\x89PNG\r\n\x1a\n'
        png += chunk(b'IHDR', struct.pack('>IIBBBBB', self.width, self.height, 8, 6, 0, 0, 0))
        png += chunk(b'IDAT', compressed)
        png += chunk(b'IEND', b'')
        return png


def generate_cipher_image(cipher: dict, output_path: str):
    w, h = 640, 320
    canvas = Canvas(w, h, bg_color=(15, 23, 42))  # Slate 900

    # Grid background lines
    grid_color = (30, 41, 59)
    for x in range(0, w, 32):
        for y in range(h):
            canvas.set_pixel(x, y, grid_color)
    for y in range(0, h, 32):
        for x in range(w):
            canvas.set_pixel(x, y, grid_color)

    # Outer border
    diff = cipher["difficulty"].lower()
    if diff == "easy":
        theme_color = (34, 197, 94)    # Emerald Green
        badge_text = "EASY - 150 PTS"
    elif diff == "medium":
        theme_color = (234, 179, 8)    # Amber
        badge_text = "MEDIUM - 250 PTS"
    else:
        theme_color = (239, 68, 68)    # Crimson Red
        badge_text = "HARD - 400 PTS"

    canvas.draw_rect(8, 8, w - 9, h - 9, theme_color, thickness=2)

    # Top Header banner
    canvas.fill_rect(10, 10, w - 11, 46, (2, 6, 23))  # Dark header
    canvas.draw_text(24, 20, f"CIPHER CHALLENGE #{cipher['id']:02d}", (248, 250, 252), scale=2)

    # Difficulty Badge on top right
    badge_x = w - 240
    canvas.fill_rect(badge_x, 18, w - 24, 40, theme_color)
    canvas.draw_text(badge_x + 10, 24, badge_text, (0, 0, 0), scale=1)

    # Category bar
    category_title = f"CATEGORY: {cipher.get('category', 'UNKNOWN')}".upper()
    canvas.draw_text(24, 60, category_title, (148, 163, 184), scale=1)

    # Cipher display box in center
    box_x1, box_y1, box_x2, box_y2 = 24, 88, w - 25, 230
    canvas.fill_rect(box_x1, box_y1, box_x2, box_y2, (2, 6, 23))
    canvas.draw_rect(box_x1, box_y1, box_x2, box_y2, (71, 85, 105), thickness=1)

    # Draw ciphertext text inside box (split into multiple lines if needed)
    ciphertext = cipher["ciphertext"]
    words = ciphertext.split(' ')
    lines = []
    current_line = []
    char_count = 0
    max_chars = 34  # roughly fits nicely at scale 2

    for word in words:
        if char_count + len(word) + (1 if current_line else 0) <= max_chars:
            current_line.append(word)
            char_count += len(word) + (1 if current_line else 0)
        else:
            if current_line:
                lines.append(' '.join(current_line))
            current_line = [word]
            char_count = len(word)
    if current_line:
        lines.append(' '.join(current_line))

    # Center lines vertically in box
    total_text_h = len(lines) * 22
    start_y = box_y1 + (box_y2 - box_y1 - total_text_h) // 2
    for i, line in enumerate(lines):
        canvas.draw_text(40, start_y + i * 22, line, (56, 189, 248), scale=2)

    # Footer instruction bar
    canvas.fill_rect(10, h - 54, w - 11, h - 10, (15, 23, 42))
    canvas.draw_text(24, h - 44, "COMMANDS: ./answer <text>  OR  ./pass", (203, 213, 225), scale=1)
    canvas.draw_text(24, h - 26, "PENALTY: -12 PTS ON WRONG ANSWER | PASS AWARDS +20 TO OPPOSITION", (244, 63, 94), scale=1)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(canvas.to_png_bytes())


def main():
    json_path = os.path.join(os.path.dirname(__file__), "..", "data", "ciphers.json")
    with open(json_path, "r") as f:
        ciphers = json.load(f)

    ciphers_dir = os.path.join(os.path.dirname(__file__), "..", "data", "ciphers")
    for cipher in ciphers:
        out_file = os.path.join(ciphers_dir, cipher["image_filename"])
        generate_cipher_image(cipher, out_file)
        print(f"Generated {out_file} for Cipher #{cipher['id']}")

    print(f"Successfully generated all {len(ciphers)} cipher cards.")


if __name__ == "__main__":
    main()
