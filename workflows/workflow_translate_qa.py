# -*- coding: utf-8 -*-
r"""Workflow chuẩn cho công cụ run_workflow:
Điều phối dịch thuật phân vai song song & cổng kiểm định chất lượng (QA) kịch bản tiếng Việt.
Đọc PROJECT_DIR từ: Args['project_dir'] -> biến môi trường VIETSUB_PROJECT_DIR -> CWD -> WORKSPACES[0].
"""
import json
import os
import re
from pathlib import Path


def _resolve_project_dir() -> Path:
    g_args = globals().get("args") or {}
    if isinstance(g_args, dict) and g_args.get("project_dir"):
        return Path(str(g_args["project_dir"])).expanduser().resolve()

    env_dir = os.environ.get("VIETSUB_PROJECT_DIR", "").strip()
    if env_dir:
        return Path(env_dir).expanduser().resolve()

    cwd = Path.cwd().resolve()
    if (cwd / "project.json").exists():
        return cwd

    ws = globals().get("WORKSPACES") or ()
    if ws:
        return Path(ws[0]).expanduser().resolve()

    return cwd


PROJ_DIR = _resolve_project_dir()
PROJ_CFG_PATH = PROJ_DIR / "project.json"
GLOSSARY_PATH = PROJ_DIR / "glossary.md"
RAW_MANIFEST = PROJ_DIR / "raw" / "posts_manifest.json"
TRANS_DIR = PROJ_DIR / "transcripts"
OUT_VI_DIR = PROJ_DIR / "translations"
OUT_VI_DIR.mkdir(parents=True, exist_ok=True)

if not PROJ_CFG_PATH.exists():
    raise FileNotFoundError(
        f"Không tìm thấy {PROJ_CFG_PATH}. Hãy truyền Args={{'project_dir': '...'}} "
        "hoặc đặt biến môi trường VIETSUB_PROJECT_DIR trỏ tới thư mục dự án."
    )

PROJ_CFG = json.loads(PROJ_CFG_PATH.read_text(encoding="utf-8"))
CHANNEL_NAME = PROJ_CFG.get("channel_name") or PROJ_CFG.get("project_slug") or "Douyin Channel"
ROLES_CFG = PROJ_CFG.get("roles") or {
    "dan_chuyen": {"label": "Dẫn Chuyện", "description": "Giọng đọc mặc định"}
}
VALID_ROLES = set(ROLES_CFG.keys())
GLOSSARY_TEXT = (
    GLOSSARY_PATH.read_text(encoding="utf-8").strip()
    if GLOSSARY_PATH.exists()
    else "(Chưa có glossary.md — giữ xưng hô nhất quán, câu thoại súc tích tự nhiên)"
)

CJK_RE = re.compile(r"[\u4e00-\u9fff]")
FORBIDDEN_STEM_RE = re.compile(r'[<>:"/\\|?*]')


def _roles_markdown_list() -> str:
    lines = []
    for idx, (rkey, info) in enumerate(ROLES_CFG.items(), 1):
        label = info.get("label") or rkey
        desc = info.get("description") or ""
        voice = info.get("voice") or ""
        pitch = info.get("pitch") or "+0Hz"
        lines.append(f'{idx}. `"{rkey}"`: **{label}** — {desc} (TTS: `{voice}`, pitch `{pitch}`)')
    return "\n".join(lines)


