# TransProt

Windows 轻量级桌面 OCR / 翻译工具。

当前版本包含这些能力：

- 系统托盘常驻
- 启动后立即显示可拖拽、可缩放的半透明翻译框
- 点击翻译按钮后执行截图、OCR、翻译，并把译文显示回框内
- 设置页支持 API Key、模型、目标语言、超时与快捷键持久化
- `--self-check` 运行环境自检

## Quick Start

1. 创建虚拟环境。
2. 安装桌面依赖：`pip install -e .[desktop]`
3. 安装 OCR 依赖：`pip install -e .[ocr]`
4. 运行自检：`python -m transprot --self-check`
5. 启动桌面应用：`python -m transprot`

## 常用命令

- 开发启动：`powershell -ExecutionPolicy Bypass -File .\scripts\run-dev.ps1`
- 绿色版构建：`python -m PyInstaller --noconfirm .\packaging\transprot.spec`
- 安装包构建：`powershell -ExecutionPolicy Bypass -File .\scripts\build-release.ps1`

## 打包说明

### 1. 安装打包依赖

```powershell
pip install -e .[desktop,ocr,build]
```

### 2. 构建绿色版目录

```powershell
python -m PyInstaller --noconfirm .\packaging\transprot.spec
```

输出目录：

```text
dist\TransProt\TransProt.exe
```

### 3. 构建 Windows 安装包

先安装 Inno Setup 6，然后执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build-release.ps1
```

输出目录：

```text
installer-output\TransProt-Setup.exe
```

### 4. 首次运行说明

- 安装包不会内置 Paddle OCR 模型。
- 第一次执行 OCR 时，程序会联网下载模型到本地缓存目录。
- 首次识别可能比后续识别更慢，这是正常现象。

### 5. 发布版运行时目录

- 配置文件：`%APPDATA%\TransProt\config.json`
- 日志目录：`%LOCALAPPDATA%\TransProt\logs`
- OCR 缓存：`%LOCALAPPDATA%\TransProt\runtime` 下相关目录

### 6. 无安装包时仅构建绿色版

如果当前机器没有安装 Inno Setup，可以先执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build-release.ps1 -SkipInstaller
```

这样会只产出 `dist\TransProt\`，不生成安装包。
