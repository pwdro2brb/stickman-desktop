from __future__ import annotations

import math
import random
import sys
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from .animation import CharacterRenderer, Particles
from .config import load_config
from .environment import desktop_surfaces, nearest_monitor, virtual_bounds
from .motion import Motion
from .core import parse_command
from .windows import (
    GlobalHotkeys,
    MonitorInfo,
    WindowInfo,
    cursor_position,
    enumerate_monitors,
    position_overlay,
    enumerate_visible_windows,
    foreground_window,
    launch,
    minimize_window,
    set_click_through,
    top_level_window,
)

TRANSPARENT = "#ff00ff"


class StickmanDesktop:
    def __init__(self) -> None:
        if sys.platform != "win32":
            raise RuntimeError("Stickman Desktop requer Windows 10 ou 11.")
        project_root = Path(__file__).resolve().parents[2]
        self.config = load_config(project_root / "config.json")
        character = self.config["character"]

        self.root = tk.Tk()
        self.root.title("Stickman Desktop")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=TRANSPARENT)
        self.root.wm_attributes("-transparentcolor", TRANSPARENT)

        try:
            self.monitors = enumerate_monitors()
        except OSError:
            rect = (0, 0, self.root.winfo_screenwidth(), self.root.winfo_screenheight())
            self.monitors = [MonitorInfo(rect, rect, True)]
        left, top, right, bottom = virtual_bounds(self.monitors)
        self.origin_x, self.origin_y = left, top
        self.sw, self.sh = right - left, bottom - top
        self.root.geometry(f"{self.sw}x{self.sh}+0+0")
        self.canvas = tk.Canvas(self.root, bg=TRANSPARENT, width=self.sw, height=self.sh,
                                highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)

        self.name = character.get("name", "Pixel")
        self.color = character.get("color", "#ff7a00")
        self.ground_offset = max(0.0, float(character.get("ground_offset", 72)))
        primary = next((m for m in self.monitors if m.primary), self.monitors[0])
        pl, _pt, pr, pb = primary.work_rect
        start_x = max(pl + 28, min(pr - 28, pl + float(character.get("start_x", 120))))
        self.motion = Motion(self.sw, self.sh, start_x - left, pb - top - self.ground_offset)
        self.frame = 0
        self.behavior = "manual"
        self.pose: str | None = None
        self.pose_until = 0.0
        self.story_running = False
        self._story_jobs: set[str] = set()
        self._scene_jobs: set[str] = set()
        self._scene_items: set[int] = set()
        self._echo_visible = False
        self._next_spark = 0.0
        self._next_decision = 0.0
        self._next_monitor_scan = time.monotonic() + 1
        self._last_tick = time.monotonic()
        self._drag_anchor = None
        self._dragging = False
        self._drag_sample = None
        self._drag_velocity = (0.0, 0.0)
        self.bubble_until = 0.0
        self.command_open = False
        self.click_through = False
        self.visible_windows: list[WindowInfo] = []
        self.last_external_window: WindowInfo | None = None
        self.window_scan_failed = False
        self.panel_hwnd = 0
        self.windows_panel: tk.Toplevel | None = None
        self.windows_tree: ttk.Treeview | None = None
        self.windows_status: tk.StringVar | None = None

        self._sync_surfaces()
        self._draw_character()
        self._draw_control()
        self.root.update_idletasks()
        position_overlay(int(self.root.winfo_id()), virtual_bounds(self.monitors))
        self.canvas.tag_bind("character", "<ButtonPress-1>", self._begin_drag)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._end_drag)
        self.canvas.tag_bind("character", "<Double-Button-1>", self._double_click)
        self.canvas.tag_bind("character", "<Button-3>", self._character_menu)
        self.hotkeys = GlobalHotkeys()
        self.hotkeys.register()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(100, self._capture_external_window)
        self.root.after(20, self._poll_hotkeys)
        self.root.after(16, self._tick)
        self.say("Olá! F2 abre comandos, F3 libera cliques e F4 inicia uma história.", 6)

    @property
    def own_hwnds(self) -> set[int]:
        values = {int(self.root.winfo_id())}
        if self.panel_hwnd:
            values.add(int(self.panel_hwnd))
        if self.windows_panel is not None:
            values.add(int(self.windows_panel.winfo_id()))
        # Tk's widget handle may be a child of its native top-level wrapper.
        values.update(top_level_window(hwnd) for hwnd in tuple(values))
        values.discard(0)
        return values

    def _draw_control(self) -> None:
        self.control = tk.Button(self.root, text="☰", command=self.open_command_panel,
                                 bg="#202020", fg="white", activebackground="#333333",
                                 activeforeground="white", bd=0, font=("Segoe UI", 12, "bold"))
        self._place_control()

    @property
    def x(self) -> float:
        return self.motion.x

    @property
    def y(self) -> float:
        return self.motion.y

    @property
    def direction(self) -> int:
        return self.motion.direction

    @property
    def mode(self) -> str:
        if self.pose and time.monotonic() < self.pose_until:
            return self.pose
        return self.motion.mode

    def _place_control(self) -> None:
        primary = next((m for m in self.monitors if m.primary), self.monitors[0])
        self.control.place(x=primary.work_rect[0] - self.origin_x + 12,
                           y=primary.work_rect[1] - self.origin_y + 12, width=38, height=34)

    def _sync_surfaces(self) -> None:
        self.motion.set_surfaces(desktop_surfaces(
            self.monitors, self.visible_windows, (self.origin_x, self.origin_y),
            self.ground_offset, self.motion.support_key, self.x,
        ))

    def _refresh_desktop(self) -> None:
        now = time.monotonic()
        if now < self._next_monitor_scan:
            return
        self._next_monitor_scan = now + 1
        try:
            monitors = enumerate_monitors()
            if monitors == self.monitors:
                return
            left, top, right, bottom = virtual_bounds(monitors)
            position_overlay(int(self.root.winfo_id()), (left, top, right, bottom))
        except OSError:
            return
        if self._drag_anchor is not None:
            self._end_drag()
        was_story = self.story_running
        self._cancel_story()
        self.pose = None
        self.particles.clear()
        if was_story:
            self.motion.stop()
        self.motion.reframe(right - left, bottom - top,
                            self.origin_x - left, self.origin_y - top)
        self.monitors = monitors
        self.origin_x, self.origin_y = left, top
        self.sw, self.sh = right - left, bottom - top
        self.canvas.configure(width=self.sw, height=self.sh)
        if not self.click_through:
            self._place_control()
        self._sync_surfaces()

    def _draw_character(self) -> None:
        self.actor = CharacterRenderer(self.canvas, self.color)
        self.echo = CharacterRenderer(self.canvas, "#8970ff", tag="echo")
        self.echo.set_visible(False)
        self.particles = Particles(self.canvas)
        self.bubble = self.canvas.create_rectangle(0, 0, 0, 0, fill="#fff9eb",
                                                   outline="#333333", width=2, state="hidden")
        self.bubble_text = self.canvas.create_text(0, 0, text="", fill="#111111",
                                                   font=("Segoe UI", 11), width=326,
                                                   anchor="nw", state="hidden")

    def _work_area(self) -> tuple[float, float, float, float]:
        monitor = nearest_monitor(self.monitors, self.x + self.origin_x, self.y + self.origin_y)
        left, top, right, bottom = monitor.work_rect
        return left - self.origin_x, top - self.origin_y, right - self.origin_x, bottom - self.origin_y

    def _render(self) -> None:
        now = time.monotonic()
        self.actor.render(self.x, self.y, self.direction, self.mode, now, self.motion.vy)
        self.echo.set_visible(self._echo_visible)
        if self._echo_visible:
            left, _top, right, _bottom = self._work_area()
            echo_x = max(left + 40, min(right - 40, self.x + self.direction * 140))
            self.echo.render(echo_x, self.y, -self.direction, "fight", now + 0.2)
            if now >= self._next_spark:
                self._next_spark = now + 0.13
                self.particles.burst((self.x + echo_x) / 2, self.y - 48, count=5)
        if now < self.bubble_until:
            left, top, right, bottom = self._work_area()
            width = min(350, right - left - 24)
            bx = max(left + 12, min(right - width - 12, self.x + 30))
            by = max(top + 12, self.y - 200)
            self.canvas.itemconfigure(self.bubble_text, state="normal", width=width - 24)
            self.canvas.coords(self.bubble_text, bx + 12, by + 10)
            bounds = self.canvas.bbox(self.bubble_text)
            height = max(54, bounds[3] - by + 12) if bounds else 70
            by = max(top + 12, min(by, bottom - height - 12))
            self.canvas.coords(self.bubble_text, bx + 12, by + 10)
            self.canvas.coords(self.bubble, bx, by, bx + width, by + height)
            self.canvas.itemconfigure(self.bubble, state="normal")
            self.canvas.tag_raise(self.bubble)
            self.canvas.tag_raise(self.bubble_text)
        else:
            self.canvas.itemconfigure(self.bubble, state="hidden")
            self.canvas.itemconfigure(self.bubble_text, state="hidden")

    def _capture_external_window(self) -> None:
        self._refresh_desktop()
        self._refresh_windows()
        self.root.after(250, self._capture_external_window)

    def _refresh_windows(self) -> bool:
        excluded = self.own_hwnds
        try:
            self.visible_windows = enumerate_visible_windows(excluded)
        except OSError:
            self.visible_windows = []
            self.last_external_window = None
            self.window_scan_failed = True
            self._sync_surfaces()
            self._update_window_list()
            return False

        self.window_scan_failed = False
        by_handle = {info.hwnd: info for info in self.visible_windows}
        candidate = foreground_window(excluded)
        if candidate is not None:
            self.last_external_window = by_handle.get(candidate.hwnd)
        elif self.last_external_window is not None:
            self.last_external_window = by_handle.get(self.last_external_window.hwnd)
        self._sync_surfaces()
        self._update_window_list()
        return True

    def show_window_list(self) -> None:
        if self.windows_panel is not None:
            self._refresh_windows()
            self.windows_panel.deiconify()
            self.windows_panel.lift()
            if self.windows_tree is not None:
                self.windows_tree.focus_force()
            return

        panel = tk.Toplevel(self.root)
        self.windows_panel = panel
        panel.title("Janelas visíveis — Stickman Desktop")
        panel.geometry("760x400+80+80")
        panel.minsize(620, 280)
        panel.attributes("-topmost", True)
        panel.configure(bg="#171717")
        panel.protocol("WM_DELETE_WINDOW", self._close_window_list)
        panel.bind("<Escape>", lambda _event: self._close_window_list())
        tk.Label(panel, text="Janelas visíveis", bg="#171717", fg="white",
                 font=("Segoe UI", 16, "bold")).pack(anchor="w", padx=18, pady=(18, 6))
        tk.Label(panel, text="Títulos, dimensões e posições atualizados automaticamente.",
                 bg="#171717", fg="#bdbdbd", font=("Segoe UI", 10)).pack(anchor="w", padx=18)

        frame = tk.Frame(panel, bg="#171717")
        frame.pack(fill="both", expand=True, padx=18, pady=14)
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        tree = ttk.Treeview(frame, columns=("title", "size", "position"),
                            show="headings", selectmode="browse")
        self.windows_tree = tree
        tree.heading("title", text="Janela")
        tree.heading("size", text="Dimensões (px)")
        tree.heading("position", text="Posição (x, y)")
        tree.column("title", width=380, minwidth=220)
        tree.column("size", width=130, minwidth=110, anchor="center", stretch=False)
        tree.column("position", width=150, minwidth=120, anchor="center", stretch=False)
        vertical = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        horizontal = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        tree.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")

        row = tk.Frame(panel, bg="#171717")
        row.pack(fill="x", padx=18, pady=(0, 14))
        self.windows_status = tk.StringVar(panel)
        tk.Label(row, textvariable=self.windows_status, bg="#171717", fg="#bdbdbd",
                 font=("Segoe UI", 10)).pack(side="left")
        tk.Button(row, text="Fechar", command=self._close_window_list,
                  bg="#333333", fg="white", bd=0, font=("Segoe UI", 11),
                  padx=20, pady=8).pack(side="right")
        panel.update_idletasks()
        self._refresh_windows()
        tree.focus_force()

    def _update_window_list(self) -> None:
        if self.windows_tree is None or self.windows_status is None:
            return
        tree = self.windows_tree
        remaining = set(tree.get_children())
        for index, info in enumerate(self.visible_windows):
            key = str(info.hwnd)
            left, top, right, bottom = info.rect
            values = (info.title, f"{right-left} × {bottom-top}", f"{left}, {top}")
            if key in remaining:
                remaining.remove(key)
                if tuple(tree.item(key, "values")) != values:
                    tree.item(key, values=values)
                tree.move(key, "", index)
            else:
                tree.insert("", index, iid=key, values=values)
        for key in remaining:
            tree.delete(key)
        count = len(self.visible_windows)
        if self.window_scan_failed:
            status = "Não foi possível consultar as janelas. Tentando novamente…"
        elif count == 0:
            status = "Nenhuma janela visível encontrada."
        elif count == 1:
            status = "1 janela visível."
        else:
            status = f"{count} janelas visíveis."
        self.windows_status.set(status)

    def _close_window_list(self) -> None:
        panel = self.windows_panel
        self.windows_panel = self.windows_tree = self.windows_status = None
        if panel is not None:
            panel.destroy()

    def _poll_hotkeys(self) -> None:
        for event in self.hotkeys.poll():
            if event == 1:
                self.open_command_panel()
            elif event == 2:
                self.toggle_click_through()
            elif event == 3:
                self.start_story()
        self.root.after(20, self._poll_hotkeys)

    def say(self, text: str, seconds: float = 4) -> None:
        self.canvas.itemconfigure(self.bubble_text, text=text[:320] + ("…" if len(text) > 320 else ""))
        self.bubble_until = time.monotonic() + seconds

    def _take_control(self) -> None:
        self._end_drag()
        self.behavior = "manual"
        self.pose = None
        self._cancel_story()

    def walk_to(self, x: float) -> None:
        if not math.isfinite(float(x)):
            raise ValueError("A posição deve ser um número finito.")
        self._take_control()
        self.motion.walk_to(float(x) - self.origin_x)

    def jump(self) -> None:
        self._take_control()
        self.motion.jump()

    def climb_window(self) -> None:
        self._take_control()
        self._refresh_windows()
        info = self.last_external_window
        if info is None:
            self.say("Selecione uma janela externa e use subir na janela.", 5)
        elif self.motion.leap_to(f"window:{info.hwnd}"):
            self.say(f"Vou subir em {info.title[:80]}!", 4)
        else:
            self.say("Preciso de uma borda livre. Mova a janela mais para baixo ou aumente sua largura.", 6)

    def descend(self) -> None:
        self._take_control()
        if self.motion.drop():
            self.say("Lá vou eu!", 2)
        else:
            self.say("Já estou no chão.", 2)

    def stop(self) -> None:
        self._take_control()
        self.motion.stop()
        self.say("Pausa. Estou por aqui!", 3)

    def wave(self) -> None:
        self._take_control()
        self.motion.stop()
        self.pose, self.pose_until = "wave", time.monotonic() + 2.8
        self.say("Oi! Vamos explorar esse desktop?", 3)

    def explore(self) -> None:
        self._take_control()
        self.motion.stop()
        self.behavior, self._next_decision = "explore", 0
        self.say("Vou passear pelas bordas das janelas. Diga parar quando quiser.", 5)

    def follow_mouse(self) -> None:
        self._take_control()
        self.motion.stop()
        self.behavior, self._next_decision = "follow", 0
        self.say("Vou acompanhar seu cursor. Diga parar para descansar.", 4)

    def _update_behavior(self, now: float) -> None:
        if self.behavior == "manual" or self.command_open or self._drag_anchor is not None:
            return
        if now < self._next_decision:
            return
        if self.behavior == "follow":
            self._next_decision = now + 0.1
            try:
                x, _y = cursor_position()
            except OSError:
                return
            if abs(x - self.origin_x - self.x) > 55:
                self.motion.walk_to(x - self.origin_x)
            else:
                self.motion.stop()
            return
        self._next_decision = now + random.uniform(3, 5)
        if not self.motion.grounded:
            self._next_decision = now + 0.5
            return
        options = [surface for surface in self._playground()
                   if surface.kind == "window" and surface.key != self.motion.support_key]
        if options and random.random() < 0.6:
            self.motion.leap_to(random.choice(options).key)
        elif self.motion.support is not None:
            support = self.motion.support
            if support.kind == "window" and random.random() < 0.2:
                self.motion.drop()
            else:
                self.motion.walk_to(random.uniform(support.left + 28, support.right - 28))
                if random.random() < 0.25:
                    self.motion.jump()

    def _playground(self):
        return desktop_surfaces(self.monitors, self.visible_windows,
                                (self.origin_x, self.origin_y), self.ground_offset,
                                self.motion.support_key, self.x)

    def _begin_drag(self, event) -> None:
        if self.click_through:
            return
        self._take_control()
        self.motion.stop()
        self._drag_anchor = (self.x - (event.x_root - self.origin_x),
                             self.y - (event.y_root - self.origin_y), event.x_root, event.y_root)
        self._drag_sample = (time.monotonic(), self.x, self.y)
        self._drag_velocity = (0.0, 0.0)
        self._dragging = False
        self.canvas.grab_set()

    def _drag(self, event) -> None:
        if self._drag_anchor is None:
            return
        dx, dy, start_x, start_y = self._drag_anchor
        if not self._dragging and abs(event.x_root - start_x) + abs(event.y_root - start_y) < 4:
            return
        x, y = event.x_root - self.origin_x + dx, event.y_root - self.origin_y + dy
        monitor = nearest_monitor(self.monitors, x + self.origin_x, y + self.origin_y)
        left, top, right, bottom = monitor.work_rect
        x = max(left - self.origin_x + 28, min(right - self.origin_x - 28, x))
        y = max(top - self.origin_y + 104,
                min(bottom - self.origin_y - self.ground_offset, y))
        now = time.monotonic()
        if self._drag_sample is not None:
            previous, px, py = self._drag_sample
            elapsed = max(0.016, now - previous)
            self._drag_velocity = ((x - px) / elapsed, (y - py) / elapsed)
        self._drag_sample = (now, x, y)
        self._dragging = True
        self.motion.drag_to(x, y)

    def _end_drag(self, _event=None) -> None:
        if self._drag_anchor is None:
            return
        if self._dragging:
            velocity = self._drag_velocity
            if self._drag_sample is None or time.monotonic() - self._drag_sample[0] > 0.12:
                velocity = (0.0, 0.0)
            self.motion.release(*velocity)
        self._drag_anchor = self._drag_sample = None
        self._dragging = False
        self.canvas.grab_release()

    def _double_click(self, _event) -> str:
        self._end_drag()
        self.jump()
        return "break"

    def _character_menu(self, event) -> None:
        self._refresh_windows()
        menu = tk.Menu(self.root, tearoff=False)
        for label, command in [
            ("Pular", self.jump), ("Subir na janela", self.climb_window),
            ("Descer", self.descend), ("Explorar", self.explore),
            ("Seguir mouse", self.follow_mouse), ("Acenar", self.wave),
            ("Parar", self.stop), ("História", self.start_story),
            ("Comandos (F2)", self.open_command_panel),
            ("Liberar cliques (F3)", self.toggle_click_through), ("Sair", self.close),
        ]:
            menu.add_command(label=label, command=command)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
            menu.destroy()

    def toggle_click_through(self) -> None:
        self._end_drag()
        self.click_through = not self.click_through
        set_click_through(top_level_window(int(self.root.winfo_id())), self.click_through)
        if self.click_through:
            self.control.place_forget()
        else:
            self._place_control()
            self.root.lift()
            self.say("Modo interativo restaurado.", 3)

    def inspect(self) -> None:
        self._refresh_windows()
        info = self.last_external_window
        if not info:
            self.say("Não encontrei uma janela externa válida.", 4)
            return
        left, top, right, bottom = info.rect
        self.say(f"Janela: {info.title}\nÁrea: {right-left} × {bottom-top} px", 6)
        self.walk_to((left+right)/2)

    def minimize_external(self) -> None:
        if not self.config.get("safety", {}).get("allow_window_minimize", True):
            self.say("Minimização desativada no config.json.", 4)
            return
        self._refresh_windows()
        info = self.last_external_window
        if not info or info.hwnd in self.own_hwnds:
            self.say("Selecione uma janela externa e tente novamente.", 4)
            return
        if minimize_window(info.hwnd, self.own_hwnds):
            self.say(f"Janela minimizada: {info.title}", 4)
        else:
            self.say("O Windows não minimizou essa janela.", 4)

    def open_allowed_app(self, key: str) -> None:
        if not self.config.get("safety", {}).get("allow_process_launch", True):
            self.say("Abertura de aplicativos desativada.", 4)
            return
        command = self.config.get("authorized_apps", {}).get(key)
        if not command:
            self.say(f"Aplicativo não autorizado: {key}", 5)
            return
        launch(command)
        self.say(f"Abrindo {key}. Ação autorizada pelo config.json.", 4)

    def _schedule_scene(self, delay: int, callback, story: bool = False) -> None:
        jobs = self._story_jobs if story else self._scene_jobs
        def run() -> None:
            jobs.discard(token)
            if not story or self.story_running:
                callback()
        token = self.root.after(delay, run)
        jobs.add(token)

    def _cancel_story(self) -> None:
        self.story_running = False
        for jobs in (self._story_jobs, self._scene_jobs):
            for token in tuple(jobs):
                self.root.after_cancel(token)
            jobs.clear()
        for item in self._scene_items:
            self.canvas.delete(item)
        self._scene_items.clear()
        self._echo_visible = False

    def portal(self, manual: bool = True) -> None:
        if manual:
            self._take_control()
        self.pose = None
        self._echo_visible = False
        left, top, right, bottom = self._work_area()
        center = max(left + 70, min(right - 70, self.x + self.direction * 180))
        cy = max(top + 115, min(bottom - 115, self.y - 90))
        ids = []
        for radius, color, width in [(48, "#00d7ff", 6), (39, "#8970ff", 3), (30, "#b2f5ff", 2)]:
            ids.append(self.canvas.create_oval(center - radius, cy - 95,
                                              center + radius, cy + 95, outline=color, width=width))
        self._scene_items.update(ids)
        self.motion.walk_to(center)
        self.particles.burst(center, cy, color="#00d7ff", count=20)
        self.say("Um atalho para a próxima aventura!", 4)
        def cleanup() -> None:
            for item in ids:
                self.canvas.delete(item)
                self._scene_items.discard(item)
        self._schedule_scene(6000, cleanup)

    def start_story(self) -> None:
        if self.story_running:
            return
        self._take_control()
        self.motion.stop()
        self.story_running = True
        self.say("Um eco digital quer testar meus reflexos…", 4)
        left, _top, right, _bottom = self._work_area()
        self._schedule_scene(2000, lambda: self.motion.walk_to((left + right) / 2), story=True)
        self._schedule_scene(4500, self._fight, story=True)
        self._schedule_scene(9500, lambda: self.portal(manual=False), story=True)
        self._schedule_scene(16000, self._finish_story, story=True)

    def _fight(self) -> None:
        self.motion.stop()
        self.pose, self.pose_until = "fight", time.monotonic() + 5
        self._echo_visible = True
        self.say("Sua vez, eco!", 3)
        self.particles.burst(self.x + self.direction * 70, self.y - 50, count=16)

    def _finish_story(self) -> None:
        self._cancel_story()
        self.pose = None
        self.motion.stop()
        self.say("Bom treino! Até a próxima aventura.", 4)

    def execute(self, text: str) -> None:
        parsed = parse_command(text)
        if parsed.action == "walk":
            try:
                self.walk_to(float(parsed.argument))
            except ValueError:
                self.say("Use um número, por exemplo: andar 500", 4)
        elif parsed.action == "jump": self.jump()
        elif parsed.action == "climb": self.climb_window()
        elif parsed.action == "descend": self.descend()
        elif parsed.action == "explore": self.explore()
        elif parsed.action == "follow": self.follow_mouse()
        elif parsed.action == "stop": self.stop()
        elif parsed.action == "wave": self.wave()
        elif parsed.action == "inspect": self.inspect()
        elif parsed.action == "list_windows": self.show_window_list()
        elif parsed.action == "minimize": self.minimize_external()
        elif parsed.action == "open": self.open_allowed_app(parsed.argument)
        elif parsed.action == "story": self.start_story()
        elif parsed.action == "portal": self.portal()
        elif parsed.action == "help":
            self.say("subir na janela | descer | explorar | seguir mouse | parar | acenar | andar 500 | pular | listar janelas | história | portal", 10)
        elif parsed.action != "empty":
            self.say("Comando desconhecido. Digite ajuda.", 4)

    def open_command_panel(self) -> None:
        self._end_drag()
        if self.command_open:
            return
        # Capture the external target before the panel takes keyboard focus.
        self._refresh_windows()
        self.command_open = True
        panel = tk.Toplevel(self.root)
        panel.title("Comandos do Stickman")
        panel.geometry("620x390+80+80")
        panel.attributes("-topmost", True)
        panel.configure(bg="#171717")
        panel.update_idletasks()
        self.panel_hwnd = int(panel.winfo_id())
        panel.protocol("WM_DELETE_WINDOW", lambda: self._close_panel(panel))
        tk.Label(panel, text=f"Diga a {self.name} o que fazer", bg="#171717", fg="white",
                 font=("Segoe UI", 16, "bold")).pack(anchor="w", padx=18, pady=(18,6))
        tk.Label(panel, text="Somente ferramentas autorizadas no config.json podem ser executadas.",
                 bg="#171717", fg="#bdbdbd", font=("Segoe UI", 10)).pack(anchor="w", padx=18)
        entry = tk.Entry(panel, font=("Segoe UI", 13), bg="#292929", fg="white",
                         insertbackground="white", relief="flat")
        entry.pack(fill="x", padx=18, pady=16, ipady=9)
        entry.focus_force()
        tk.Label(panel, text="Ex.: subir na janela | explorar | seguir mouse | parar | listar janelas",
                 bg="#171717", fg="#71c7ff", font=("Segoe UI", 10)).pack(anchor="w", padx=18)
        tk.Label(panel, text="Arraste o personagem • Duplo clique para pular • Botão direito para ações",
                 bg="#171717", fg="#bdbdbd", font=("Segoe UI", 10)).pack(anchor="w", padx=18, pady=(8, 0))
        quick = tk.Frame(panel, bg="#171717")
        quick.pack(fill="x", padx=18, pady=(12, 0))
        def quick_run(value: str) -> None:
            self._close_panel(panel)
            self.execute(value)
        for label, command in [("Subir", "subir na janela"), ("Explorar", "explorar"),
                               ("Seguir mouse", "seguir mouse"), ("Acenar", "acenar"), ("Parar", "parar")]:
            tk.Button(quick, text=label, command=lambda value=command: quick_run(value),
                      bg="#292929", fg="white", bd=0, padx=10, pady=6).pack(side="left", padx=(0, 6))
        row = tk.Frame(panel, bg="#171717")
        row.pack(fill="x", padx=18, pady=18)
        def run() -> None:
            value = entry.get()
            self._close_panel(panel)
            self.execute(value)
        tk.Button(row, text="Executar", command=run, bg="#ff7a00", fg="white", bd=0,
                  font=("Segoe UI", 11, "bold"), padx=20, pady=8).pack(side="left")
        tk.Button(row, text="Cancelar", command=lambda: self._close_panel(panel), bg="#333333",
                  fg="white", bd=0, font=("Segoe UI", 11), padx=20, pady=8).pack(side="left", padx=10)
        entry.bind("<Return>", lambda _e: run())

    def _close_panel(self, panel: tk.Toplevel) -> None:
        self.command_open, self.panel_hwnd = False, 0
        panel.destroy()

    def _tick(self) -> None:
        now = time.monotonic()
        dt = min(0.05, max(0.0, now - self._last_tick))
        self._last_tick = now
        self.frame += 1
        self._update_behavior(now)
        was_grounded = self.motion.grounded
        self.motion.step(dt)
        if not was_grounded and self.motion.grounded:
            self.particles.burst(self.x, self.y - 2, color=self.color, count=8)
        self.particles.step(dt)
        self._render()
        self.root.after(16, self._tick)

    def close(self) -> None:
        self._end_drag()
        self._cancel_story()
        self.particles.clear()
        self.hotkeys.close()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    StickmanDesktop().run()


if __name__ == "__main__":
    main()
