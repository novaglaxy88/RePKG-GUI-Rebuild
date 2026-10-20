# -*- coding: utf-8 -*-
"""
RePKG GUI · Rebuild by NovaGlaxy v1.0.0

使用Deeseek迭代开发；

基于 RePKG-GUI 的二次开发，主要改动如下：

稳定性
    配置文件缺失、损坏或不可写时全部走安全回退，不会崩溃。
    PyInstaller 打包后能通过 sys.frozen 与 sys._MEIPASS 正确解析程序位置。
    配置中记录的 RePKG 路径失效时自动清空，界面不再显示失效旧路径。
    未识别到 RePKG.exe 时主窗口就绪后弹出提示，引导用户手动选择。

提取流程
    subprocess 使用列表传参，避免路径含空格时命令被拆断。
    提取在线程中执行，主线程只负责 UI 更新，窗口全程响应。
    严格按进程退出码判定成败，逐项着色状态标记。
    支持随时取消，先用 terminate 再用 kill 兜底。

路径与配置
    启动时依次在程序目录、tools 子目录、_MEIPASS 中查找 RePKG.exe。
    保存位置默认取系统下载文件夹，提取成功后自动打开目标目录。
    配置文件统一写在程序持久目录，onefile 的临时解压路径不写入配置。
    手动编辑输入框后回车或失焦即同步全局变量与配置文件。
    粘贴路径时可能带的首尾空白和引号会在同步前自动清洗。

批量与命名
    单独文件夹模式默认关闭，开启后每个 pkg 提取到独立子目录。
    重名文件夹从 _1 开始依次编号，且只在确实重名时才加后缀，
    不重名的文件保留原始名称。

界面
    ttk 搭配 grid 布局，clam 主题配合 Tailwind 风格浅色系配色。
    底部状态栏实时反馈进度，Tooltip 在悬停 1.5 秒后于鼠标位置弹出并保持固定。
    路径显示统一走 os.path.normpath，底部版权居中，原作链接可点击。
    窗口标题为 RePKG-GUI  ·  Rebuild by NovaGlaxy。


原作：https://github.com/Keineliebeundkeinleid/RePKG-GUI
RePKG：https://github.com/notscuffed/repkg

二次开发：NovaGlaxy

"""

import os
import sys
import re
import time
import webbrowser
import subprocess
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from PIL import Image, ImageTk  # noqa: F401

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    HAS_DND = True
except ImportError:
    HAS_DND = False
    TkinterDnD = None
    DND_FILES = None


# 主题配色
#
# 参考 Tailwind 色板选取的浅色系。整体以低饱和背景、高对比文字、
# 单一强调蓝和危险红为主，避免视觉噪音。每个常量后面的注释标明
# 它在界面上的具体用途。
COLOR_BG = '#f8fafc'                # 全局背景
COLOR_BORDER = '#e2e8f0'            # 分组边框
COLOR_ACCENT = '#2563eb'            # 主按钮
COLOR_ACCENT_HOVER = '#1d4ed8'      # 主按钮悬停
COLOR_ACCENT_PRESSED = '#1e40af'    # 主按钮按下
COLOR_ACCENT_DISABLED = '#93c5fd'   # 主按钮禁用
COLOR_DANGER = '#dc2626'            # 危险按钮
COLOR_DANGER_HOVER = '#b91c1c'      # 危险按钮悬停
COLOR_DANGER_DISABLED = '#fca5a5'   # 危险按钮禁用
COLOR_TEXT = '#0f172a'              # 主文字
COLOR_MUTED = '#64748b'             # 次要文字
COLOR_STATUS_BG = '#f1f5f9'         # 状态栏背景
COLOR_LINK = '#2563eb'              # 超链接
COLOR_TOOLTIP_BG = '#ffffff'        # 提示框背景
COLOR_TOOLTIP_FG = '#1e293b'        # 提示框文字
COLOR_TOOLTIP_BORDER = '#cbd5e1'    # 提示框边框

# 统一字体，避免混用导致布局跳动
FONT_FAMILY = 'Microsoft YaHei UI'
FONT_NORMAL = (FONT_FAMILY, 10)
FONT_SMALL = (FONT_FAMILY, 9)
FONT_TITLE = (FONT_FAMILY, 10, 'bold')


# 路径与文件工具

def norm_path(p):
    """把任意风格的路径统一为当前平台的标准格式。

    在 Windows 上会把正斜杠转为反斜杠，去掉多余分隔符和末尾反斜杠，
    保证 Entry、日志、消息框和配置文件里看到的路径样式一致。
    """
    if not p:
        return p
    try:
        return os.path.normpath(p)
    except Exception:
        return p


def clean_path_input(value):
    """清洗用户在 Entry 里手动输入或粘贴的路径。

    手动粘贴时常见两类污染。第一类是 Windows 资源管理器"复制为路径"
    时会给路径带上首尾双引号。第二类是复制时带上不可见的前后空白。
    这两类都会导致后续 os.path.isfile 或 isdir 判断失败，所以必须在
    写入全局变量和配置之前去掉。路径本身不应该出现双引号，一旦出现
    即视为复制产生的包裹，直接剥离即可。
    """
    if not value:
        return ''
    v = value.strip()
    if len(v) >= 2 and v[0] == '"' and v[-1] == '"':
        v = v[1:-1].strip()
    return norm_path(v)


def get_app_dir():
    """返回程序的持久所在目录。

    源码运行时取脚本文件所在目录；PyInstaller 打包后取 exe 所在目录。
    这里特意不用 sys._MEIPASS，因为它是临时解压目录，程序退出后即被
    清理，不能用来存放需要跨启动保留的配置。
    """
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def config_path(name):
    """拼接配置文件路径，统一存放在程序持久目录下。"""
    return os.path.join(get_app_dir(), name)


