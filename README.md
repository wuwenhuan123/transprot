# TransProt

Windows 轻量级屏幕 OCR 工具 MVP。

当前版本实现了这些能力：

- 系统托盘常驻
- 应用启动后立即显示可拖拽、可缩放的半透明框选区域
- 点击框选区域中的 `识别` 按钮后，执行截图 + OCR 识别
- 识别结果直接显示在同一块框选区域内
- 设置页保留原有翻译配置，便于后续恢复真实翻译能力
- `--self-check` 运行环境自检

> 当前版本先聚焦 OCR 识别，主流程不会调用翻译接口。

## Quick Start

1. 创建虚拟环境。
2. 安装桌面依赖：`pip install -e .[desktop]`
3. 安装 OCR 依赖：`pip install -e .[ocr]`
4. 运行自检：`python -m transprot --self-check`
5. 启动桌面应用：`python -m transprot`

## 交互方式

1. 启动应用后，桌面上会出现一个半透明矩形区域。
2. 拖拽或缩放这个区域，使其覆盖到你要识别的文字。
3. 点击区域右上角的 `识别` 按钮。
4. 程序会短暂隐藏该区域、完成截图和 OCR，再把识别结果显示回区域内。

## 翻译配置说明

设置页中的 Provider、Endpoint、API key、Model、Timeout 仍会保留并持久化，
但当前 OCR-only 版本不会在主流程中使用这些配置。

## 打包

安装打包依赖后运行：

```powershell
python -m PyInstaller --noconfirm --windowed --onedir --name TransProt --collect-all paddleocr --paths src src/transprot/__main__.py
```
