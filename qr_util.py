from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPixmap

GF_EXP = [0] * 512
GF_LOG = [0] * 256

def _init_gf():
    x = 1
    for i in range(255):
        GF_EXP[i] = x
        GF_EXP[i + 255] = x
        GF_LOG[x] = i
        x <<= 1
        if x & 256:
            x ^= 0x11D

_init_gf()

def gf_mul(x, y):
    if x == 0 or y == 0:
        return 0
    return GF_EXP[GF_LOG[x] + GF_LOG[y]]

def rs_generator_poly(degree):
    poly = [1]
    for i in range(degree):
        next_poly = [0] * (len(poly) + 1)
        root = GF_EXP[i]
        for j in range(len(poly)):
            next_poly[j] ^= gf_mul(poly[j], root)
            next_poly[j + 1] ^= poly[j]
        poly = next_poly
    return poly

def rs_encode(data, num_ec_bytes):
    gen = rs_generator_poly(num_ec_bytes)
    msg = data + [0] * num_ec_bytes
    for i in range(len(data)):
        coef = msg[i]
        if coef != 0:
            for j in range(len(gen)):
                msg[i + j] ^= gf_mul(gen[j], coef)
    return msg[len(data):]

VERSION_SPECS = [
    {"version": 1, "size": 21, "totalCodewords": 26, "dataCodewords": 19, "ecCodewords": 7, "alignment": []},
    {"version": 2, "size": 25, "totalCodewords": 44, "dataCodewords": 34, "ecCodewords": 10, "alignment": [6, 18]},
    {"version": 3, "size": 29, "totalCodewords": 70, "dataCodewords": 55, "ecCodewords": 15, "alignment": [6, 22]},
    {"version": 4, "size": 33, "totalCodewords": 100, "dataCodewords": 80, "ecCodewords": 20, "alignment": [6, 26]},
    {"version": 5, "size": 37, "totalCodewords": 134, "dataCodewords": 108, "ecCodewords": 26, "alignment": [6, 30]},
    {"version": 6, "size": 41, "totalCodewords": 172, "dataCodewords": 136, "ecCodewords": 36, "alignment": [6, 34]},
    {"version": 7, "size": 45, "totalCodewords": 196, "dataCodewords": 156, "ecCodewords": 40, "alignment": [6, 22, 38]},
]