def get_downloads_dir():
    """获取用户真实的下载文件夹路径。

    通过 Windows Known Folder API 读取，能正确处理用户把下载目录
    改到其他盘的情况。API 调用失败或返回空值时回退到 ~/Downloads。
    """
    try:
        import ctypes
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [
                ("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8),
            ]

        # FOLDERID_Downloads = {374DE290-123F-4565-9164-39C4925E467B}
        fid = GUID(0x374DE290, 0x123F, 0x4565,
                   (ctypes.c_ubyte * 8)(0x91, 0x64, 0x39, 0xC4, 0x92, 0x5E, 0x46, 0x7B))
        shell32 = ctypes.windll.shell32
        shell32.SHGetKnownFolderPath.argtypes = [
            ctypes.POINTER(GUID), wintypes.DWORD,
            wintypes.HANDLE, ctypes.POINTER(ctypes.c_wchar_p),
        ]
        shell32.SHGetKnownFolderPath.restype = ctypes.c_long
        ptr = ctypes.c_wchar_p()
        if shell32.SHGetKnownFolderPath(ctypes.byref(fid), 0, None, ctypes.byref(ptr)) == 0 and ptr.value:
            result = ptr.value
            try:
                ctypes.windll.ole32.CoTaskMemFree(ctypes.cast(ptr, ctypes.c_void_p))
            except Exception:
                pass
            return result
    except Exception as e:
        print(f'[路径] 获取下载文件夹失败: {e}')
    return os.path.join(os.path.expanduser('~'), 'Downloads')


def is_writable_dir(path):
    """检测目录是否存在且可写。

    通过在目标目录写一个临时文件再删除来判断。这比 os.access 更可靠，
    因为 Windows 上的 ACL 权限和只读属性会让 os.access 误判。
    """
    if not path or not os.path.isdir(path):
        return False
    f = os.path.join(path, f'.repkg_write_test_{os.getpid()}')
    try:
        with open(f, 'w') as fp:
            fp.write('x')
        os.remove(f)
        return True
    except Exception:
        return False


def open_folder(path):
    """用系统默认文件管理器打开目录。

    兼容 Windows、macOS、Linux 三个平台。失败时只记录日志不弹窗，
    因为提取本身已经成功，打开目录失败不应该打断用户。
    """
    if not path or not os.path.isdir(path):
        log(f'[打开] 目录不存在: {path}')
        return
    try:
        if sys.platform.startswith('win'):
            os.startfile(path)
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', path])
        else:
            subprocess.Popen(['xdg-open', path])
    except Exception as e:
        log(f'[打开] 失败: {e}')


def load_text(name):
    """读取配置文件内容，返回去除首尾空白的字符串。

    先查程序目录，再查当前工作目录，都不存在时返回空串。
    双路径查找是为了兼容旧版本把配置写在 CWD 的情况。
    任何读失败都返回空串，让调用方按"未配置"处理。
    """
    for p in (config_path(name), name):
        try:
            with open(p, 'r', encoding='utf-8') as f:
                return f.read().strip()
        except FileNotFoundError:
            continue
        except Exception as e:
            print(f'[配置] 读取 {p} 失败: {e}')
    return ''


def save_text(name, content):
    """写入配置文件，只记录异常不抛给上层。

    写失败通常出现在只读目录或权限不足的场景。此时程序应当继续运行，
    下一次启动会重新走默认值或自动识别逻辑。
    """
    try:
        with open(config_path(name), 'w', encoding='utf-8') as f:
            f.write(content)
    except Exception as e:
        print(f'[配置] 保存 {name} 失败: {e}')


def find_repkg():
    """按固定优先级查找 RePKG.exe。

    查找顺序依次为：
        1. 程序所在目录，覆盖 onedir 打包产物和用户手动放置的常见位置
        2. 程序目录下的 tools 子目录，方便把工具集中管理
        3. sys._MEIPASS，onefile 打包后内嵌 RePKG.exe 的解压位置

    返回一个二元组，第一个元素是完整路径，第二个元素表示该文件是否
    位于临时解压目录。临时目录每次启动都会变，把这种路径写入配置会
    导致下次启动直接失效，因此调用方需要据此决定是否持久化。
    找不到时返回 ('', False)。
    """
    app_dir = get_app_dir()
    search_dirs = [app_dir, os.path.join(app_dir, 'tools')]

    meipass = getattr(sys, '_MEIPASS', None)
    if meipass and meipass not in search_dirs:
        search_dirs.append(meipass)

    for d in search_dirs:
        if not d or not os.path.isdir(d):
            continue
        try:
            for name in os.listdir(d):
                if name.lower() == 'repkg.exe':
                    full = os.path.join(d, name)
                    is_temp = bool(meipass) and os.path.abspath(full).startswith(
                        os.path.abspath(meipass)
                    )
                    return full, is_temp
        except OSError as e:
            print(f'[识别] 扫描 {d} 失败: {e}')
    return '', False


# ttk 主题

def apply_theme(root):
    """把 clam 主题改造成浅色现代风格并应用到全部 ttk 控件。

    选 clam 而不是 vista 的原因是 vista 主题会强制覆盖按钮的
    background，无法配置悬停、按下、禁用三态颜色。clam 支持完整样式
    配置，代价是失去一点 Windows 原生外观。
    """
    style = ttk.Style(root)
    try:
        style.theme_use('clam')
    except Exception:
        pass

    style.configure('.', font=FONT_NORMAL, foreground=COLOR_TEXT)
    style.configure('TFrame', background=COLOR_BG)
    style.configure('TLabel', background=COLOR_BG, foreground=COLOR_TEXT)
    style.configure('Muted.TLabel', background=COLOR_BG, foreground=COLOR_MUTED, font=FONT_SMALL)
    style.configure('TLabelframe', background=COLOR_BG,
                    bordercolor=COLOR_BORDER, lightcolor=COLOR_BG,
                    darkcolor=COLOR_BG, relief='solid', borderwidth=1)
    style.configure('TLabelframe.Label', background=COLOR_BG,
                    foreground=COLOR_TEXT, font=FONT_TITLE)
    style.configure('TCheckbutton', background=COLOR_BG, foreground=COLOR_TEXT)
    style.map('TCheckbutton', background=[('active', COLOR_BG)])
    style.configure('TEntry', fieldbackground='white',
                    bordercolor=COLOR_BORDER, lightcolor=COLOR_BORDER,
                    darkcolor=COLOR_BORDER, padding=(6, 5))
    style.configure('TButton', font=FONT_NORMAL, padding=(10, 5))

    # 主操作按钮，强调色加粗字
    style.configure('Accent.TButton', background=COLOR_ACCENT, foreground='white',
                    bordercolor=COLOR_ACCENT, focusthickness=0,
                    font=FONT_TITLE, padding=(18, 7))
    style.map('Accent.TButton',
              background=[('active', COLOR_ACCENT_HOVER),
                          ('pressed', COLOR_ACCENT_PRESSED),
                          ('disabled', COLOR_ACCENT_DISABLED)],
              foreground=[('disabled', '#f0f0f0')])

    # 危险操作按钮，用红色区分取消类动作
    style.configure('Danger.TButton', background=COLOR_DANGER, foreground='white',
                    bordercolor=COLOR_DANGER, focusthickness=0,
                    font=FONT_NORMAL, padding=(18, 7))
    style.map('Danger.TButton',
              background=[('active', COLOR_DANGER_HOVER),
                          ('disabled', COLOR_DANGER_DISABLED)],
              foreground=[('disabled', '#f0f0f0')])

    # 进度条与整体强调色一致，加厚便于观察
    style.configure('Horizontal.TProgressbar', background=COLOR_ACCENT,
                    troughcolor=COLOR_STATUS_BG, bordercolor=COLOR_BORDER,
                    lightcolor=COLOR_ACCENT, darkcolor=COLOR_ACCENT, thickness=8)


def set_window_icon(root):
    """尝试从 _MEIPASS 或程序目录加载 app.ico，缺失时静默跳过。"""
    candidates = []
    meipass = getattr(sys, '_MEIPASS', None)
    if meipass:
        candidates.append(os.path.join(meipass, 'app.ico'))
    candidates.append(os.path.join(get_app_dir(), 'app.ico'))
    for p in candidates:
        if os.path.isfile(p):
            try:
                root.iconbitmap(p)
                return
            except Exception:
                pass


# Tooltip

class Tooltip:
    """为任意控件添加悬停提示。

    行为约定：
        鼠标进入后开始计时，delay 毫秒后在鼠标当前位置右下方弹出气泡。
        气泡一旦弹出就保持固定，不跟随鼠标移动。鼠标离开控件或按下按键
        时立即销毁。气泡是 overrideredirect 的 Toplevel，不抢焦点。

    位置计算为什么用 winfo_pointerx/y 而不是 <Enter> 事件坐标：
        ttk 复合控件内部有子元素，进入瞬间的坐标可能来自子元素，容易
        偏移。而且高 DPI 缩放下事件坐标和 wm_geometry 使用的坐标系
        可能不一致，两者混用会产生明显的错位。
    """

    def __init__(self, widget, text, delay=1500, wraplength=400):
        self.widget = widget
        self.text = text
        self.delay = delay
        self.wraplength = wraplength
        self.tip = None
        self.after_id = None
        widget.bind('<Enter>', self._schedule, add='+')
        widget.bind('<Leave>', self._hide, add='+')
        widget.bind('<ButtonPress>', self._hide, add='+')

    def _schedule(self, _event=None):
        """进入控件时重新安排弹出，取消上一次尚未触发的计划。"""
        self._cancel()
        try:
            self.after_id = self.widget.after(self.delay, self._show)
        except Exception:
            self.after_id = None

    def _cancel(self):
        if self.after_id:
            try:
                self.widget.after_cancel(self.after_id)
            except Exception:
                pass
            self.after_id = None

    def _show(self):
        """在鼠标当前位置弹出提示气泡。"""
        self.after_id = None
        if self.tip or not self.text:
            return
        try:
            mx = self.widget.winfo_pointerx()
            my = self.widget.winfo_pointery()
        except Exception:
            return

        tip = tk.Toplevel(self.widget)
        tip.wm_overrideredirect(True)
        tip.wm_attributes('-topmost', True)

        # 用外层 Frame 充当 1px 边框，避免依赖 tk 原生 border 颜色
        outer = tk.Frame(tip, background=COLOR_TOOLTIP_BORDER)
        outer.pack()
        tk.Label(
            outer, text=self.text, justify='left',
            background=COLOR_TOOLTIP_BG, foreground=COLOR_TOOLTIP_FG,
            font=FONT_SMALL, padx=12, pady=8, wraplength=self.wraplength,
            relief='flat', borderwidth=0,
        ).pack(padx=1, pady=1)

        # 更新布局后读取真实尺寸，避免气泡超出屏幕边缘
        try:
            tip.update_idletasks()
            tw, th = tip.winfo_reqwidth(), tip.winfo_reqheight()
            sw, sh = tip.winfo_screenwidth(), tip.winfo_screenheight()
            x = mx + 16
            y = my + 20
            if x + tw > sw - 8:
                x = sw - tw - 8
            if y + th > sh - 8:
                y = my - th - 12
            if x < 8:
                x = 8
            if y < 8:
                y = 8
            tip.wm_geometry(f'+{x}+{y}')
        except Exception:
            tip.wm_geometry(f'+{mx + 16}+{my + 20}')
        self.tip = tip

    def _hide(self, _event=None):
        self._cancel()
        if self.tip:
            try:
                self.tip.destroy()
            except Exception:
                pass
            self.tip = None


# 全局状态
#
# 这些变量跨越事件回调与后台线程读写，集中声明便于追踪。
# UI 引用在构建阶段才赋值，函数内访问前需要判空。
RePKG_path = ''
save_path = ''
wallpaper = []                      # 待提取的 pkg 文件路径列表
wallpaper_status = {}               # pkg 路径 → 状态符号
repkg_missing = False               # 启动时未识别到 RePKG，用于延后弹窗

log_text = None
listbox = None
progress = None
progress_label = None
button_extract = None
button_cancel = None
btn_add = None
btn_remove = None
btn_clear = None
var_separate = None
status_text = None

is_extracting = False               # 是否正在执行提取
current_proc = None                 # 当前 RePKG 子进程，用于取消和关窗终止
cancel_event = threading.Event()    # 跨线程取消信号


def set_status(text):
    """更新底部状态栏文字。"""
    if status_text is not None:
        try:
            status_text.set(text)
        except Exception:
            pass


def log(msg):
    """向日志框追加一行，并自动滚动到底部。

    后台线程不能直接操作 tk 控件，调用方需要先通过 root.after
    切回主线程再调用本函数。
    """
    if log_text is None:
        print(msg)
        return
    try:
        log_text.config(state='normal')
        log_text.insert('end', msg + '\n')
        log_text.see('end')
        log_text.config(state='disabled')
    except Exception:
        pass


def clear_log():
    """清空日志框内容。"""
    if log_text is None:
        return
    try:
        log_text.config(state='normal')
        log_text.delete('1.0', 'end')
        log_text.config(state='disabled')
    except Exception:
        pass


def shorten_path(path, max_len=78):
    """把过长的路径缩写成 盘符开头...文件名结尾 的形式。

    目的是让列表既能看出文件来自哪个盘，又始终能看到文件名。
    如果文件名本身就长，则省略前面全部路径只保留文件名尾部。
    """
    if len(path) <= max_len:
        return path
    name = os.path.basename(path)
    if len(name) >= max_len - 4:
        return '...' + name[-(max_len - 3):]
    head_budget = max_len - len(name) - 6
    if head_budget < 8:
        return '...' + name
    return f'{path[:head_budget]}...{name}'


def refresh_listbox():
    """根据 wallpaper 和 wallpaper_status 重建整个列表。

    重建前记录滚动位置，重建后恢复，避免刷新后列表跳回顶部。
    """
    if listbox is None:
        return
    try:
        y = listbox.yview()
    except Exception:
        y = (0.0, 1.0)
    listbox.delete(0, 'end')
    for p in wallpaper:
        status = wallpaper_status.get(p, '⚪')
        listbox.insert('end', f' {status}  {shorten_path(p)}')
    try:
        listbox.yview_moveto(y[0])
    except Exception:
        pass


def on_listbox_select(_event=None):
    """列表项被选中时在状态栏显示完整路径。

    列表里显示的是缩短后的路径，用户想复制或确认完整位置时
    看状态栏即可。
    """
    if is_extracting or listbox is None:
        return
    sel = listbox.curselection()
    if not sel:
        return
    idx = sel[0]
    if 0 <= idx < len(wallpaper):
        set_status(wallpaper[idx])


def _set_status(pkg_path, status):
    """更新指定 pkg 的状态标记并刷新列表。"""
    wallpaper_status[pkg_path] = status
    refresh_listbox()


# 用于清理文件夹名中的 Windows 非法字符
_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def build_output_dirs():
    """为单独文件夹模式计算每个 pkg 的目标目录。

    目录名以 pkg 文件名去扩展名后的部分为基础，替换掉 Windows
    不允许的字符。重名判定分两阶段处理。

    第一阶段统计每个基础名在整个列表中出现的次数，比较时统一转小写，
    因为 Windows 文件系统不区分大小写，Scene 和 scene 会被视为冲突。

    第二阶段按列表顺序逐个分配目录名。只出现一次的基础名直接原样使用，
    不加任何后缀。出现多次的基础名从 _1 开始依次追加序号，这样重名
    文件会得到 scene_1、scene_2、scene_3 这样的独立目录，而不重名的
    文件仍然保留 scene 这样的原始名称。

    分配时用一个全局已用集合兜底，避免不同基础名清洗非法字符后相互
    撞名，例如 a<b.pkg 和 a>b.pkg 都会被清洗为 a_b。一旦发现撞名就在
    候选名后再追加 _1、_2 直到唯一。
    """
    stems = []
    for p in wallpaper:
        stem = os.path.splitext(os.path.basename(p))[0]
        stem = _INVALID_CHARS.sub('_', stem).strip('. ') or 'pkg'
        stems.append(stem)

    counts = {}
    for s in stems:
        key = s.lower()
        counts[key] = counts.get(key, 0) + 1

    seq = {}
    used = set()
    mapping = {}
    for p, stem in zip(wallpaper, stems):
        key = stem.lower()
        if counts[key] == 1:
            candidate = stem
        else:
            seq[key] = seq.get(key, 0) + 1
            candidate = f'{stem}_{seq[key]}'

        final = candidate
        n = 1
        while final.lower() in used:
            final = f'{candidate}_{n}'
            n += 1
        used.add(final.lower())
        mapping[p] = os.path.join(save_path, final)
    return mapping


# 输入同步

def _sync_repkg_entry(_event=None):
    """把 RePKG Entry 的当前值写回全局变量和配置。

    用户可能手动粘贴路径而不是点"选择..."，粘贴后可能伴随首尾空白
    或引号，需要统一清洗。若清洗后是有效文件路径，同时清除启动时的
    "未识别"标记。
    """
    global RePKG_path, repkg_missing
    v = clean_path_input(var_RePKG.get())
    if v != var_RePKG.get():
        var_RePKG.set(v)
    if v != RePKG_path:
        RePKG_path = v
        save_text('RePKG-path.txt', v)
    if v and os.path.isfile(v):
        repkg_missing = False


def _sync_save_entry(_event=None):
    """把保存位置 Entry 的当前值写回全局变量和配置。

    这个函数解决了"手动粘贴地址到保存位置后点提取无效"的问题。
    用户粘贴的值原本只存在 StringVar 里，没同步到全局 save_path，
    导致 extract 里用的仍然是旧值。
    """
    global save_path
    v = clean_path_input(var_save.get())
    if v != var_save.get():
        var_save.set(v)
    if v != save_path:
        save_path = v
        save_text('save-path.txt', v)


# 文件选择与列表操作

def choose_RePKG():
    """手动选择 RePKG.exe，成功后同步更新配置。"""
    global RePKG_path, repkg_missing
    path = filedialog.askopenfilename(
        title='选择 RePKG 程序',
        initialdir=os.path.expanduser('~'),
        filetypes=(('Executable files', '*.exe'), ('All files', '*.*'))
    )
    if not path:
        return
    RePKG_path = norm_path(path)
    repkg_missing = False
    var_RePKG.set(RePKG_path)
    save_text('RePKG-path.txt', RePKG_path)


def choose_save():
    """手动选择保存位置，成功后同步更新配置。"""
    global save_path
    path = filedialog.askdirectory(title='选择保存位置')
    if not path:
        return
    save_path = norm_path(path)
    var_save.set(save_path)
    save_text('save-path.txt', save_path)


def add_multiple():
    """通过文件对话框批量添加 pkg，自动去重。"""
    paths = filedialog.askopenfilenames(
        title='选择 wallpaper pkg 文件',
        initialdir=os.path.expanduser('~'),
        filetypes=(('Package files', '*.pkg'), ('All files', '*.*'))
    )
    if not paths:
        return
    added = 0
    for p in paths:
        np = norm_path(p)
        if np not in wallpaper:
            wallpaper.append(np)
            added += 1
    if added:
        refresh_listbox()
        log(f'[添加] 添加 {added} 个 pkg, 共 {len(wallpaper)} 个')
        set_status(f'已添加 {added} 个，共 {len(wallpaper)} 个')


def remove_selected():
    """移除列表中当前选中的一项或多项。"""
    sel = listbox.curselection()
    if not sel:
        return
    for idx in reversed(sel):
        p = wallpaper.pop(idx)
        wallpaper_status.pop(p, None)
    refresh_listbox()
    log(f'[移除] 已移除 {len(sel)} 个, 剩余 {len(wallpaper)} 个')
    set_status(f'剩余 {len(wallpaper)} 个')


def clear_list():
    """清空整个列表，需要二次确认。"""
    if not wallpaper:
        return
    if not messagebox.askyesno('确认', f'清空 {len(wallpaper)} 个 pkg?'):
        return
    wallpaper.clear()
    wallpaper_status.clear()
    refresh_listbox()
    log('[清空] 列表已清空')
    set_status('列表已清空')


def on_drop(event):
    """处理从资源管理器拖入的文件。

    只接受实际存在且扩展名为 .pkg 的文件，其余计入跳过数量。
    解析 event.data 使用 tk.splitlist 以正确处理带空格的路径。
    """
    if not HAS_DND:
        return
    try:
        paths = root.tk.splitlist(event.data)
    except Exception as e:
        log(f'[拖放] 解析失败: {e}')
        return
    added = skipped = 0
    for p in paths:
        p = norm_path(p.strip())
        if (not p or not os.path.isfile(p)
                or not p.lower().endswith('.pkg') or p in wallpaper):
            skipped += 1
            continue
        wallpaper.append(p)
        added += 1
    if added:
        refresh_listbox()
        msg = f'[拖放] 添加 {added} 个文件'
        if skipped:
            msg += f', 跳过 {skipped} 个'
        log(msg)
        set_status(f'已添加 {added} 个，共 {len(wallpaper)} 个')


# 进度

def update_progress(done, total):
    """更新进度条数值与 x/y 文本，提取中同步刷新状态栏。"""
    try:
        progress['maximum'] = max(total, 1)
        progress['value'] = done
    except Exception:
        pass
    try:
        progress_label.config(text=f'{done}/{total}')
    except Exception:
        pass
    if is_extracting:
        set_status(f'提取中 {done}/{total}')


# 提取

def extract():
    """校验参数、准备输出映射，然后把实际提取交给后台线程。

    进入时先从两个 Entry 读取最新值同步到全局变量，解决用户手动
    粘贴路径但未触发 FocusOut 时的时序问题。粘贴后直接点"开始提取"
    时，FocusOut 与 button command 的触发顺序在 tkinter 上并不保证，
    所以必须在 extract 入口处主动同步一次。

    所有耗时操作都不在主线程，用户点击后立即返回，界面保持响应。
    校验失败时用消息框提示，不静默失败。
    """
    global is_extracting

    # 从 Entry 读取最新值，作为本次提取的权威来源
    _sync_repkg_entry()
    _sync_save_entry()

    if not RePKG_path:
        messagebox.showwarning('提示', '请先选择 RePKG 程序'); return
    if not os.path.isfile(RePKG_path):
        messagebox.showerror('错误', f'RePKG 程序不存在:\n{RePKG_path}'); return
    if not save_path:
        messagebox.showwarning('提示', '请先选择保存位置'); return
    if not is_writable_dir(save_path):
        if not messagebox.askyesno('警告', f'保存位置不存在或不可写:\n{save_path}\n\n仍要继续吗?'):
            return
    if not wallpaper:
        messagebox.showwarning('提示', '请先添加 wallpaper pkg 文件'); return

    # 单独模式为每个 pkg 分配独立目录，否则全部指向同一个根目录
    separate = bool(var_separate.get())
    out_map = build_output_dirs() if separate else {p: save_path for p in wallpaper}

    for p in wallpaper:
        wallpaper_status[p] = '⚪'
    refresh_listbox()

    cancel_event.clear()
    is_extracting = True

    button_extract.config(state='disabled', text='提取中...')
    button_cancel.config(state='normal')
    btn_add.config(state='disabled')
    btn_remove.config(state='disabled')
    btn_clear.config(state='disabled')

    update_progress(0, len(wallpaper))

    log('=' * 55)
    log(f'开始提取, 共 {len(wallpaper)} 个文件')
    log(f'RePKG: {RePKG_path}')
    log(f'输出根目录: {save_path}')
    log(f'单独文件夹模式: {"开" if separate else "关"}')

    threading.Thread(target=_do_extract, args=(separate, out_map), daemon=True).start()


def _read_stream(stream, lines):
    """把子进程输出流逐行读入列表。

    必须用独立线程读取，否则管道写满后子进程会阻塞，主等待循环卡死。
    """
    try:
        for line in iter(stream.readline, ''):
            lines.append(line)
    except Exception:
        pass
    finally:
        try:
            stream.close()
        except Exception:
            pass


def _do_extract(separate, out_map):
    """后台线程主循环，逐个调用 RePKG 提取每个 pkg。

    线程不能直接操作 tk 控件，所有 UI 更新都通过 root.after(0, ...)
    打包成回调交给主线程执行。使用默认参数绑定当前循环变量的值，
    避免闭包捕获同一个变量导致所有回调拿到最后一次迭代的值。
    """
    global current_proc
    total = len(wallpaper)
    results = []

    for idx, wp in enumerate(wallpaper):
        if cancel_event.is_set():
            break

        name = os.path.basename(wp)
        out_dir = out_map.get(wp, save_path)

        # 单独文件夹模式下需要先确保目录存在，RePKG 不会自建深层目录
        if separate:
            try:
                os.makedirs(out_dir, exist_ok=True)
            except Exception as e:
                root.after(0, lambda i=idx + 1, n=name, e=str(e), t=total:
                           log(f'[{i}/{t}] ✗ 创建目录失败: {n}\n  {e}'))
                results.append('fail')
                root.after(0, lambda p=wp: _set_status(p, '✗'))
                root.after(0, lambda d=idx + 1, t=total: update_progress(d, t))
                continue

        if separate:
            root.after(0, lambda i=idx + 1, n=name, t=total, d=os.path.basename(out_dir):
                       log(f'[{i}/{t}] 提取: {n}  →  {d}/'))
        else:
            root.after(0, lambda i=idx + 1, n=name, t=total:
                       log(f'[{i}/{t}] 提取: {n}'))
        root.after(0, lambda p=wp: _set_status(p, '⏳'))

        cancelled = False
        try:
            proc = subprocess.Popen(
                [RePKG_path, 'extract', wp, '-o', out_dir],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding='utf-8', errors='replace',
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)
            )
            current_proc = proc

            stdout_lines, stderr_lines = [], []
            t_out = threading.Thread(target=_read_stream, args=(proc.stdout, stdout_lines), daemon=True)
            t_err = threading.Thread(target=_read_stream, args=(proc.stderr, stderr_lines), daemon=True)
            t_out.start(); t_err.start()

            # 主等待循环，每 100ms 检查一次取消信号
            while proc.poll() is None:
                if cancel_event.is_set():
                    cancelled = True
                    try:
                        proc.terminate()
                    except Exception:
                        pass
                    try:
                        proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        try:
                            proc.kill()
                        except Exception:
                            pass
                    break
                time.sleep(0.1)

            t_out.join(timeout=2); t_err.join(timeout=2)
            current_proc = None
            stdout = ''.join(stdout_lines)
            stderr = ''.join(stderr_lines)

            if cancelled:
                results.append('cancel')
                root.after(0, lambda i=idx + 1, n=name, t=total:
                           log(f'[{i}/{t}] 已取消: {n}'))
                root.after(0, lambda p=wp: _set_status(p, '—'))
            elif proc.returncode == 0:
                results.append('ok')
                root.after(0, lambda i=idx + 1, n=name, t=total:
                           log(f'[{i}/{t}] ✓ 完成: {n}'))
                root.after(0, lambda p=wp: _set_status(p, '✓'))
            else:
                results.append('fail')
                err = (stderr or stdout or '').strip()[:400]
                root.after(0, lambda i=idx + 1, n=name, t=total, e=err:
                           log(f'[{i}/{t}] ✗ 失败: {n}\n  {e}'))
                root.after(0, lambda p=wp: _set_status(p, '✗'))
        except Exception as e:
            current_proc = None
            results.append('fail')
            err = str(e)
            root.after(0, lambda i=idx + 1, n=name, t=total, e=err:
                       log(f'[{i}/{t}] ✗ 异常: {n}\n  {e}'))
            root.after(0, lambda p=wp: _set_status(p, '✗'))

        root.after(0, lambda d=idx + 1, t=total: update_progress(d, t))

    root.after(0, lambda: _on_extract_done(results, separate))