def validate_vi_file(ep_key: str) -> list:
    zh_path = TRANS_DIR / f"{ep_key}_zh.json"
    vi_path = OUT_VI_DIR / f"{ep_key}_vi.json"
    issues = []
    if not zh_path.exists():
        return [f"{ep_key}: thiếu transcript gốc {zh_path.name}"]
    if not vi_path.exists():
        return [f"{ep_key}: thiếu file dịch {vi_path.name}"]

    try:
        zh = json.loads(zh_path.read_text(encoding="utf-8"))
        vi = json.loads(vi_path.read_text(encoding="utf-8"))
    except Exception as e:
        return [f"{ep_key}: JSON hỏng ({e})"]

    zh_segs = zh.get("segments") or []
    vi_segs = vi.get("segments") or []
    if len(zh_segs) != len(vi_segs):
        return [f"{ep_key}: lệch số lượng segments (zh={len(zh_segs)} vs vi={len(vi_segs)})"]

    if not (vi.get("vi_title_display") or "").strip():
        issues.append(f"{ep_key}: thiếu vi_title_display")
    stem = (vi.get("vi_file_stem") or "").strip()
    if not stem:
        issues.append(f"{ep_key}: thiếu vi_file_stem")
    else:
        if CJK_RE.search(stem):
            issues.append(f"{ep_key}: vi_file_stem còn sót chữ Hán")
        if FORBIDDEN_STEM_RE.search(stem):
            issues.append(f"{ep_key}: vi_file_stem chứa ký tự cấm")

    for zs, vs in zip(zh_segs, vi_segs):
        sid = zs["id"]
        if vs.get("id") != sid:
            issues.append(f"{ep_key} seg {sid}: sai id ({vs.get('id')})")
        role = vs.get("role")
        if role not in VALID_ROLES:
            issues.append(f"{ep_key} seg {sid}: role không hợp lệ '{role}'")
        vt = (vs.get("vi_text") or "").strip()
        if not vt:
            issues.append(f"{ep_key} seg {sid}: vi_text rỗng")
        elif CJK_RE.search(vt):
            issues.append(f"{ep_key} seg {sid}: vi_text còn sót chữ Hán '{vt}'")
        max_words = max(6, round(float(zs.get("duration", 1.0)) * 4.5))
        if len(vt.split()) > max_words + 4:
            issues.append(
                f"{ep_key} seg {sid}: hơi dài ({len(vt.split())} từ / {zs['duration']}s -> nên rút gọn <= {max_words} từ)"
            )
    return issues


def make_batch_prompt(batch_keys: list) -> str:
    zh_files_list = "\n".join(
        f"  - Đọc: `{TRANS_DIR / f'{k}_zh.json'}`  -->  Ghi: `{OUT_VI_DIR / f'{k}_vi.json'}`"
        for k in batch_keys
    )
    roles_block = _roles_markdown_list()
    sample_role = next(iter(VALID_ROLES))
    return f"""Dịch kịch bản & phân vai lồng tiếng tiếng Việt cho kênh **{CHANNEL_NAME}**, lô tập: {", ".join(batch_keys)}

## File cần xử lý (Đọc bằng `read_file`, ghi kết quả bằng `write_file` — KHÔNG truyền `ArtifactMetadata`):
{zh_files_list}

## Từ điển nhân vật & Quy ước dự án (`glossary.md`):
{GLOSSARY_TEXT}

## Mã vai hợp lệ cho trường `"role"` (kết hợp ngữ cảnh + `f0_hz` / `acoustic_hint` trong `_zh.json`):
{roles_block}

## Quy tắc CỰC KỲ QUAN TRỌNG (chống nuốt chữ & khớp Karaoke `\\kf`):
1. **Giữ NGUYÊN 100% số lượng `segments`, đúng từng `id`, `start`, `end`, `duration`, `zh_text`** từ file `_zh.json`. Tuyệt đối không gộp, không tách, không xóa dòng.
2. **Độ dài `vi_text` phải súc tích, tự nhiên như thoại phim hoạt hình**, số từ đơn tối đa xấp xỉ **`max(3, round(duration * 3.8))` từ** (không vượt `max(6, round(duration * 4.5))`) để TTS đọc vừa khít khung giờ `[start, end]` mà không bị ép tốc độ.
3. Không giữ bất kỳ chữ Hán (`汉字`) nào trong `vi_text` hay `vi_file_stem`; đổi số Ả Rập trần thành chữ tiếng Việt (vd: `"một"`, `"hai"`, `"ba người"`).
4. Đặt `vi_title_display` (tên tập tiếng Việt ngắn gọn có dấu) và `vi_file_stem` (dạng `<index:02d>_<Ten_Khong_Ky_Tu_Dac_Biet>`, tối đa ~50 ký tự, không có `<>:"/\\|?*`, dùng `_` thay khoảng trắng).
5. Cấu trúc JSON đầu ra ở mỗi file `_vi.json` (**Sao chép CHÍNH XÁC `width`, `height`, `duration_sec`, `hardsub_band` từ file `_zh.json` tương ứng**):
   ```json
   {{
     "ep_key": "...",
     "index": 1,
     "aweme_id": "...",
     "aweme_url": "...",
     "publish_date": "...",
     "title_zh": "...",
     "vi_title_display": "...",
     "vi_file_stem": "01_...",
     "width": 1080,
     "height": 1920,
     "duration_sec": 180.5,
     "hardsub_band": [1497, 1689],
     "segments": [
       {{
         "id": 1,
         "start": 0.5,
         "end": 2.8,
         "duration": 2.3,
         "role": "{sample_role}",
         "zh_text": "...",
         "vi_text": "..."
       }}
     ]
   }}
   ```

Sau khi ghi xong toàn bộ các file trong lô bằng `write_file`, gọi `finish` trả về danh sách các `ep_key` đã hoàn tất."""


