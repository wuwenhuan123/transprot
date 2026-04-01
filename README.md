# TransProt

Windows 轻量级屏幕翻译工具 MVP。

当前版本实现了这些能力：

- 系统托盘常驻
- 全局热键唤起透明框选
- 截图后走 OCR -> 翻译 -> 原位覆盖显示
- 同时支持 OpenAI 兼容翻译接口和普通翻译 API
- `--self-check` 运行环境自检

## Quick Start

1. 创建虚拟环境。
2. 安装桌面依赖：`pip install -e .[desktop]`
3. 如需 OCR：`pip install -e .[ocr]`
4. 运行自检：`python -m transprot --self-check`
5. 启动桌面应用：`python -m transprot`

## 普通翻译 API 兼容约定

普通翻译 API 采用通用 JSON POST：

- 请求体默认发送 `q`、`source`、`target`
- 若配置了 API Key，会同时附带 `Authorization: Bearer <key>` 和请求体字段 `api_key`
- 响应优先解析这些字段：`translatedText`、`translation`、`translated_text`、`data.translation`、`data.translatedText`

这可以兼容一大类简单 REST 翻译接口；如果后续需要对接某个特定厂商，再单独扩展解析器即可。

## 打包

安装打包依赖后运行：

```powershell
python -m PyInstaller --noconfirm --windowed --onedir --name TransProt --collect-all paddleocr --paths src src/transprot/__main__.py
```