def _on_extract_done(results, separate):
    """提取结束后的收尾：统计结果、恢复控件、按需打开目录。

    单独模式打开保存根目录，用户能看到每个 pkg 各自的子目录。
    非单独模式所有内容都在 materials 下，直接打开该目录更直观。
    """
    global is_extracting
    is_extracting = False

    button_extract.config(state='normal', text='开始提取')
    button_cancel.config(state='disabled')
    btn_add.config(state='normal')
    btn_remove.config(state='normal')
    btn_clear.config(state='normal')

    ok = results.count('ok')
    fail = results.count('fail')
    cancel = results.count('cancel')
    unprocessed = len(wallpaper) - len(results)

    update_progress(len(results), len(wallpaper))

    log('=' * 55)
    log(f'完成: 成功 {ok} / 失败 {fail} / 取消 {cancel} / 未处理 {unprocessed}')

    if cancel > 0 and ok == 0:
        set_status(f'已取消 (成功 {ok} / 失败 {fail})')
    elif fail or cancel or unprocessed:
        set_status(f'完成 成功 {ok} 失败 {fail} 取消 {cancel} 未处理 {unprocessed}')
    else:
        set_status(f'完成 成功 {ok}')

    if ok > 0:
        if separate:
            log(f'正在打开保存目录: {save_path}')
            open_folder(save_path)
        else:
            target = os.path.join(save_path, 'materials')
            log(f'正在打开: {target}')
            open_folder(target if os.path.isdir(target) else save_path)

    if fail or cancel or unprocessed:
        messagebox.showwarning('完成',
                               f'成功 {ok} / 失败 {fail} / 取消 {cancel} / 未处理 {unprocessed}')


