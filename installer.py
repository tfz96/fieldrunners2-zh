"""Small Windows GUI, also usable with an ordinary Python installation."""
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import patcher


def show_gui():
    app = tk.Tk()
    app.title(f'坚守阵地 2 · 简体中文补丁 {patcher.VERSION}')
    app.geometry('780x540')
    app.minsize(700, 500)
    app.option_add('*Font', ('Microsoft YaHei UI', 10))
    style = ttk.Style(app)
    style.theme_use('clam')
    outer = ttk.Frame(app, padding=24)
    outer.pack(fill='both', expand=True)
    ttk.Label(outer, text='Fieldrunners 2 简体中文补丁', font=('Microsoft YaHei UI', 18, 'bold')).pack(anchor='w')
    ttk.Label(outer, text='适用于 Steam Windows 版 · build 37185 · 测试版', foreground='#555555').pack(anchor='w', pady=(6, 18))
    ttk.Label(outer, text='游戏文件夹（包含 Fieldrunners2.exe）').pack(anchor='w')
    path = tk.StringVar(value=str(patcher.detect_game() or ''))
    row = ttk.Frame(outer)
    row.pack(fill='x', pady=(6, 16))
    entry = ttk.Entry(row, textvariable=path)
    entry.pack(side='left', fill='x', expand=True)
    def browse():
        chosen = filedialog.askdirectory(title='选择 Fieldrunners 2 游戏文件夹', initialdir=path.get() or None)
        if chosen:
            path.set(chosen)
    browse_button = ttk.Button(row, text='浏览…', command=browse)
    browse_button.pack(side='left', padx=(8, 0))
    ttk.Label(outer, text='请先关闭游戏。安装会保留原版备份；还原按钮可恢复英文。\n只处理 Data.pak 和 Fieldrunners2.dll，不修改存档或 Steam 客户端。',
              wraplength=710).pack(anchor='w')
    buttons = ttk.Frame(outer)
    buttons.pack(fill='x', pady=18)
    output = tk.Text(outer, height=11, wrap='word', relief='solid', borderwidth=1, state='disabled',
                     font=('Microsoft YaHei UI', 10), padx=10, pady=10)
    output.pack(fill='both', expand=True)
    events = queue.Queue()
    controls = [entry, browse_button]
    busy = False
    def log(text):
        output.configure(state='normal')
        output.insert('end', str(text) + '\n')
        output.see('end')
        output.configure(state='disabled')
    def run(action):
        nonlocal busy
        if busy:
            return
        if not path.get().strip():
            messagebox.showerror('未选择游戏', '请选择游戏文件夹。', parent=app)
            return
        busy = True
        for widget in controls:
            widget.configure(state='disabled')
        selected = path.get().strip()
        log({'install': '开始安装汉化…', 'restore': '开始还原原版…', 'verify': '开始校验…'}[action])
        def work():
            try:
                if action == 'verify':
                    events.put(('log', patcher.verify(selected)))
                else:
                    getattr(patcher, action)(selected, lambda text: events.put(('log', text)))
                events.put(('done', None))
            except Exception as exc:
                events.put(('error', str(exc)))
        threading.Thread(target=work, daemon=True).start()
    for text, action in [('安装 / 更新汉化', 'install'), ('还原原版', 'restore'), ('校验文件', 'verify')]:
        button = ttk.Button(buttons, text=text, command=lambda a=action: run(a))
        button.pack(side='left', padx=(0, 12))
        controls.append(button)
    def poll():
        nonlocal busy
        while True:
            try:
                kind, text = events.get_nowait()
            except queue.Empty:
                break
            if kind == 'log':
                log(text)
            else:
                busy = False
                for widget in controls:
                    widget.configure(state='normal')
                if kind == 'error':
                    log('操作失败：' + text)
                    messagebox.showerror('操作失败', text, parent=app)
                else:
                    log('操作完成。')
        app.after(100, poll)
    def close():
        if busy:
            messagebox.showinfo('正在处理', '请等待操作完成后再关闭窗口。', parent=app)
        else:
            app.destroy()
    app.protocol('WM_DELETE_WINDOW', close)
    log('准备就绪。安装完成后，请通过 Steam 启动游戏。')
    poll()
    app.mainloop()
    return 0
