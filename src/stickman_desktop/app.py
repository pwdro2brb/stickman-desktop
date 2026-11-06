from __future__ import annotations

import math
import random
import re
import sys
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from .animation import CharacterRenderer, Particles
from .characters import COMPANIONS, DesktopCharacter, find_character, spawn_x
from .config import load_config
from .environment import FOOT_CLEARANCE, desktop_surfaces, nearest_monitor, virtual_bounds
from .gestures import PointerVelocity
from .motion import Motion
from .core import parse_command
from .duel import DuelFrame, FighterPose, TabDuel
from .scenes import BUILTIN_SCENES_DIR, SceneStep, load_scenes
from .sprites import SpritePack, SpriteRenderer
from .tab_effects import TabEffects
from .tray import TrayIcon
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
BROWSER_NAMES = frozenset({"google chrome", "chromium", "microsoft edge", "mozilla firefox",
                           "firefox", "brave", "opera", "vivaldi"})


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

        name = character.get("name", "Pixel")
        color = character.get("color", "#ff7a00")
        self.ground_offset = max(0.0, float(character.get("ground_offset", 0)))
        primary = next((m for m in self.monitors if m.primary), self.monitors[0])
        pl, _pt, pr, pb = primary.work_rect
        start_x = max(pl + 28, min(pr - 28, pl + float(character.get("start_x", 120))))
        motion = Motion(self.sw, self.sh, start_x - left, pb - top - self.ground_offset - FOOT_CLEARANCE)
        renderer = CharacterRenderer(self.canvas, color, tag="actor:pixel")
        self.active_character = DesktopCharacter("pixel", name, color, motion, renderer)
        self.characters = {self.active_character.id: self.active_character}
        self._sprite_pack: SpritePack | None = None
        self.character_picker: ttk.Combobox | None = None
        self.appearance_picker: ttk.Combobox | None = None
        self.character_prompt: tk.StringVar | None = None
        self.add_character_button: tk.Button | None = None
        self.remove_character_button: tk.Button | None = None
        self._tag_character(self.active_character)
        self.hidden = False
        self._closing = False
        self.tray: TrayIcon | None = None
        self.scenes = ()
        self.scene_errors = ()
        self.selected_scene_id = ""
        self.scene_picker: ttk.Combobox | None = None
        self.scene_status: tk.StringVar | None = None
        self.scene_play_button: tk.Button | None = None
        self.command_panel: tk.Toplevel | None = None
        self._story_generation = 0
        self.reload_scenes(notify=False)
        self.frame = 0
        self.story_running = False
        self._story_jobs: set[str] = set()
        self._scene_jobs: set[str] = set()
        self._scene_items: set[int] = set()
        self._duel: TabDuel | None = None
        self._duel_frame: DuelFrame | None = None
        self._duel_last_tick = 0.0
        self._tab_title = "Nova aba"
        self._next_monitor_scan = time.monotonic() + 1
        self._last_tick = time.monotonic()
        self._gaze: tuple[float, float] | None = None
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
        self._draw_effects()
        self._draw_control()
        self.root.update_idletasks()
        position_overlay(int(self.root.winfo_id()), virtual_bounds(self.monitors))
        self.canvas.tag_bind("desktop_character", "<ButtonPress-1>",
                             lambda event: self._actor_event(event, self._begin_drag))
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._end_drag)
        self.canvas.tag_bind("desktop_character", "<Double-Button-1>",
                             lambda event: self._actor_event(event, self._double_click))
        self.canvas.tag_bind("desktop_character", "<Button-3>",
                             lambda event: self._actor_event(event, self._character_menu))
        self.hotkeys = GlobalHotkeys()
        self.hotkeys.register()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        tray_error = False
        try:
            self.tray = TrayIcon()
            self.tray.start()
            self._update_tray()
        except OSError:
            if self.tray is not None:
                self.tray.close()
            self.tray = None
            tray_error = True
        self._loop_jobs = {
            "windows": self.root.after(100, self._capture_external_window),
            "input": self.root.after(20, self._poll_hotkeys),
            "animation": self.root.after(16, self._tick),
        }
        if tray_error:
            self.say("A bandeja está indisponível. F2 abre os comandos; o personagem continuará visível.", 7)
        else:
            self.say("Olá! Estou também na bandeja. F2 abre comandos e F4 inicia a cena selecionada.", 6)

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
    def motion(self) -> Motion:
        return self.active_character.motion

    @property
    def x(self) -> float:
        return self.motion.x

    @property
    def y(self) -> float:
        return self.motion.y

    @property
    def direction(self) -> int:
        return self.motion.direction

    def _place_control(self) -> None:
        primary = next((m for m in self.monitors if m.primary), self.monitors[0])
        self.control.place(x=primary.work_rect[0] - self.origin_x + 12,
                           y=primary.work_rect[1] - self.origin_y + 12, width=38, height=34)

    def _sync_surfaces(self) -> None:
        bounds = [
            (m.work_rect[0] - self.origin_x, m.work_rect[1] - self.origin_y,
             m.work_rect[2] - self.origin_x, m.work_rect[3] - self.origin_y)
            for m in self.monitors
        ]
        for character in self.characters.values():
            character.motion.set_bounds(bounds)
            character.motion.set_surfaces(self._playground(character))

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
        self.active_character.pose = None
        if was_story:
            self.motion.stop()
        for character in self.characters.values():
            character.motion.reframe(right - left, bottom - top,
                                     self.origin_x - left, self.origin_y - top)
        self.monitors = monitors
        self.origin_x, self.origin_y = left, top
        self.sw, self.sh = right - left, bottom - top
        self.canvas.configure(width=self.sw, height=self.sh)
        if not self.click_through:
            self._place_control()
        self._sync_surfaces()

    def _draw_effects(self) -> None:
        self.anomaly = CharacterRenderer(self.canvas, "#a66cff", tag="anomaly")
        self.anomaly.set_visible(False)
        self.tab_effects = TabEffects(self.canvas)
        self.particles = Particles(self.canvas)
        self.bubble = self.canvas.create_rectangle(0, 0, 0, 0, fill="#fff9eb",
                                                   outline="#333333", width=2, state="hidden")
        self.bubble_text = self.canvas.create_text(0, 0, text="", fill="#111111",
                                                   font=("Segoe UI", 11), width=326,
                                                   anchor="nw", state="hidden")

    def _work_area(self, character: DesktopCharacter | None = None) -> tuple[float, float, float, float]:
        motion = character.motion if character is not None else self.motion
        monitor = nearest_monitor(self.monitors, motion.x + self.origin_x, motion.y + self.origin_y)
        left, top, right, bottom = monitor.work_rect
        return left - self.origin_x, top - self.origin_y, right - self.origin_x, bottom - self.origin_y

    def _update_gaze(self) -> None:
        try:
            x, y = cursor_position()
            self._gaze = (x - self.origin_x, y - self.origin_y)
        except OSError:
            self._gaze = None

    def _react_to_impacts(self, now: float, character: DesktopCharacter | None = None) -> None:
        character = character or self.active_character
        impacts = character.motion.drain_impacts()
        for impact in impacts:
            self.particles.burst(impact.x, impact.y - 3, color=character.color,
                                 count=min(18, max(3, int(impact.speed / 140))))
        if character is not self.active_character:
            return
        hard = [impact for impact in impacts if impact.count >= 2 and impact.speed >= 350]
        if not hard:
            return
        count = max(impact.count for impact in hard)
        level = 2 if count >= 4 else 1
        if level > character.hurt_level and now >= character.hurt_cooldown:
            character.hurt_level = level
            character.hurt_cooldown = now + 1.5
            text = "Ai! Essa parede é dura!" if level == 1 else "Ai, ai… já chega de quicar!"
            self.say(text, 3)

    def _render_character(self, character: DesktopCharacter, now: float, dt: float) -> None:
        motion = character.motion
        frame = character.animation.update(motion.mode, now, dt, pose=character.pose,
                                           pose_until=character.pose_until)
        character.renderer.render(motion.x, motion.y, motion.direction, frame.mode, now, motion.vy,
                                  gaze=self._gaze, dt=dt, vx=motion.vx, state_elapsed=frame.elapsed)

    @staticmethod
    def _render_duelist(renderer, pose: FighterPose, target: FighterPose, now: float, dt: float) -> None:
        mode = pose.mode
        if isinstance(renderer, SpriteRenderer):
            mode = {"windup": "fight", "throw": "fight", "recoil": "fall",
                    "recover": "idle"}.get(mode, mode)
        renderer.render(pose.x, pose.y, pose.direction, mode, now,
                        gaze=(target.x, target.y - 75), dt=dt, state_elapsed=pose.elapsed)

    def _render(self, dt: float = 0) -> None:
        now = time.monotonic()
        duel = self._duel_frame
        for character in self.characters.values():
            if duel is not None and character is self.active_character:
                self._render_duelist(character.renderer, duel.player, duel.opponent, now, dt)
            else:
                self._render_character(character, now, dt)
        self.anomaly.set_visible(duel is not None)
        if duel is not None:
            self._render_duelist(self.anomaly, duel.opponent, duel.player, now, dt)
        if now < self.bubble_until:
            left, top, right, bottom = self._work_area()
            width = min(350, right - left - 24)
            x, y = (duel.player.x, duel.player.y) if duel is not None else (self.x, self.y)
            bx = max(left + 12, min(right - width - 12, x + 30))
            by = max(top + 12, y - 200)
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
        if self._closing:
            return
        self._refresh_desktop()
        self._refresh_windows()
        self._loop_jobs["windows"] = self.root.after(250, self._capture_external_window)

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
        if self.hidden:
            self.restore_overlay()
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

    def _update_tray(self) -> None:
        if self.tray is not None:
            self.tray.set_state(hidden=self.hidden, click_through=self.click_through)

    def hide_overlay(self) -> None:
        if self.hidden or self._closing:
            return
        if self.tray is None or not self.tray.available:
            self.say("A bandeja está indisponível; vou permanecer visível para você me encontrar.", 5)
            return
        self._take_control()
        for character in self.characters.values():
            character.behavior = "manual"
            character.pose = None
            character.motion.stop()
        if self.command_panel is not None:
            self._close_panel(self.command_panel)
        self._close_window_list()
        self.hidden = True
        self.root.withdraw()
        self._update_tray()

    def restore_overlay(self) -> None:
        if self._closing:
            return
        self.hidden = False
        self.root.deiconify()
        self.root.update_idletasks()
        position_overlay(int(self.root.winfo_id()), virtual_bounds(self.monitors))
        self.click_through = False
        set_click_through(top_level_window(int(self.root.winfo_id())), False)
        self._place_control()
        self.root.lift()
        # Recover a character left outside the work areas by a display change.
        for character in self.characters.values():
            motion = character.motion
            gx, gy = motion.x + self.origin_x, motion.y + self.origin_y
            visible = any(m.work_rect[0] + 28 <= gx <= m.work_rect[2] - 28
                          and m.work_rect[1] + 100 <= gy <= m.work_rect[3] for m in self.monitors)
            if not visible:
                primary = next((m for m in self.monitors if m.primary), self.monitors[0])
                left, _top, right, bottom = primary.work_rect
                occupied = [other.motion.x for other in self.characters.values() if other is not character]
                x = spawn_x(left - self.origin_x + 28, right - self.origin_x - 28,
                            (left + right) / 2 - self.origin_x, occupied)
                motion.drag_to(x, bottom - self.origin_y - self.ground_offset - FOOT_CLEARANCE)
                motion.release()
                motion.step(0.01)
        self._last_tick = time.monotonic()
        self._update_tray()
        self._update_gaze()
        self._render(0)

    def _handle_tray_event(self, event: str) -> None:
        if event == "restore":
            self.restore_overlay()
        elif event == "toggle_visible":
            self.restore_overlay() if self.hidden else self.hide_overlay()
        elif event == "commands":
            self.open_command_panel()
        elif event == "windows":
            self.show_window_list()
        elif event == "explore":
            if self.hidden:
                self.restore_overlay()
            self.explore()
        elif event == "story":
            self.start_story()
        elif event == "stop":
            self.stop()
        elif event == "toggle_click_through":
            self.toggle_click_through()
        elif event == "quit":
            self.close()

    def _poll_hotkeys(self) -> None:
        if self._closing:
            return
        for event in self.hotkeys.poll():
            if event == 1:
                self.open_command_panel()
            elif event == 2:
                self.toggle_click_through()
            elif event == 3:
                self.start_story()
        if self.tray is not None:
            for event in self.tray.poll():
                self._handle_tray_event(event)
                if self._closing:
                    return
        self._loop_jobs["input"] = self.root.after(20, self._poll_hotkeys)

    def say(self, text: str, seconds: float = 4) -> None:
        self.canvas.itemconfigure(self.bubble_text, text=text[:320] + ("…" if len(text) > 320 else ""))
        self.bubble_until = time.monotonic() + seconds

    def _take_control(self) -> None:
        self._end_drag()
        self.active_character.behavior = "manual"
        self.active_character.pose = None
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
        self.active_character.pose, self.active_character.pose_until = "wave", time.monotonic() + 2.8
        self.say("Oi! Vamos explorar esse desktop?", 3)

    def explore(self) -> None:
        self._take_control()
        self.motion.stop()
        self.active_character.behavior, self.active_character.next_decision = "explore", 0
        self.say("Vou passear pelas bordas das janelas. Diga parar quando quiser.", 5)

    def follow_mouse(self) -> None:
        self._take_control()
        self.motion.stop()
        self.active_character.behavior, self.active_character.next_decision = "follow", 0
        self.say("Vou acompanhar seu cursor. Diga parar para descansar.", 4)

    def _update_behavior(self, now: float, character: DesktopCharacter | None = None) -> None:
        character = character or self.active_character
        motion = character.motion
        if character.behavior == "manual":
            return
        if character is self.active_character and (self.command_open or self._drag_anchor is not None):
            return
        if now < character.next_decision:
            return
        if character.behavior == "follow":
            character.next_decision = now + 0.1
            try:
                x, _y = cursor_position()
            except OSError:
                return
            if abs(x - self.origin_x - motion.x) > 55:
                motion.walk_to(x - self.origin_x)
            else:
                motion.stop()
            return
        character.next_decision = now + random.uniform(3, 5)
        if not motion.grounded:
            character.next_decision = now + 0.5
            return
        options = [surface for surface in self._playground(character)
                   if surface.kind == "window" and surface.key != motion.support_key]
        if options and random.random() < 0.6:
            motion.leap_to(random.choice(options).key)
        elif motion.support is not None:
            support = motion.support
            if support.kind == "window" and random.random() < 0.2:
                motion.drop()
            else:
                motion.walk_to(random.uniform(support.left + 28, support.right - 28))
                if random.random() < 0.25:
                    motion.jump()

    def _playground(self, character: DesktopCharacter | None = None):
        motion = character.motion if character is not None else self.motion
        return desktop_surfaces(self.monitors, self.visible_windows,
                                (self.origin_x, self.origin_y), self.ground_offset,
                                motion.support_key, motion.x)

    def _tag_character(self, character: DesktopCharacter) -> None:
        self.canvas.addtag_withtag("desktop_character", character.tag)

    def _actor_event(self, event, handler):
        for tag in self.canvas.gettags("current"):
            if tag.startswith("actor:"):
                if self.select_character(tag.removeprefix("actor:"), announce=False):
                    return handler(event)
                break
        return None

    def _make_renderer(self, character_id: str, color: str, appearance: str):
        tag = f"actor:{character_id}"
        if appearance == "circuito":
            if self._sprite_pack is None:
                self._sprite_pack = SpritePack.load(self.root)
            return SpriteRenderer(self.canvas, self._sprite_pack, tag=tag)
        return CharacterRenderer(self.canvas, color, tag=tag)

    def add_character(self) -> None:
        spec = next((item for item in COMPANIONS if item.id not in self.characters), None)
        if spec is None:
            self.say("Todos os quatro personagens já estão no desktop.", 4)
            return
        left, top, right, bottom = self._work_area()
        occupied = [item.motion.x for item in self.characters.values()
                    if top <= item.motion.y <= bottom]
        x = spawn_x(left + 28, right - 28, self.x, occupied)
        y = max(top + 104, bottom - self.ground_offset - FOOT_CLEARANCE)
        motion = Motion(self.sw, self.sh, x, y)
        appearance = spec.appearance
        try:
            renderer = self._make_renderer(spec.id, spec.color, appearance)
        except ValueError:
            appearance = "strokes"
            renderer = self._make_renderer(spec.id, spec.color, appearance)
        character = DesktopCharacter(spec.id, spec.name, spec.color, motion, renderer, appearance)
        self.characters[character.id] = character
        self._tag_character(character)
        self._sync_surfaces()
        self.select_character(character.id, announce=False)
        self.say(f"{character.name} entrou no desktop.", 4)

    def select_character(self, query: str, announce: bool = True) -> bool:
        character = find_character(self.characters, query)
        if character is None:
            self.say("Personagem não encontrado. Use personagens para ver o elenco.", 5)
            return False
        if character is self.active_character:
            return True
        self._end_drag()
        if self.story_running or self._scene_jobs or self._duel is not None:
            self.active_character.pose = None
            self.motion.stop()
            self._cancel_story()
        self.active_character = character
        self.bubble_until = 0
        self._update_character_picker()
        if announce:
            self.say(f"{character.name} está selecionado.", 3)
        return True

    def remove_character(self) -> None:
        character = self.active_character
        if character.id == "pixel":
            self.say("Selecione um companheiro para removê-lo.", 4)
            return
        self.select_character("pixel", announce=False)
        del self.characters[character.id]
        character.renderer.close()
        self._update_character_picker()
        self.say(f"{character.name} saiu do desktop.", 4)

    def set_appearance(self, name: str) -> None:
        appearance = {"tracos": "strokes", "circuito": "circuito"}.get(name)
        if appearance is None:
            self.say("Escolha aparência traços ou aparência circuito.", 4)
            return
        character = self.active_character
        if character.appearance == appearance:
            return
        try:
            renderer = self._make_renderer(character.id, character.color, appearance)
        except ValueError:
            self._update_character_picker()
            self.say("O pacote Circuito não pôde ser carregado.", 5)
            return
        character.renderer.close()
        character.renderer, character.appearance = renderer, appearance
        self._tag_character(character)
        self._update_character_picker()
        self._render_character(character, time.monotonic(), 0)

    def _update_character_picker(self) -> None:
        if self.character_picker is None:
            return
        characters = list(self.characters.values())
        self.character_picker.configure(values=[character.name for character in characters])
        self.character_picker.current(characters.index(self.active_character))
        self.appearance_picker.current(1 if self.active_character.appearance == "circuito" else 0)
        self.character_prompt.set(f"Diga a {self.active_character.name} o que fazer")
        self.add_character_button.configure(state="normal" if len(characters) < 1 + len(COMPANIONS) else "disabled")
        self.remove_character_button.configure(state="normal" if self.active_character.id != "pixel" else "disabled")

    def _select_character_from_panel(self, _event=None) -> None:
        index = self.character_picker.current()
        if 0 <= index < len(self.characters):
            self.select_character(list(self.characters)[index], announce=False)

    def _select_appearance_from_panel(self, _event=None) -> None:
        index = self.appearance_picker.current()
        if index in (0, 1):
            self.set_appearance(("tracos", "circuito")[index])

    def _begin_drag(self, event) -> None:
        if self.click_through:
            return
        self._take_control()
        self.motion.stop()
        self._drag_anchor = (self.x - (event.x_root - self.origin_x),
                             self.y - (event.y_root - self.origin_y), event.x_root, event.y_root)
        self._drag_sample = (time.monotonic(), self.x, self.y)
        self._drag_velocity = (0.0, 0.0)
        self._pointer_velocity = PointerVelocity()
        self._pointer_velocity.record(self._drag_sample[0], event.x_root, event.y_root)
        self.active_character.hurt_level = 0
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
                min(bottom - self.origin_y - self.ground_offset - FOOT_CLEARANCE, y))
        now = time.monotonic()
        self._pointer_velocity.record(now, event.x_root, event.y_root)
        self._drag_velocity = self._pointer_velocity.velocity(now)
        self._drag_sample = (now, x, y)
        self._dragging = True
        self.motion.drag_to(x, y)

    def _end_drag(self, _event=None) -> None:
        if self._drag_anchor is None:
            return
        if self._dragging:
            now = time.monotonic()
            if _event is not None:
                self._pointer_velocity.record(now, _event.x_root, _event.y_root)
            velocity = self._pointer_velocity.velocity(now)
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
        menu.add_command(label=self.active_character.name, state="disabled")
        menu.add_separator()
        for label, command in [
            ("Pular", self.jump), ("Subir na janela", self.climb_window),
            ("Descer", self.descend), ("Explorar", self.explore),
            ("Seguir mouse", self.follow_mouse), ("Acenar", self.wave),
            ("Parar", self.stop), ("História", self.start_story),
            ("Comandos (F2)", self.open_command_panel),
            ("Liberar cliques (F3)", self.toggle_click_through),
            ("Ocultar na bandeja", self.hide_overlay), ("Sair", self.close),
        ]:
            menu.add_command(label=label, command=command)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
            menu.destroy()

    def toggle_click_through(self) -> None:
        if self.hidden:
            self.restore_overlay()
            return
        self._end_drag()
        self.click_through = not self.click_through
        set_click_through(top_level_window(int(self.root.winfo_id())), self.click_through)
        if self.click_through:
            self.control.place_forget()
        else:
            self._place_control()
            self.root.lift()
            self.say("Modo interativo restaurado.", 3)
        self._update_tray()

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
        generation = self._story_generation
        def run() -> None:
            if token not in jobs:
                return
            jobs.discard(token)
            if generation == self._story_generation and (not story or self.story_running):
                callback()
        token = self.root.after(delay, run)
        jobs.add(token)

    def _cancel_story(self) -> None:
        self._story_generation += 1
        self.story_running = False
        for jobs in (self._story_jobs, self._scene_jobs):
            for token in tuple(jobs):
                self.root.after_cancel(token)
            jobs.clear()
        for item in self._scene_items:
            self.canvas.delete(item)
        self._scene_items.clear()
        self._end_duel()
        self.particles.clear()

    def portal(self, manual: bool = True, duration: float = 6) -> None:
        if manual:
            self._take_control()
        self.active_character.pose = None
        if self._duel is not None:
            self._end_duel()
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
        self._schedule_scene(round(duration * 1000), cleanup)

    def reload_scenes(self, notify: bool = True) -> None:
        if notify:
            self._take_control()
            self.motion.stop()
        catalog = load_scenes(BUILTIN_SCENES_DIR)
        self.scenes, self.scene_errors = catalog.scenes, catalog.errors
        ids = {scene.id for scene in self.scenes}
        if self.selected_scene_id not in ids:
            self.selected_scene_id = ("anomalia" if "anomalia" in ids else
                                      self.scenes[0].id if self.scenes else "")
        self._update_scene_picker()
        if notify:
            message = f"{len(self.scenes)} cena(s) disponível(is)."
            if self.scene_errors:
                message += " Alguns arquivos precisam de correção; veja o painel de cenas."
            self.say(message, 5)

    def _update_scene_picker(self) -> None:
        if self.scene_picker is None:
            return
        self.scene_picker.configure(values=[scene.name for scene in self.scenes],
                                    state="readonly" if self.scenes else "disabled")
        if self.scenes:
            selected = next((i for i, scene in enumerate(self.scenes)
                             if scene.id == self.selected_scene_id), 0)
            self.scene_picker.current(selected)
        else:
            self.scene_picker.set("Nenhuma cena válida")
        if self.scene_play_button is not None:
            self.scene_play_button.configure(state="normal" if self.scenes else "disabled")
        if self.scene_status is not None:
            status = f"{len(self.scenes)} cena(s). Edite os arquivos JSON e clique Recarregar."
            if self.scene_errors:
                status = f"{len(self.scene_errors)} arquivo(s) ignorado(s): {self.scene_errors[0]}"
            self.scene_status.set(status)

    def _select_scene(self, _event=None) -> None:
        if self.scene_picker is not None:
            index = self.scene_picker.current()
            if 0 <= index < len(self.scenes):
                self.selected_scene_id = self.scenes[index].id

    def start_story(self, scene_id: str | None = None) -> None:
        if self.hidden:
            self.restore_overlay()
        chosen = scene_id or self.selected_scene_id
        scene = next((item for item in self.scenes if item.id == chosen), None)
        if scene is None and chosen == "echo_duel":
            scene = next((item for item in self.scenes if item.id == "anomalia"), None)
        if scene is None:
            self.say("Cena não encontrada. Abra cenas para selecionar ou recarregar os arquivos JSON.", 6)
            return
        if self.story_running and scene_id is None:
            return
        self._take_control()
        self.motion.stop()
        self.selected_scene_id = scene.id
        self.story_running = True
        self.say(f"Cena: {scene.name}", 2)
        for step in scene.steps:
            self._schedule_scene(round(step.at * 1000),
                                 lambda item=step: self._run_scene_step(item), story=True)
        self._schedule_scene(round(scene.duration * 1000), self._finish_story, story=True)

    def _run_scene_step(self, step: SceneStep) -> None:
        if self._duel is not None and step.action not in {"say", "fight"}:
            self._end_duel()
        if step.action == "say":
            self.say(step.args["text"], 4)
        elif step.action == "walk":
            left, _top, right, _bottom = self._work_area()
            self.motion.walk_to(left + 28 + (right - left - 56) * step.args["fraction"])
        elif step.action == "jump":
            self.motion.jump()
        elif step.action == "wave":
            self.motion.stop()
            self._scene_pose("wave", step.args["duration"])
        elif step.action == "climb":
            self._refresh_windows()
            options = [surface for surface in self._playground() if surface.kind == "window"]
            key = f"window:{self.last_external_window.hwnd}" if self.last_external_window else ""
            target = next((item for item in options if item.key == key), options[0] if options else None)
            if target is not None:
                self.motion.leap_to(target.key)
        elif step.action == "fight":
            self._fight(step.args["duration"], fragments=step.args.get("fragments"))
        elif step.action == "portal":
            self.portal(manual=False, duration=step.args["duration"])

    def _scene_pose(self, pose: str, duration: float) -> None:
        end = time.monotonic() + duration
        self.active_character.pose, self.active_character.pose_until = pose, end
        def finish() -> None:
            if self.active_character.pose == pose and self.active_character.pose_until == end:
                self.active_character.pose = None
        self._schedule_scene(round(duration * 1000), finish, story=self.story_running)

    def _browser_tab(self) -> tuple[str, tuple[float, float] | None]:
        windows = self.visible_windows
        if self.last_external_window is not None:
            windows = [self.last_external_window, *windows]
        for window in windows:
            parts = re.split(r"\s+[-–—]\s+", window.title)
            if parts[-1].strip().casefold() not in BROWSER_NAMES:
                continue
            left, top, right, _bottom = window.rect
            title = " — ".join(parts[:-1]).strip() or "Nova aba"
            return title[:80], (left + min(170, (right - left) / 2) - self.origin_x,
                                top + 28 - self.origin_y)
        return "Nova aba", None

    def _fight(self, duration: float = 5, fragments: int | None = None) -> None:
        self._end_duel()
        self.motion.stop()
        self.active_character.pose = None
        self.bubble_until = 0
        self._tab_title, source = self._browser_tab()
        self._duel = TabDuel(duration, self.x, self.y, self._work_area(),
                             fragments=fragments, source=source)
        self._duel_frame = self._duel.advance(0)
        self._duel_last_tick = time.monotonic()

    def _end_duel(self, keep_fragments: bool = False) -> None:
        self._duel = self._duel_frame = None
        self.anomaly.set_visible(False)
        if keep_fragments:
            self.tab_effects.render_tab(None, self._tab_title, 0)
        else:
            self.tab_effects.clear()

    def _advance_duel(self, now: float, dt: float) -> None:
        self.tab_effects.step(dt)
        if self._duel is None:
            return
        frame = self._duel.advance(max(0.0, now - self._duel_last_tick))
        self._duel_last_tick = now
        for impact in frame.impacts:
            self.tab_effects.shatter(impact, self._tab_title, floor_y=self.y)
            self.particles.burst(impact.x, impact.y, color="#ddc6a6",
                                 count=min(18, 5 + impact.fragments // 2))
        if frame.finished:
            self._end_duel(keep_fragments=True)
        else:
            self._duel_frame = frame
            self.tab_effects.render_tab(frame.tab, self._tab_title, now)

    def _finish_story(self) -> None:
        self._cancel_story()
        self.active_character.pose = None
        self.motion.stop()
        self.say("Cena concluída. Até a próxima aventura!", 4)

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
        elif parsed.action == "scene": self.start_story(parsed.argument)
        elif parsed.action == "scenes": self.open_command_panel(focus_scene=True)
        elif parsed.action == "characters": self.open_command_panel(focus_character=True)
        elif parsed.action == "add_character": self.add_character()
        elif parsed.action == "select_character": self.select_character(parsed.argument)
        elif parsed.action == "remove_character": self.remove_character()
        elif parsed.action == "appearance": self.set_appearance(parsed.argument)
        elif parsed.action == "reload_scenes": self.reload_scenes()
        elif parsed.action == "hide": self.hide_overlay()
        elif parsed.action == "restore": self.restore_overlay()
        elif parsed.action == "portal": self.portal()
        elif parsed.action == "help":
            self.say("personagens | adicionar personagem | selecionar Faísca | aparência circuito | cenas | explorar | parar | listar janelas", 10)
        elif parsed.action != "empty":
            self.say("Comando desconhecido. Digite ajuda.", 4)

    def open_command_panel(self, focus_scene: bool = False, *, focus_character: bool = False) -> None:
        if self.hidden:
            self.restore_overlay()
        self._end_drag()
        if self.command_open:
            if self.command_panel is not None:
                self.command_panel.lift()
            if focus_character and self.character_picker is not None:
                self.character_picker.focus_force()
            elif focus_scene and self.scene_picker is not None:
                self.scene_picker.focus_force()
            return
        # Capture the external target before the panel takes keyboard focus.
        self._refresh_windows()
        self.command_open = True
        panel = tk.Toplevel(self.root)
        self.command_panel = panel
        panel.title("Comandos do Stickman")
        panel.geometry("650x540+80+80")
        panel.attributes("-topmost", True)
        panel.configure(bg="#171717")
        panel.update_idletasks()
        self.panel_hwnd = int(panel.winfo_id())
        panel.protocol("WM_DELETE_WINDOW", lambda: self._close_panel(panel))
        self.character_prompt = tk.StringVar(panel)
        tk.Label(panel, textvariable=self.character_prompt, bg="#171717", fg="white",
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
        character_frame = tk.Frame(panel, bg="#171717")
        character_frame.pack(fill="x", padx=18, pady=(16, 0))
        tk.Label(character_frame, text="Personagem e aparência", bg="#171717", fg="white",
                 font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 6))
        character_line = tk.Frame(character_frame, bg="#171717")
        character_line.pack(fill="x")
        self.character_picker = ttk.Combobox(character_line, state="readonly", width=16)
        self.character_picker.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.character_picker.bind("<<ComboboxSelected>>", self._select_character_from_panel)
        self.appearance_picker = ttk.Combobox(character_line, state="readonly", width=12,
                                              values=("Traços", "Circuito"))
        self.appearance_picker.pack(side="left", padx=(0, 8))
        self.appearance_picker.bind("<<ComboboxSelected>>", self._select_appearance_from_panel)
        self.add_character_button = tk.Button(character_line, text="Adicionar", command=self.add_character,
                                             bg="#333333", fg="white", bd=0, padx=10, pady=5)
        self.add_character_button.pack(side="left", padx=(0, 8))
        self.remove_character_button = tk.Button(character_line, text="Remover", command=self.remove_character,
                                                bg="#333333", fg="white", bd=0, padx=10, pady=5)
        self.remove_character_button.pack(side="left")
        self._update_character_picker()
        scene_frame = tk.Frame(panel, bg="#171717")
        scene_frame.pack(fill="x", padx=18, pady=(16, 0))
        tk.Label(scene_frame, text="Cena visual", bg="#171717", fg="white",
                 font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 6))
        line = tk.Frame(scene_frame, bg="#171717")
        line.pack(fill="x")
        self.scene_picker = ttk.Combobox(line, state="readonly", width=28)
        self.scene_picker.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.scene_picker.bind("<<ComboboxSelected>>", self._select_scene)
        def play_scene() -> None:
            self._select_scene()
            chosen = self.selected_scene_id
            self._close_panel(panel)
            self.start_story(chosen)
        self.scene_play_button = tk.Button(line, text="Iniciar", command=play_scene,
                                          bg="#ff7a00", fg="white", bd=0, padx=12, pady=6)
        self.scene_play_button.pack(side="left", padx=(0, 8))
        tk.Button(line, text="Recarregar", command=self.reload_scenes,
                  bg="#333333", fg="white", bd=0, padx=12, pady=6).pack(side="left")
        self.scene_status = tk.StringVar(panel)
        tk.Label(scene_frame, textvariable=self.scene_status, wraplength=600,
                 bg="#171717", fg="#bdbdbd", font=("Segoe UI", 9)).pack(anchor="w", pady=(6, 0))
        self._update_scene_picker()
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
        if focus_character:
            self.character_picker.focus_force()
        elif focus_scene:
            self.scene_picker.focus_force()

    def _close_panel(self, panel: tk.Toplevel) -> None:
        self.command_open, self.panel_hwnd = False, 0
        self.command_panel = None
        self.scene_picker = self.scene_status = self.scene_play_button = None
        self.character_picker = self.appearance_picker = self.character_prompt = None
        self.add_character_button = self.remove_character_button = None
        panel.destroy()

    def _tick(self) -> None:
        if self._closing:
            return
        now = time.monotonic()
        dt = min(0.05, max(0.0, now - self._last_tick))
        self._last_tick = now
        self.frame += 1
        if self.hidden:
            self._loop_jobs["animation"] = self.root.after(16, self._tick)
            return
        for character in self.characters.values():
            if self._duel is not None and character is self.active_character:
                continue
            motion = character.motion
            self._update_behavior(now, character)
            was_grounded = motion.grounded
            motion.step(dt)
            if not was_grounded and motion.grounded:
                self.particles.burst(motion.x, motion.y - 2, color=character.color, count=8)
            self._react_to_impacts(now, character)
        self._advance_duel(now, dt)
        self.particles.step(dt)
        self._update_gaze()
        self._render(dt)
        self._loop_jobs["animation"] = self.root.after(16, self._tick)

    def close(self) -> None:
        if self._closing:
            return
        self._closing = True
        for job in self._loop_jobs.values():
            self.root.after_cancel(job)
        self._loop_jobs.clear()
        if self.tray is not None:
            self.tray.close()
            self.tray = None
        self._end_drag()
        self._cancel_story()
        self.particles.close()
        for character in self.characters.values():
            character.renderer.close()
        self.anomaly.close()
        self.tab_effects.close()
        self._sprite_pack = None
        self.hotkeys.close()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    StickmanDesktop().run()


if __name__ == "__main__":
    main()
