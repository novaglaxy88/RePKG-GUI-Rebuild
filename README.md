# RePKG-GUI-Rebuild

> 基于 RePKG 二次开发的 Wallpaper Engine 壁纸包批量提取工具，支持拖放添加、单独文件夹输出、进度显示与随时取消，内嵌 RePKG.exe 开箱即用。

**RePKG GUI ·  Rebuild by NovaGlaxy v1.0.0**

> 使用 DeepSeek 迭代开发。

基于 RePKG-GUI 的二次开发，主要改动如下:

---

## 稳定性

- 配置文件缺失、损坏或不可写时全部走安全回退，不会崩溃。
- PyInstaller 打包后能通过 `sys.frozen` 与 `sys._MEIPASS` 正确解析程序位置。
- 配置中记录的 RePKG 路径失效时自动清空，界面不再显示失效旧路径。
- 未识别到 RePKG.exe 时主窗口就绪后弹出提示，引导用户手动选择。

## 提取流程

- `subprocess` 使用列表传参，避免路径含空格时命令被拆断。
- 提取在线程中执行，主线程只负责 UI 更新，窗口全程响应。
- 严格按进程退出码判定成败，逐项着色状态标记。
- 支持随时取消，先用 `terminate` 再用 `kill` 兜底。

## 路径与配置

- 启动时依次在程序目录、`tools` 子目录、`_MEIPASS` 中查找 RePKG.exe。
- 保存位置默认取系统下载文件夹，提取成功后自动打开目标目录。
- 配置文件统一写在程序持久目录，onefile 的临时解压路径不写入配置。
- 手动编辑输入框后回车或失焦即同步全局变量与配置文件。
- 粘贴路径时可能带的首尾空白和引号会在同步前自动清洗。

## 批量与命名

- 单独文件夹模式默认关闭，开启后每个 pkg 提取到独立子目录。
- 重名文件夹从 `_1` 开始依次编号，且只在确实重名时才加后缀，不重名的文件保留原始名称。

## 界面

- ttk 搭配 grid 布局，clam 主题配合 Tailwind 风格浅色系配色。
- 底部状态栏实时反馈进度，Tooltip 在悬停 1.5 秒后于鼠标位置弹出并保持固定。
- 路径显示统一走 `os.path.normpath`，底部版权居中，原作链接可点击。
- 窗口标题为 `RePKG-GUI  ·  Rebuild by NovaGlaxy`。

---

## 鸣谢

- 原作：[https://github.com/Keineliebeundkeinleid/RePKG-GUI](https://github.com/Keineliebeundkeinleid/RePKG-GUI)
- RePKG：[https://github.com/notscuffed/repkg](https://github.com/notscuffed/repkg)

**二次开发：NovaGlaxy**
