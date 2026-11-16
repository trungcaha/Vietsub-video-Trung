"""Chuyển số, ngày tháng, giờ, phần trăm, tiền tệ, đơn vị và ký hiệu sang chữ tiếng Việt trước khi đọc TTS.

G-OmniVoice đọc sai khi gặp chữ số và ký hiệu ("6.3" -> "sáu ba", "10/10/2026" -> "mười mờn...").
Gọi normalize(text) cho từng câu trước model.generate(); phụ đề vẫn giữ chữ gốc.

Thử nhanh:  python vn_textnorm.py "Tăng 3% lên 6.3 tỷ đô ngày 10/10/2026"
"""
import re

DIGITS = ["không", "một", "hai", "ba", "bốn", "năm", "sáu", "bảy", "tám", "chín"]
SCALES = ["", "nghìn", "triệu", "tỷ", "nghìn tỷ", "triệu tỷ", "tỷ tỷ"]


def _two(n, full):
    """0..99. full=True nghĩa là nhóm đứng sau hàng trăm/nhóm khác (cần 'linh')."""
    t, u = divmod(n, 10)
    if t == 0:
        return ("linh " if full else "") + DIGITS[u] if u else ""
    head = "mười" if t == 1 else DIGITS[t] + " mươi"
    if u == 0:
        return head
    if u == 5:
        tail = "lăm"
    elif u == 1 and t > 1:
        tail = "mốt"
    elif u == 4 and t > 1:
        tail = "tư"
    else:
        tail = DIGITS[u]
    return head + " " + tail


def _three(n, full):
    h, r = divmod(n, 100)
    if h == 0 and not full:
        return _two(r, False)
    out = DIGITS[h] + " trăm"
    if r:
        out += " " + _two(r, True)
    return out


def read_int(n):
    n = int(n)
    if n == 0:
        return "không"
    if n < 0:
        return "âm " + read_int(-n)
    groups = []
    while n:
        n, g = divmod(n, 1000)
        groups.append(g)
    if len(groups) > len(SCALES):
        return " ".join(DIGITS[int(c)] for c in str(n))
    words = []
    for i in range(len(groups) - 1, -1, -1):
        g = groups[i]
        if g == 0:
            continue
        lead = i == len(groups) - 1
        words.append(_three(g, not lead))
        if SCALES[i]:
            words.append(SCALES[i])
    return " ".join(words)


def read_digits(s):
    return " ".join(DIGITS[int(c)] for c in s if c.isdigit())


def read_decimal(int_part, frac):
    out = read_int(int_part) + " phẩy "
    # 6,3 -> sáu phẩy ba ; 15,25 -> mười lăm phẩy hai mươi lăm ; 0,05 -> không phẩy không năm
    if frac.startswith("0") or len(frac) > 2:
        return out + read_digits(frac)
    return out + read_int(frac)


def _num_token(s):
    """Chuỗi số có thể có dấu nghìn/thập phân -> chữ."""
    s = s.strip()
    neg = s.startswith("-")
    s = s.lstrip("-+")
    if re.fullmatch(r"\d{1,3}([.,]\d{3}){2,}", s):           # 1.250.000 / 1,250,000
        val = read_int(re.sub(r"[.,]", "", s))
    elif re.fullmatch(r"\d{1,3}[.,]\d{3}", s):                # 1.250 / 1,250 -> nghìn
        val = read_int(re.sub(r"[.,]", "", s))
    elif re.fullmatch(r"\d+[.,]\d+", s):                      # 6.3 / 6,3 -> thập phân
        a, b = re.split(r"[.,]", s)
        val = read_decimal(a, b)
    elif re.fullmatch(r"0\d{8,}", s):                         # số điện thoại
        val = read_digits(s)
    elif s.isdigit():
        val = read_int(s) if len(s) <= 15 else read_digits(s)
    else:
        return s
    return ("âm " if neg else "") + val


NUM = r"-?\d+(?:[.,]\d+)*"

MONTHS = {1: "một", 4: "tư"}


def _month(m):
    m = int(m)
    return MONTHS.get(m, read_int(m))


