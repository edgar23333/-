# 微信自动定时发送助手 V15.0

Windows 桌面自动化工具：多目标独立消息/图片/时间、OCR 搜索、聊天标题核验、日历定时、Windows 任务计划。

## 开发运行
1. 运行 `check_environment.bat`，确认 `All checks passed.`。
2. 运行 `run_debug.bat`。
3. 先测试“检查 / 启动微信（不发送）”，再测试框选和发送。

## EXE 发布
关闭正在运行的 `WeChatAutoSender.exe` 后运行 `build_windows.bat`。
打包结果在 `dist\WeChatAutoSender`。整个目录作为便携版使用；不要只拿 EXE 单文件。

## GitHub 发布建议
源码仓库只提交源码、脚本、README、LICENSE 和 `assets`，不要提交 `build`、`dist`、`data`、日志或缓存。
编译后的便携版 ZIP 建议作为 GitHub Release Asset 上传。

## 安全说明
本项目通过桌面 GUI 自动化操作已登录的电脑版微信。遇到扫码登录、无法确认微信窗口前台状态或目标核验失败时应停止任务，以减少误操作。

## 作者
Edgar Jingxiu — sunzhuojian13@gmail.com