def cancel_extract():
    """请求取消当前提取。

    设置跨线程取消标志后，后台循环在 100ms 内会检测到并终止当前
    子进程。已经处理完的 pkg 结果保留，剩余 pkg 标记为未处理。
    """
    if not is_extracting:
        return
    cancel_event.set()
    set_status('正在取消...')
    log('[取消] 请求取消当前提取...')
    if current_proc:
        try:
            current_proc.terminate()
        except Exception:
            pass


# 启动初始化

RePKG_path = norm_path(load_text('RePKG-path.txt'))
save_path = norm_path(load_text('save-path.txt'))

# 配置里的路径可能已失效，比如用户删了或移走了 RePKG.exe。
# 先清空并写回配置，避免界面显示一个打不开的旧路径误导用户，
# 也让下次启动直接走自动识别，不再读到脏数据。
if RePKG_path and not os.path.isfile(RePKG_path):
    print(f'[识别] 配置中的路径已失效: {RePKG_path}')
    RePKG_path = ''
    save_text('RePKG-path.txt', '')

# 未配置或配置已失效时，按程序目录、tools 子目录、_MEIPASS 顺序自动查找。
# 临时解压路径只在本次启动有效，不写配置，避免下次启动读到失效路径。
if not RePKG_path:
    detected, is_temp = find_repkg()
    if detected:
        RePKG_path = norm_path(detected)
        if not is_temp:
            save_text('RePKG-path.txt', RePKG_path)
            print(f'[识别] 自动识别 RePKG: {RePKG_path}')
        else:
            print(f'[识别] 使用内嵌 RePKG (临时解压): {RePKG_path}')
    else:
        # 自动查找也失败，明确保持为空，让路径框空出来提示用户手动选择。
        # 同时标记 repkg_missing，UI 构建完成后会弹窗提示。
        RePKG_path = ''
        repkg_missing = True
        print('[识别] 未找到 RePKG.exe, 请手动选择')