ABBR = [
    (r"\bTP\.?\s?HCM\b", "thành phố Hồ Chí Minh"),
    (r"\bTP\.?\s?Hồ Chí Minh\b", "thành phố Hồ Chí Minh"),
    (r"\bTP\.(?=\s)", "thành phố"),
    (r"\bv\.v\.?", "vân vân"),
    (r"\.(com|vn|net|org)\b", r" chấm \1"),
    (r"\bUBND\b", "ủy ban nhân dân"),
    (r"\bTW\b", "trung ương"),
    (r"\bThS\.", "thạc sĩ"),
    (r"\bTS\.", "tiến sĩ"),
    (r"\bBS\.", "bác sĩ"),
    (r"\bPGS\.", "phó giáo sư"),
    (r"\bGS\.", "giáo sư"),
    (r"\bAI\b", "ây ai"),
    (r"\bCEO\b", "xi i âu"),
    (r"\bVN\b", "Việt Nam"),
]

UNITS = [  # đơn vị đứng ngay sau số
    (r"km/h", "ki lô mét trên giờ"),
    (r"m²|m2", "mét vuông"), (r"m³|m3", "mét khối"), (r"km²|km2", "ki lô mét vuông"),
    (r"km", "ki lô mét"), (r"cm", "xen ti mét"), (r"mm", "mi li mét"), (r"m", "mét"),
    (r"kg", "ki lô gam"), (r"mg", "mi li gam"), (r"g", "gam"), (r"tấn", "tấn"),
    (r"ml", "mi li lít"), (r"l", "lít"),
    (r"°C|ºC|độ C", "độ xê"), (r"°F", "độ ép"), (r"°", "độ"),
    (r"GB", "ghi ga bai"), (r"MB", "mê ga bai"), (r"TB", "tê ra bai"), (r"Hz", "héc"),
    (r"kW", "ki lô oát"), (r"W", "oát"), (r"V", "vôn"), (r"mAh", "mi li am pe giờ"),
    (r"ha", "héc ta"),
    (r"VNĐ|VND|vnđ|vnd|đồng|đ", "đồng"),
    (r"USD|usd", "đô la Mỹ"), (r"\$", "đô la"), (r"€|EUR", "ơ rô"), (r"¥", "yên"),
    (r"k|K", "nghìn"), (r"tr", "triệu"),
    (r"%", "phần trăm"),
    (r"x", "lần"),
]
UNIT_RE = re.compile(
    r"(?<![\w.,])(" + NUM + r")\s?(" + "|".join(u for u, _ in UNITS) + r")(?![\wÀ-ỹ²³])")
UNIT_MAP = [(re.compile(r"(?:" + u + r")\Z"), w) for u, w in UNITS]


def _unit(m):
    num, unit = m.group(1), m.group(2)
    word = next(w for rx, w in UNIT_MAP if rx.match(unit))
    return _num_token(num) + " " + word


