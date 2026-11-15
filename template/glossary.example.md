# Từ điển nhân vật & Quy tắc dịch thuật (Mẫu: Series "汪汪喵爸" — Bố Cún & Mèo Con)

> Khi tạo dự án mới bằng `init_project.py`, hãy cập nhật file `glossary.md` này theo đúng nhân vật, xưng hô và bối cảnh của kênh mới. Các file cấu hình vai đọc (`role`) phải khớp với khóa trong `project.json`.

## 1. Từ điển nhân vật & Thuật ngữ xuyên suốt
- **大黄 / 汪爸 / 喵爸** -> **Đại Hoàng** / **Bố Cún** (gọi Tiểu Quất là *con* hoặc *Tiểu Quất*, xưng *bố* hoặc *ta/tôi* tùy cảnh).
- **小橘 / 小橙子** -> **Tiểu Quất** (mèo cam nhỏ lễ phép, gọi Đại Hoàng là *Bố Cún* / *Bố ơi*, gọi Biên Mục là *anh Biên* / *chú Biên*).
- **边哥 / 边牧** -> **Anh Biên** (chó Border Collie thông minh, bình tĩnh).
- **多吉** -> **Đa Cát** (tên người/bác nông dân trong truyện).
- **头狼 / 狼王** -> **Sói Đầu Đàn**.
- **狗贩子** -> **Bọn trộm chó** / **Lái chó**.

## 2. Quy ước phân vai (`role` trong `project.json`)
Kết hợp ngữ cảnh câu thoại với chỉ số `f0_hz` và `acoustic_hint` trong file `_zh.json`:

| Mã `role` | Nhân vật / Vai | Gợi ý âm học (`f0_hz`) | Giọng TTS | Cao độ (`Hz`) |
|---|---|---|---|---|
| `bo_cho` | Bố Chó Đại Hoàng / chó lớn ấm áp | `< 165 Hz` | `vi-VN-NamMinhNeural` | `-10Hz` |
| `meo_con` | Mèo con Tiểu Quất / thú nhỏ / trẻ nhỏ | `>= 225 Hz` | `vi-VN-HoaiMyNeural` | `+18Hz` |
| `bien_muc` | Anh Biên / chó bạn trẻ / sói trẻ | `155–235 Hz` | `vi-VN-NamMinhNeural` | `+2Hz` |
| `ke_xau` | Kẻ trộm chó / Sói dữ / phản diện | Trầm gằn | `vi-VN-NamMinhNeural` | `-18Hz` |
| `dan_chuyen` | Lời dẫn chuyện / tổng kết / giọng nữ | Trung tính / nữ | `vi-VN-HoaiMyNeural` | `+0Hz` |

## 3. Quy tắc dịch súc tích chống nuốt chữ & khớp Karaoke `\kf`
1. **Giữ nguyên 100%** số lượng `segments`, đúng từng `id`, `start`, `end`, `duration`, `zh_text` từ `_zh.json`. Không gộp, không tách, không xóa dòng.
2. **Giới hạn độ dài**: `vi_text` phải súc tích, tự nhiên như thoại phim hoạt hình; số từ đơn tiếng Việt tối đa xấp xỉ `max(3, round(duration * 3.8))` (không vượt `max(6, round(duration * 4.5))`) để TTS không bị ép tua quá `atempo <= 1.48`.
3. **Không giữ chữ Hán** (`汉字`) trong `vi_text` hay `vi_file_stem`. Hạn chế số Ả Rập trần gây đọc sai (viết thành chữ: `"một"`, `"hai"`, `"ba người"`).
4. **Đặt tên tập sạch**:
   - `vi_title_display`: Tên tiếng Việt có dấu tự nhiên, ngắn gọn (vd: `"Tập 01: Bình Minh Trên Thảo Nguyên"`).
   - `vi_file_stem`: Dạng `<index:02d>_<Ten_Khong_Ky_Tu_Dac_Biet>`, tối đa ~50 ký tự, không có `<>:"/\|?*` hay chữ Hán, dùng `_` thay khoảng trắng (vd: `"01_Binh_Minh_Thao_Nguyen"`).
5. **Metadata gốc**: Luôn sao chép chính xác `width`, `height`, `duration_sec`, `hardsub_band` từ `_zh.json` sang `_vi.json`.