# 首次运行时把保存位置默认设为系统下载文件夹
if not save_path:
    save_path = norm_path(get_downloads_dir())
    if not os.path.isdir(save_path):
        save_path = os.path.expanduser('~')
    save_text('save-path.txt', save_path)
    print(f'[路径] 保存位置默认使用: {save_path}')


# 创建主窗口

if HAS_DND:
    try:
        root = TkinterDnD.Tk()
    except Exception as e:
        print(f'[拖放] 初始化失败, 降级为普通模式: {e}')
        HAS_DND = False
        root = tk.Tk()
else:
    root = tk.Tk()

root.title('RePKG-GUI  ·  Rebuild by NovaGlaxy')
root.configure(bg=COLOR_BG)
apply_theme(root)
set_window_icon(root)

# 尝试恢复上次窗口几何。格式不符或超出屏幕时回退到默认尺寸。
saved_geo = load_text('window-geometry.txt')
geo_applied = False
if saved_geo:
    m = re.match(r'^(\d+)x(\d+)([+-]\d+)([+-]\d+)$', saved_geo)
    if m:
        w, h = int(m.group(1)), int(m.group(2))
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        if 600 <= w <= sw and 400 <= h <= sh:
            root.geometry(saved_geo)
            geo_applied = True

if not geo_applied:
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(f'{min(1020, int(sw * 0.78))}x{min(800, int(sh * 0.80))}')