def normalize(text):
    t = text

    # chữ viết tắt
    for pat, rep in ABBR:
        t = re.sub(pat, rep, t)

    # ngày dd/mm/yyyy, dd-mm-yyyy, dd.mm.yyyy
    def date_full(m):
        pre = m.group(1) or ""
        d, mo, y = m.group(2), m.group(3), m.group(4)
        lead = "" if pre.strip().lower() in ("ngày", "mùng", "hôm") else "ngày "
        return f"{pre}{lead}{read_int(d)} tháng {_month(mo)} năm {read_int(y)}"
    t = re.sub(r"(\b(?:ngày|mùng|hôm)\s+)?\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})\b", date_full, t, flags=re.I)

    # tháng mm/yyyy
    def month_year(m):
        pre = m.group(1) or ""
        lead = "" if pre.strip().lower() == "tháng" else "tháng "
        return f"{pre}{lead}{_month(m.group(2))} năm {read_int(m.group(3))}"
    t = re.sub(r"(\btháng\s+)?\b(\d{1,2})/(\d{4})\b", month_year, t, flags=re.I)

    # ngày dd/mm
    def day_month(m):
        pre = m.group(1) or ""
        d, mo = int(m.group(2)), int(m.group(3))
        if not (1 <= d <= 31 and 1 <= mo <= 12):
            return m.group(0)
        lead = "" if pre.strip().lower() in ("ngày", "mùng", "hôm") else "ngày "
        return f"{pre}{lead}{read_int(d)} tháng {_month(mo)}"
    t = re.sub(r"(\b(?:ngày|mùng|hôm)\s+)?\b(\d{1,2})/(\d{1,2})\b(?!/)", day_month, t, flags=re.I)

    # "tháng 4" -> tháng tư, "tháng 1" -> tháng một
    t = re.sub(r"\b(tháng)\s+(\d{1,2})\b", lambda m: f"{m.group(1)} {_month(m.group(2))}", t, flags=re.I)

    # giờ 8:30, 8h30, 8g30, 8h
    def clock(h, mi=None, s=None):
        out = read_int(h) + " giờ"
        if mi and int(mi):
            out += " " + read_int(mi) + " phút"
        if s and int(s):
            out += " " + read_int(s) + " giây"
        return out
    t = re.sub(r"\b(\d{1,2}):(\d{2})(?::(\d{2}))?\b", lambda m: clock(*m.groups()), t)
    t = re.sub(r"\b(\d{1,2})[hg](\d{2})?p?(?![\w])", lambda m: clock(m.group(1), m.group(2)), t)

    # khoảng 3-5, 10–15 (không phải ngày đã đổi ở trên)
    t = re.sub(r"(?<![\w.,])(\d+(?:[.,]\d+)?)\s?[-–—]\s?(\d+(?:[.,]\d+)?)(?![\w/])",
               lambda m: f"{_num_token(m.group(1))} đến {_num_token(m.group(2))}", t)

    # tiền tệ đứng trước số: $6.3, $100
    t = re.sub(r"\$\s?(" + NUM + r")", lambda m: _num_token(m.group(1)) + " đô la", t)
    t = re.sub(r"€\s?(" + NUM + r")", lambda m: _num_token(m.group(1)) + " ơ rô", t)

    # số + đơn vị / % / tiền tệ
    t = UNIT_RE.sub(_unit, t)

    # "/năm", "/tháng", "/người" sau con số -> "mỗi năm"
    t = re.sub(r"\s?/\s?(năm|tháng|ngày|tuần|giờ|người|kg|lít|km|tháng|lần|suất|cái|chiếc|hộp)\b", r" mỗi \1", t)

    # thứ tự: thứ 1 -> thứ nhất, thứ 4 -> thứ tư
    t = re.sub(r"\b(thứ|hạng|lần thứ)\s+1\b", r"\1 nhất", t, flags=re.I)
    t = re.sub(r"\b(thứ|hạng|lần thứ)\s+4\b", r"\1 tư", t, flags=re.I)

    # số âm đứng riêng: -5
    t = re.sub(r"(?<![\w])-(\d+(?:[.,]\d+)?)\b", lambda m: "âm " + _num_token(m.group(1)), t)

    # số còn lại
    t = re.sub(r"(?<![\w])\d+(?:[.,]\d+)*(?![\w])", lambda m: _num_token(m.group(0)), t)
    t = re.sub(r"\d+", lambda m: _num_token(m.group(0)), t)  # số dính chữ (F1, 4G...)

    # ký hiệu
    for sym, word in [("&", " và "), ("+", " cộng "), ("=", " bằng "), ("~", " khoảng "), ("≈", " khoảng "),
                      ("@", " a còng "), ("#", " thăng "), (">", " lớn hơn "), ("<", " nhỏ hơn "),
                      ("%", " phần trăm "), ("/", " trên "), ("×", " nhân "), ("*", " ")]:
        t = t.replace(sym, word)
    t = re.sub(r"[\"“”«»_|^`]", "", t)
    t = re.sub(r"\s+([,.!?;:…])", r"\1", t)
    t = re.sub(r"\s{2,}", " ", t).strip()
    return t


if __name__ == "__main__":
    import sys
    for line in (sys.argv[1:] or [sys.stdin.read()]):
        for l in line.splitlines():
            if l.strip():
                print(normalize(l))