g_args = globals().get("args") or {}
batch_size = max(1, int(g_args.get("batch_size", 4)))
model_tier = str(g_args.get("model") or "flash")

phase("Discover Pending Episodes")
if not RAW_MANIFEST.exists():
    raise FileNotFoundError(f"Chưa có {RAW_MANIFEST}")

manifest = json.loads(RAW_MANIFEST.read_text(encoding="utf-8"))
single_eps = [e["ep_key"] for e in manifest.get("episodes", []) if not e.get("is_compilation")]
log(f"Dự án: {PROJ_DIR} | Kênh: {CHANNEL_NAME} | Tập lẻ: {len(single_eps)}")

pending = [k for k in single_eps if validate_vi_file(k)]
log(f"Cần dịch mới / sửa lại: {len(pending)} tập")

if pending:
    phase("Parallel Character Translation")
    batches = [pending[i : i + batch_size] for i in range(0, len(pending), batch_size)]
    log(f"Chia thành {len(batches)} lô song song (tối đa {batch_size} tập/lô, model={model_tier}).")
    results = await parallel(
        batches,
        lambda b: agent(
            make_batch_prompt(b),
            schema={"type": "array", "items": {"type": "string"}},
            role=f"Translate {b[0][:4]}..{b[-1][:4]}",
            model=model_tier,
        ),
    )
    for r in results:
        log("Batch xong:", r)

phase("Translation QA Gate")
all_issues = []
for k in single_eps:
    all_issues.extend(validate_vi_file(k))

if all_issues:
    log(f"Phát hiện {len(all_issues)} vấn đề cần QA Agent sửa:")
    for it in all_issues[:40]:
        log("  -", it)
    issue_text = "\n".join(f"- {x}" for x in all_issues)
    qa_res = await agent(
        f"""Bạn là QA Kiểm định Kịch Bản Lồng Tiếng cho kênh {CHANNEL_NAME}.
Các lỗi sau vừa được phát hiện khi kiểm tra `{OUT_VI_DIR}` đối chiếu với `{TRANS_DIR}`:
{issue_text}

Hãy đọc các file bị lỗi tương ứng trong `{TRANS_DIR}` và `{OUT_VI_DIR}`, sửa dứt điểm toàn bộ lỗi:
- Khớp 100% số lượng `segments`, `id`, `start`, `end`, `duration`, `zh_text`.
- `role` thuộc `{sorted(VALID_ROLES)}`.
- `vi_text` không rỗng, không còn chữ Hán, rút gọn súc tích không vượt quá `max(6, round(duration * 4.5))` từ.
- Đủ `vi_title_display` và `vi_file_stem` sạch không ký tự cấm/chữ Hán.

Ghi đè bằng `write_file` (Overwrite=True, KHÔNG truyền `ArtifactMetadata`), rồi gọi `finish` báo cáo kết quả.""",
        schema={"type": "string"},
        role="Translation QA Fixer",
        model=model_tier,
    )
    log("QA Agent:", qa_res)

final_issues = []
for k in single_eps:
    final_issues.extend(validate_vi_file(k))

if final_issues:
    log(f"CẢNH BÁO: Còn {len(final_issues)} lưu ý nhỏ sau QA:")
    for it in final_issues[:20]:
        log("  !", it)
else:
    log(f"TOÀN BỘ {len(single_eps)} TẬP ĐÃ ĐẠT CHUẨN 100% SẴN SÀNG LỒNG TIẾNG & RENDER KARAOKE!")

log("DONE_WORKFLOW")