def generate_qr_matrix(text: str):
    utf8_bytes = list(text.encode("utf-8"))
    data_len = len(utf8_bytes)

    spec = next((s for s in VERSION_SPECS if s["dataCodewords"] >= data_len + 3), VERSION_SPECS[-1])
    size = spec["size"]

    bits = []
    def push_bits(val, length):
        for i in range(length - 1, -1, -1):
            bits.append((val >> i) & 1)

    push_bits(0b0100, 4)
    push_bits(data_len, 8)
    for b in utf8_bytes:
        push_bits(b, 8)

    total_data_bits = spec["dataCodewords"] * 8
    term_len = min(4, total_data_bits - len(bits))
    push_bits(0, term_len)

    while len(bits) % 8 != 0:
        bits.append(0)

    pad_bytes = [0xEC, 0x11]
    pad_idx = 0
    while len(bits) < total_data_bits:
        push_bits(pad_bytes[pad_idx % 2], 8)
        pad_idx += 1

    data_bytes = []
    for i in range(0, len(bits), 8):
        b = 0
        for j in range(8):
            b = (b << 1) | bits[i + j]
        data_bytes.append(b)

    ec_bytes = rs_encode(data_bytes, spec["ecCodewords"])
    final_codewords = data_bytes + ec_bytes

    matrix = [[None] * size for _ in range(size)]
    is_func = [[False] * size for _ in range(size)]

    def set_func(r, c, val):
        if 0 <= r < size and 0 <= c < size:
            matrix[r][c] = val
            is_func[r][c] = True

    def draw_finder(r0, c0):
        for r in range(-1, 8):
            for c in range(-1, 8):
                if 0 <= r0 + r < size and 0 <= c0 + c < size:
                    is_black = (0 <= r <= 6 and (c == 0 or c == 6)) or \
                               (0 <= c <= 6 and (r == 0 or r == 6)) or \
                               (2 <= r <= 4 and 2 <= c <= 4)
                    set_func(r0 + r, c0 + c, is_black)

    draw_finder(0, 0)
    draw_finder(0, size - 7)
    draw_finder(size - 7, 0)

    for i in range(8, size - 8):
        set_func(6, i, i % 2 == 0)
        set_func(i, 6, i % 2 == 0)

    if spec["alignment"]:
        for ar in spec["alignment"]:
            for ac in spec["alignment"]:
                if (ar <= 8 and ac <= 8) or (ar <= 8 and ac >= size - 8) or (ar >= size - 8 and ac <= 8):
                    continue
                for r in range(-2, 3):
                    for c in range(-2, 3):
                        set_func(ar + r, ac + c, max(abs(r), abs(c)) != 1)

    set_func(size - 8, 8, True)
    for i in range(9):
        if 0 <= i < size:
            if not is_func[8][i]: set_func(8, i, False)
            if not is_func[i][8]: set_func(i, 8, False)
    for i in range(8):
        if 0 <= size - 1 - i < size:
            if not is_func[8][size - 1 - i]: set_func(8, size - 1 - i, False)
            if not is_func[size - 1 - i][8]: set_func(size - 1 - i, 8, False)

    byte_idx = 0
    bit_idx = 7
    up = True

    for right in range(size - 1, 0, -2):
        if right == 6:
            right -= 1
        for vert in range(size):
            r = size - 1 - vert if up else vert
            for c in (right, right - 1):
                if not is_func[r][c]:
                    bit = False
                    if byte_idx < len(final_codewords):
                        bit = ((final_codewords[byte_idx] >> bit_idx) & 1) == 1
                        bit_idx -= 1
                        if bit_idx < 0:
                            bit_idx = 7
                            byte_idx += 1
                    matrix[r][c] = bit
        up = not up

    final_result = [[False] * size for _ in range(size)]
    for r in range(size):
        for c in range(size):
            if is_func[r][c]:
                final_result[r][c] = bool(matrix[r][c])
            else:
                final_result[r][c] = bool(matrix[r][c]) ^ (((r + c) % 2) == 0)

    format_bits = 0x77C4
    def get_fbit(i):
        return ((format_bits >> i) & 1) == 1

    for i in range(6):
        final_result[8][i] = get_fbit(i)
    final_result[8][7] = get_fbit(6)
    final_result[8][8] = get_fbit(7)
    final_result[7][8] = get_fbit(8)
    for i in range(9, 15):
        final_result[14 - i][8] = get_fbit(i)

    for i in range(8):
        final_result[size - 1 - i][8] = get_fbit(i)
    for i in range(8, 15):
        final_result[8][size - 15 + i] = get_fbit(i)
    final_result[size - 8][8] = True  

    return final_result

def get_qr_pixmap(text: str):
    """Renders QR code to a high-contrast QPixmap with standard 4-module quiet zone margin."""
    try:
        import qrcode
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=8,
            border=4,
        )
        qr.add_data(text)
        qr.make(fit=True)
        matrix = qr.get_matrix()
        border = 0
    except Exception:
        matrix = generate_qr_matrix(text)
        border = 4

    size = len(matrix)
    scale = 8
    total_dim = (size + border * 2) * scale
    pixmap = QPixmap(total_dim, total_dim)
    pixmap.fill(QColor("#ffffff"))

    painter = QPainter(pixmap)
    painter.setBrush(QColor("#000000"))
    painter.setPen(Qt.PenStyle.NoPen)

    for r in range(size):
        for c in range(size):
            if matrix[r][c]:
                painter.drawRect((c + border) * scale, (r + border) * scale, scale, scale)

    painter.end()
    return pixmap