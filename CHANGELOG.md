# Changelog

## 1.6.0 (UIBuilder 8)

Fixes
- PSD point text căn trái/phải bị lệch ~400 px: rect tạm giờ bắt đầu, ở giữa hoặc kết thúc tại `anchor_x` theo kiểu căn.
- PSD paragraph (box) text: dùng khung của Photoshop (`place: rect`, `wrap: true`, căn từ trên xuống) thay vì coi gốc
  khung là baseline.
- Tên UI (frame Figma, file PSD/PNG, `--name`) bỏ các ký tự không dùng được trong tên file/thư mục (`Popup / Shop` →
  `Popup_Shop`).
- `setup.py` luôn in JSON kể cả khi tạo venv lỗi (thiếu `python3-venv`, venv hỏng); gợi ý cách sửa trong `errors`.
- Justification 3–6 của Photoshop (justify) giờ dùng căn của dòng cuối, có cảnh báo.

Safety
- SKILL.md / README nói rõ `--replace` làm mất gì (component, onClick, override, tham chiếu tới object con).
- Lỗi sau bước validate báo `PARTIAL: …` liệt kê mọi thay đổi đã làm (không rollback).
- Gói Python ghim theo khoảng đã test (`psd-tools>=1.11,<1.12`, `numpy<3`, `pillow<13`); venv tự cài lại khi danh sách đổi.
- Sprite mới: importer Max Size được nâng cho vừa ảnh; sprite dùng lại bị thu nhỏ thì có cảnh báo.
- Đặt Read/Write cho atlas font giờ được báo trong `warnings`.
- `spec.frame` sai được báo lỗi thay vì exception.

Performance
- Spec writers đọc mỗi ảnh một lần mỗi build (cache pixel + slice info), so kích thước trước khi so pixel.
- Sprite mới được import theo batch (`StartAssetEditing`), không còn refresh từng file.

Other
- Thứ tự chọn font asset cố định (asset chính trước `… Fallback`, rồi theo đường dẫn).
- Text bị xoay/skew/kéo giãn trong PSD có cảnh báo.
- `--name` / `--names` thiếu giá trị hoặc option lạ báo lỗi rõ ràng.
- SKILL.md gọn lại, chi tiết chuyển sang `reference/spec.md`; thêm `allowed-tools` cho các tool chỉ đọc.
- Version chỉ còn khai báo trong `plugin.json`.
- Thêm `tests/run_tests.py` (unittest, không cần pytest).
