# datdb-unity

Plugin Unity cho Claude Code. Hiện có skill:

- **`create-ui`**: dựng một màn hình uGUI thành prefab `Assets/_Project/Prefabs/UI/<Tên UI>.prefab` từ một
frame Figma, một file PSD hoặc một ảnh PNG mockup, dùng lại sprite và font TMP có sẵn trong project.

Chạy được trên macOS, Linux và Windows.

## Yêu cầu trên mỗi máy

| Cần có | Ghi chú |
|---|---|
| Claude Code | CLI, app desktop (tab Code) hoặc extension IDE. Trên Windows, Claude Code cần Git for Windows (Git Bash). |
| Python 3.9+ | macOS: thường đã có `python3`. **Windows: mặc định KHÔNG có.** Cài từ python.org (tick "Add python.exe to PATH") hoặc `winget install Python.Python.3.12`. |
| Unity 6 + Unity MCP | Package `com.unity.ai.assistant` (đã test với 2.21.0-pre.2, Unity 6000.0.71f1). Bật MCP server trong Edit → Project Settings → AI → Unity MCP Server và kết nối với Claude Code. Skill chỉ cần 2 tool mặc định: `Unity_RunCommand`, `Unity_GetConsoleLogs`. |
| Figma MCP | Chỉ khi dựng từ link Figma (plugin `figma` của Claude Code). |

Lần chạy đầu, skill tự tạo venv `~/.cache/datdb-uienv` (psd-tools 1.11.x, numpy, pillow trong các khoảng phiên bản đã
test; khoảng 1 phút) và tự copy `UIBuilder.cs` vào `Assets/_Project/Editor/` của project. Không cần làm tay. Khi danh
sách gói trong `setup.py` đổi, venv tự cài lại. Venv hỏng thì xoá thư mục `~/.cache/datdb-uienv` rồi chạy lại. Trên
Debian/Ubuntu cần gói `python3-venv`.

Skill tự cho phép sẵn các tool chỉ đọc (`Unity_GetConsoleLogs`, các tool đọc của Figma), nên bớt bị hỏi quyền.
`Unity_RunCommand` chạy C# tuỳ ý nên vẫn hỏi mỗi lần. Muốn bỏ hỏi thì tự thêm nó vào permission allow của project.
Tên tool phụ thuộc tên MCP server: skill giả định server Unity tên `unity-mcp`.

## Cấu trúc project Unity

```
Assets/_Project/
  Images/UI/Common/        ảnh dùng chung từ 2 UI trở lên
  Images/UI/<Tên UI>/      ảnh chỉ UI đó dùng
  Fonts/                   TMP SDF font asset (+ material viền "<font> Outline <Màu>.mat")
  Prefabs/UI/              prefab đầu ra
  Editor/UIBuilder.cs      skill tự cài
```

Font phải có sẵn dạng TMP SDF trong `Fonts/`. Thiếu font thì skill dừng ngay và báo font nào cần tạo.

## Cài đặt

Repo: https://github.com/dat-dangba/datdb-unity-tools

Chạy trong Claude Code (terminal `claude`), hai lệnh, mỗi máy một lần:

```
/plugin marketplace add dat-dangba/datdb-unity-tools
```

```
/plugin install datdb-unity@datdb-unity-tools
```

Lệnh đầu thêm marketplace `datdb-unity-tools` từ repo này, lệnh sau cài plugin `datdb-unity` trong đó (gồm skill
`create-ui`). Nếu repo
để private, máy phải đăng nhập GitHub được (clone được repo bằng SSH key hoặc credential).

Cập nhật khi có bản mới:

```
/plugin marketplace update datdb-unity-tools
```

Người sửa plugin:
- Tăng `version` trong `plugins/datdb-unity/.claude-plugin/plugin.json` mỗi lần push bản mới. Chỉ khai báo version
  ở đây (không ghi vào `marketplace.json`) để hai nơi không lệch nhau. Ghi thay đổi vào `CHANGELOG.md`.
- Sửa `unity/UIBuilder.cs` thì tăng `UIBuilder.Version`.
- Chạy test trước khi push (chỉ cần venv của skill):
  `~/.cache/datdb-uienv/bin/python -I -B plugins/datdb-unity/skills/create-ui/tests/run_tests.py`
- Muốn thử trước khi push: `/plugin marketplace add <đường dẫn tới thư mục này>`.

## Cách dùng

Mở Claude Code ở thư mục gốc project Unity (thư mục chứa `Assets/`), mở Unity Editor, rồi gõ `/create-ui` và
chọn skill (trong danh sách có thể hiện là `datdb-unity:create-ui`), kèm nguồn:

```
/create-ui Psd/BackToHomeUI.psd
/create-ui https://www.figma.com/design/<fileKey>/...?node-id=12-34
/create-ui Mockups/ShopUI.png
```

- Prefab đã tồn tại: skill hỏi ghi đè (`--replace`) hay đặt tên khác (`--name X`). Ghi đè giữ GUID của prefab nhưng
  dựng lại toàn bộ cây con, nên script, onClick và chỉnh sửa tay trong prefab bị mất, override trong scene và tham
  chiếu tới object con cũng hỏng.
- Đổi tên layer cho chuẩn (PascalCase + hậu tố loại: `PopupFrame`, `TitleText`, `CloseButton`…): đặt file
  `<Tên>.names.json` cạnh PSD/PNG, ví dụ `{"Group 5": "PopupFrame", "Are you sure?": "TitleText"}`.
- Layer nằm trong layer khác sẽ tự thành con của nó (tắt bằng `--no-nest`).
- Ảnh giống nhau nhưng khác chiều rộng (nút kéo dài) được dùng chung một sprite, đặt border 9-slice tự động và
  Image Type là Sliced.
- PNG mockup chỉ dựng từ sprite đã có trong `Images/UI`; thiếu ảnh nào skill sẽ báo vị trí để bạn thêm vào.

## Lưu ý

- Thêm skill mới cho plugin: tạo `plugins/datdb-unity/skills/<tên skill>/SKILL.md`, tăng `version`, push.
- Skill không mở hay sửa scene nào; bạn tự kéo prefab vào Canvas.
- `AssetDatabase.DeleteAsset` bị chặn qua Unity MCP, nên ảnh hoặc thư mục không còn dùng sẽ được báo để bạn tự xoá.
- Trên Windows, phần Python và Unity chưa được chạy thử trên máy thật; báo lại nếu bước setup lỗi.