root.minsize(780, 640)
root.columnconfigure(0, weight=1)
root.rowconfigure(1, weight=2)
root.rowconfigure(3, weight=1)


# 路径设置卡片
frame_top = ttk.LabelFrame(root, text='路径设置', padding=(14, 12))
frame_top.grid(row=0, column=0, sticky='ew', padx=14, pady=(14, 0))
frame_top.columnconfigure(1, weight=1)

ttk.Label(frame_top, text='RePKG程序位置:').grid(row=0, column=0, sticky='w', padx=(0, 10), pady=5)
var_RePKG = tk.StringVar(value=RePKG_path)
entry_repkg = ttk.Entry(frame_top, textvariable=var_RePKG)
entry_repkg.grid(row=0, column=1, sticky='ew', pady=5)
button_RePKG = ttk.Button(frame_top, text='选择...', command=choose_RePKG)
button_RePKG.grid(row=0, column=2, padx=(10, 0), pady=5)

ttk.Label(frame_top, text='保存位置:').grid(row=1, column=0, sticky='w', padx=(0, 10), pady=5)
var_save = tk.StringVar(value=save_path)
entry_save = ttk.Entry(frame_top, textvariable=var_save)
entry_save.grid(row=1, column=1, sticky='ew', pady=5)
button_save = ttk.Button(frame_top, text='选择...', command=choose_save)
button_save.grid(row=1, column=2, padx=(10, 0), pady=5)

