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

Lần chạy đầu, skill tự tạo venv `~/.cache/datdb-uienv` (psd-tools, numpy, pillow; khoảng 1 phút) và tự copy
`UIBuilder.cs` vào `Assets/_Project/Editor/` của project. Không cần làm tay.

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

Người sửa plugin: tăng `version` trong `plugins/datdb-unity/.claude-plugin/plugin.json` (và trong
`.claude-plugin/marketplace.json`) mỗi lần push bản mới. Muốn thử trước khi push:
`/plugin marketplace add <đường dẫn tới thư mục này>`.

## Cách dùng

Mở Claude Code ở thư mục gốc project Unity (thư mục chứa `Assets/`), mở Unity Editor, rồi gõ `/create-ui` và
chọn skill (trong danh sách có thể hiện là `datdb-unity:create-ui`), kèm nguồn:

```
/create-ui Psd/BackToHomeUI.psd
/create-ui https://www.figma.com/design/<fileKey>/...?node-id=12-34
/create-ui Mockups/ShopUI.png
```

- Prefab đã tồn tại: skill hỏi ghi đè (`--replace`, giữ GUID) hay đặt tên khác (`--name X`).
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
