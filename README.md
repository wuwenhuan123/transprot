# TransProt

Windows 轻量级屏幕 OCR + 翻译工具 MVP。

当前版本实现了这些能力：

- 系统托盘常驻
- 应用启动后立即显示可拖拽、可缩放的半透明框选区域
- 点击框选区域外侧的 `翻译` 按钮后，执行截图 + OCR + 大模型翻译
- 译文直接显示在同一块框选区域内
- 设置页支持配置百炼兼容接口、模型、目标语言与超时（默认 60 秒）
- API Key 保存在 Windows Credential Manager 中，不会明文写入 `config.json`
- 设置页支持刷新推荐文本模型列表，并允许手动输入模型名
- `--self-check` 运行环境自检

默认翻译方案使用阿里云百炼 OpenAI 兼容接口：

- Base URL：`https://dashscope.aliyuncs.com/compatible-mode/v1`
- Default Model：`qwen-mt-flash`

## Quick Start

1. 创建虚拟环境。
2. 安装桌面依赖：`pip install -e .[desktop]`
3. 安装 OCR 依赖：`pip install -e .[ocr]`
4. 运行自检：`python -m transprot --self-check`
5. 启动桌面应用：`python -m transprot`
6. 在设置页填入百炼 API Key 并保存。

## 交互方式

1. 启动应用后，桌面上会出现一个半透明矩形区域。
2. 拖拽或缩放这个区域，使其覆盖到你要翻译的文字。
3. 点击区域外侧的 `翻译` 按钮。
4. 程序会完成截图、OCR 和翻译，再把译文显示回区域内。

## 模型选择

- 设置页默认模型为 `qwen-mt-flash`
- 点击 `刷新模型` 后，会通过百炼兼容接口拉取模型列表
- 下拉框只保留适合文本翻译的推荐模型
- 如果你想试别的模型，也可以直接手动输入模型名

## 配置与密钥

- 普通配置保存在 `%APPDATA%\TransProt\config.json`
- API Key 保存在 Windows Credential Manager 中
- `config.json` 只保存 `api_key_saved` 状态位，不保存明文密钥
- 如果你升级自旧版本，首次启动会自动把旧版明文 API Key 迁移到 Windows Credential Manager

## 打包

安装打包依赖后运行：

```powershell
python -m PyInstaller --noconfirm --windowed --onedir --name TransProt --collect-all paddleocr --paths src src/transprot/__main__.py
```