# 手动编辑或粘贴后，回车或失焦即同步全局变量与配置
entry_repkg.bind('<FocusOut>', _sync_repkg_entry)
entry_repkg.bind('<Return>', _sync_repkg_entry)
entry_save.bind('<FocusOut>', _sync_save_entry)
entry_save.bind('<Return>', _sync_save_entry)


# pkg 列表卡片
list_hint = ' 支持拖放 .pkg 到此处' if HAS_DND else ' (安装 tkinterdnd2 可启用拖放)'
frame_list = ttk.LabelFrame(root, text=f'wallpaper pkg 文件列表{list_hint}', padding=(10, 10))
frame_list.grid(row=1, column=0, sticky='nsew', padx=14, pady=(10, 0))
frame_list.columnconfigure(0, weight=1)
frame_list.rowconfigure(0, weight=1)

listbox = tk.Listbox(
    frame_list, selectmode=tk.EXTENDED, activestyle='none', font=FONT_NORMAL,
    background='white', foreground=COLOR_TEXT,
    selectbackground=COLOR_ACCENT, selectforeground='white',
    relief='flat', borderwidth=1, highlightthickness=0,
)
listbox.grid(row=0, column=0, sticky='nsew')

list_scroll_y = ttk.Scrollbar(frame_list, orient='vertical', command=listbox.yview)
list_scroll_y.grid(row=0, column=1, sticky='ns')
list_scroll_x = ttk.Scrollbar(frame_list, orient='horizontal', command=listbox.xview)
list_scroll_x.grid(row=1, column=0, sticky='ew')
listbox.config(yscrollcommand=list_scroll_y.set, xscrollcommand=list_scroll_x.set)
listbox.bind('<<ListboxSelect>>', on_listbox_select)

btn_col = ttk.Frame(frame_list)
btn_col.grid(row=0, column=2, rowspan=2, sticky='ns', padx=(10, 0))
btn_add = ttk.Button(btn_col, text='添加...', command=add_multiple); btn_add.pack(fill='x', pady=2)
btn_remove = ttk.Button(btn_col, text='移除选中', command=remove_selected); btn_remove.pack(fill='x', pady=2)
btn_clear = ttk.Button(btn_col, text='清空列表', command=clear_list); btn_clear.pack(fill='x', pady=2)

# 注册拖放目标，需要 tkinterdnd2 可用
if HAS_DND:
    try:
        listbox.drop_target_register(DND_FILES)
        listbox.dnd_bind('<<Drop>>', on_drop)
    except Exception as e:
        print(f'[拖放] 注册失败: {e}')


# 操作区
frame_action = ttk.Frame(root, padding=(14, 10, 14, 0))
frame_action.grid(row=2, column=0, sticky='ew')
frame_action.columnconfigure(0, weight=1)

var_separate = tk.BooleanVar(value=False)
cb_separate = tk.Checkbutton(
    frame_action, text='单独文件夹模式', variable=var_separate,
    background=COLOR_BG, foreground=COLOR_TEXT, font=FONT_NORMAL,
    activebackground=COLOR_BG, activeforeground=COLOR_TEXT,
    selectcolor='white',
)
cb_separate.grid(row=0, column=0, columnspan=2, sticky='w', pady=(0, 8))

progress = ttk.Progressbar(frame_action, mode='determinate')
progress.grid(row=1, column=0, columnspan=2, sticky='ew', pady=(0, 6))

progress_label = ttk.Label(frame_action, text='0/0')
progress_label.grid(row=2, column=0, sticky='w')

btn_bar = ttk.Frame(frame_action)
btn_bar.grid(row=2, column=1, sticky='e')
button_extract = ttk.Button(btn_bar, text='开始提取', command=extract, style='Accent.TButton')
button_extract.pack(side='left', padx=(0, 8))
button_cancel = ttk.Button(btn_bar, text='取消', command=cancel_extract,
                           state='disabled', style='Danger.TButton')
button_cancel.pack(side='left')


# 日志卡片
frame_log = ttk.LabelFrame(root, text='日志', padding=(10, 10))
frame_log.grid(row=3, column=0, sticky='nsew', padx=14, pady=(10, 0))
frame_log.columnconfigure(0, weight=1)
frame_log.rowconfigure(0, weight=1)

log_text = tk.Text(frame_log, height=8, wrap='word', font=FONT_SMALL,
                   background='white', foreground=COLOR_TEXT,
                   relief='flat', borderwidth=1, highlightthickness=0, state='disabled')
log_text.grid(row=0, column=0, sticky='nsew')
log_scroll = ttk.Scrollbar(frame_log, orient='vertical', command=log_text.yview)
log_scroll.grid(row=0, column=1, sticky='ns')
btn_clear_log = ttk.Button(frame_log, text='清除日志', command=clear_log)
btn_clear_log.grid(row=0, column=2, sticky='n', padx=(10, 0))
log_text.config(yscrollcommand=log_scroll.set)


# 状态栏
status_text = tk.StringVar(value='就绪')
status_bar = tk.Label(root, textvariable=status_text, anchor='w',
                      background=COLOR_STATUS_BG, foreground=COLOR_TEXT,
                      font=FONT_SMALL, padx=14, pady=6,
                      relief='flat', borderwidth=0)
status_bar.grid(row=4, column=0, sticky='ew', padx=14, pady=(10, 0))


# 底部版权，居中排列，链接可点击
frame_footer = tk.Frame(root, background=COLOR_BG)
frame_footer.grid(row=5, column=0, pady=(8, 10))

tk.Label(frame_footer, text='原作：', font=FONT_SMALL,
         foreground=COLOR_MUTED, background=COLOR_BG).pack(side='left')
link_label = tk.Label(frame_footer, text='GitHub · RePKG-GUI',
                      font=(FONT_FAMILY, 9, 'underline'),
                      foreground=COLOR_LINK, cursor='hand2', background=COLOR_BG)
link_label.pack(side='left')
tk.Label(frame_footer, text='  |  二次开发：NovaGlaxy', font=FONT_SMALL,
         foreground=COLOR_MUTED, background=COLOR_BG).pack(side='left')


def _open_github(_event=None):
    """在系统默认浏览器中打开原作仓库。"""
    webbrowser.open('https://github.com/Keineliebeundkeinleid/RePKG-GUI')


link_label.bind('<Button-1>', _open_github)


# Tooltip 绑定，覆盖所有可交互控件
Tooltip(button_RePKG, '本程序自动加载RePKG.exe , 启动时会自动识别, 无需手动选择。')
Tooltip(entry_repkg, 'RePKG.exe 的完整路径。\n'
        '本程序自动加载RePKG.exe , 启动时会自动识别, 无需手动选择。')
Tooltip(button_save, '点击选择提取结果的保存位置。')
Tooltip(entry_save, '提取结果保存的根目录。\n'
                '可手动粘贴, 回车或点击其他位置后生效。')
Tooltip(listbox, '待提取的 pkg 文件列表。\n'
        '· 支持 Ctrl/Shift 多选\n'
        '· 支持拖放 .pkg 文件到此处\n'
        '· 每行显示状态 + 省略后的路径\n'
        '· 选中一行时状态栏显示完整路径\n'
        '   ⚪ 待处理  ⏳ 提取中  ✓ 成功  ✗ 失败  — 已取消')
Tooltip(btn_add, '点击打开文件选择框, 可按住 Ctrl/Shift 一次选择多个 .pkg 文件。')
Tooltip(btn_remove, '先在列表中选中一项或多项 (Ctrl/Shift 多选), 再点此按钮移除。')
Tooltip(btn_clear, '清空列表中的所有 pkg 文件 (需二次确认)。\n不会删除磁盘上的原始文件。')
Tooltip(cb_separate, '只是提取图片没有别的用途可不勾选\n\n'
        '开启后：每个 pkg 提取到独立子文件夹\n'
        '提取完成后自动打开保存根目录\n\n'
        '关闭后: 所有 pkg 都提取到 <保存位置>/materials/\n'
        '同名文件会互相覆盖导致混乱, 完成后自动打开 materials。')
Tooltip(progress_label, '已处理数量 / 总数量。')
Tooltip(button_extract, '按列表顺序依次提取所有 pkg 文件。\n'
        '提取期间可随时点"取消"。\n'
        '提取全部成功后会按当前模式自动打开对应目录。')
Tooltip(button_cancel, '终止当前正在提取的 pkg, 并跳过列表中尚未处理的文件。\n'
        '已完成的 pkg 结果会保留。')
Tooltip(log_text, '实时日志: 显示每个 pkg 的提取进度、目标目录、\n'
        '成功/失败状态以及 RePKG 的原始输出。')
Tooltip(btn_clear_log, '清空日志区显示的所有内容。\n不影响已提取的文件, 也不影响列表中的 pkg。')
Tooltip(link_label, '点击在浏览器中打开 GitHub 页面。')


# 窗口几何保存
#
# 拖动或缩放窗口会连续触发 <Configure>，这里用 debounce 延迟 600ms
# 再写盘，避免高频 IO 拖慢窗口响应。
_geo_job = [None]


def _save_geometry():
    """把当前窗口几何写入配置文件。"""
    try:
        save_text('window-geometry.txt', root.geometry())
    except Exception as e:
        print(f'[几何] 保存失败: {e}')


def _on_configure(event):
    """窗口尺寸或位置变化时重排一次延迟保存任务。"""
    if event.widget is not root:
        return
    if _geo_job[0]:
        try:
            root.after_cancel(_geo_job[0])
        except Exception:
            pass
    _geo_job[0] = root.after(600, _save_geometry)


root.bind('<Configure>', _on_configure)


# 关闭处理

def on_close():
    """关闭窗口前，若正在提取则先确认并终止子进程。

    直接 destroy 会让后台线程持有残留的 RePKG 进程，这里先发
    terminate 再 destroy，避免出现孤立进程。
    """
    if is_extracting:
        if not messagebox.askyesno('确认', '正在提取, 确定退出?'):
            return
        cancel_event.set()
        if current_proc:
            try:
                current_proc.terminate()
            except Exception:
                pass
    root.destroy()


root.protocol('WM_DELETE_WINDOW', on_close)


# 未识别到 RePKG 的启动提示

def _show_missing_repkg_dialog():
    """主窗口就绪后弹出提示，引导用户手动指定 RePKG.exe。

    用 after 延迟调用而不是直接弹，是为了让主窗口先绘制出来。
    这样提示框会挂在主窗口之上，用户也能看清背后的界面。
    """
    messagebox.showwarning(
        '未识别到 RePKG',
        '未在程序目录或已配置路径中找到 RePKG.exe。\n\n'
        '请点击「RePKG程序位置」右侧的「选择...」按钮手动指定，\n'
        '或把 RePKG.exe 放到本程序同一目录后重启。'
    )


if repkg_missing:
    # 延迟 200ms 等待主窗口完成首帧绘制，弹窗才会居中于主窗口
    root.after(200, _show_missing_repkg_dialog)


# 初始日志

log('RePKG GUI 已启动')
if RePKG_path:
    log(f'RePKG: {RePKG_path}')
else:
    log('RePKG: 未识别, 请手动选择')
log(f'保存位置: {save_path}')
log('提示: 可以直接拖放 .pkg 文件到列表区域')
log('提示: 单独文件夹模式默认关闭; 勾选后每个 pkg 单独生成文件夹')
log('提示: 鼠标悬停在任意按钮/输入框上 1.5 秒可查看操作说明')


root.mainloop()
