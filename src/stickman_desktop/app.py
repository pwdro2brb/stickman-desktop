from __future__ import annotations

import math
import random
import sys
import time
import tkinter as tk
from pathlib import Path

from .config import load_config
from .core import parse_command
from .windows import GlobalHotkeys, foreground_window, launch, minimize_window, set_click_through

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

        self.sw = self.root.winfo_screenwidth()
        self.sh = self.root.winfo_screenheight()
        self.root.geometry(f"{self.sw}x{self.sh}+0+0")
        self.canvas = tk.Canvas(self.root, bg=TRANSPARENT, width=self.sw, height=self.sh,
                                highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)

        self.name = character.get("name", "Pixel")
        self.color = character.get("color", "#ff7a00")
        self.x = float(character.get("start_x", 120))
        self.base_y = float(self.sh - character.get("ground_offset", 72))
        self.y = self.base_y
        self.vy = 0.0
        self.target_x = self.x
        self.direction = 1
        self.frame = 0
        self.mode = "idle"
        self.story_running = False
        self.bubble_until = 0.0
        self.command_open = False
        self.click_through = False
        self.last_external_window = None
        self.panel_hwnd = 0

        self._draw_character()
        self._draw_control()
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
        return values

    def _draw_control(self) -> None:
        self.control = tk.Button(self.root, text="☰", command=self.open_command_panel,
                                 bg="#202020", fg="white", activebackground="#333333",
                                 activeforeground="white", bd=0, font=("Segoe UI", 12, "bold"))
        self.control.place(x=12, y=12, width=38, height=34)

    def _draw_character(self) -> None:
        self.parts = {
            "head": self.canvas.create_oval(0, 0, 1, 1, outline=self.color, width=5),
            "body": self.canvas.create_line(0, 0, 1, 1, fill=self.color, width=6, capstyle="round"),
            "arm1": self.canvas.create_line(0, 0, 1, 1, fill=self.color, width=5, capstyle="round"),
            "arm2": self.canvas.create_line(0, 0, 1, 1, fill=self.color, width=5, capstyle="round"),
            "leg1": self.canvas.create_line(0, 0, 1, 1, fill=self.color, width=5, capstyle="round"),
            "leg2": self.canvas.create_line(0, 0, 1, 1, fill=self.color, width=5, capstyle="round"),
        }
        self.bubble = self.canvas.create_rectangle(0, 0, 0, 0, fill="white", outline="#333333",
                                                   width=2, state="hidden")
        self.bubble_text = self.canvas.create_text(0, 0, text="", fill="#111111",
                                                   font=("Segoe UI", 11), width=330,
                                                   anchor="nw", state="hidden")

    def _render(self) -> None:
        x, y = self.x, self.y
        bob = math.sin(self.frame * 0.35) * 2 if self.mode == "walk" else 0
        swing = math.sin(self.frame * (0.9 if self.mode == "fight" else 0.45))
        swing *= 22 if self.mode == "fight" else 12 if self.mode == "walk" else 0
        neck_y, hip_y, radius = y - 55 + bob, y - 20 + bob, 16
        c = self.canvas.coords
        c(self.parts["head"], x-radius, neck_y-35, x+radius, neck_y-3)
        c(self.parts["body"], x, neck_y-2, x, hip_y)
        c(self.parts["arm1"], x, neck_y+7, x+26*self.direction, neck_y+22+swing)
        c(self.parts["arm2"], x, neck_y+7, x-23*self.direction, neck_y+22-swing)
        c(self.parts["leg1"], x, hip_y, x+18*self.direction, y+swing*0.28)
        c(self.parts["leg2"], x, hip_y, x-18*self.direction, y-swing*0.28)
        if time.time() < self.bubble_until:
            bx, by = min(max(10, x+30), self.sw-370), max(20, neck_y-125)
            c(self.bubble, bx, by, bx+350, by+82)
            c(self.bubble_text, bx+12, by+10)
            self.canvas.itemconfigure(self.bubble, state="normal")
            self.canvas.itemconfigure(self.bubble_text, state="normal")
        else:
            self.canvas.itemconfigure(self.bubble, state="hidden")
            self.canvas.itemconfigure(self.bubble_text, state="hidden")

    def _capture_external_window(self) -> None:
        candidate = foreground_window(self.own_hwnds)
        if candidate:
            self.last_external_window = candidate
        self.root.after(250, self._capture_external_window)

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
        self.canvas.itemconfigure(self.bubble_text, text=text)
        self.bubble_until = time.time() + seconds

    def walk_to(self, x: float) -> None:
        self.target_x = max(40, min(self.sw-40, float(x)))
        self.direction = 1 if self.target_x >= self.x else -1
        self.mode = "walk"

    def jump(self) -> None:
        if abs(self.y-self.base_y) < 1:
            self.vy, self.mode = -15.5, "jump"

    def toggle_click_through(self) -> None:
        self.click_through = not self.click_through
        set_click_through(int(self.root.winfo_id()), self.click_through)
        if self.click_through:
            self.control.place_forget()
        else:
            self.control.place(x=12, y=12, width=38, height=34)
            self.root.lift()
            self.say("Modo interativo restaurado.", 3)

    def inspect(self) -> None:
        info = self.last_external_window or foreground_window(self.own_hwnds)
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

    def portal(self) -> None:
        ids = []
        ids.append(self.canvas.create_oval(self.sw-280, 120, self.sw-80, 520,
                                           outline="#00d7ff", width=8))
        for i in range(4):
            ids.append(self.canvas.create_oval(self.sw-270+i*8, 130+i*10,
                                               self.sw-90-i*8, 510-i*10,
                                               outline="#6d34ff", width=2))
        self.walk_to(self.sw-175)
        self.say("Portal visual aberto. A transição é teatral e segura.", 5)
        self.root.after(6500, lambda: [self.canvas.delete(item) for item in ids])

    def start_story(self) -> None:
        if self.story_running:
            return
        self.story_running = True
        self.say("Alerta: um eco digital apareceu no lado direito.", 4)
        self.root.after(3500, lambda: self.walk_to(self.sw*0.68))
        self.root.after(7000, self._fight)
        self.root.after(12000, self.portal)
        self.root.after(19000, self._finish_story)

    def _fight(self) -> None:
        self.mode = "fight"
        self.say("Combate visual. Nenhum arquivo será alterado.", 5)
        effects = []
        for _ in range(8):
            effects.append(self.canvas.create_line(self.x, self.y-45,
                                                   self.x+random.randint(45,130),
                                                   self.y-random.randint(25,100),
                                                   fill="#ffe600", width=3))
        self.root.after(4400, lambda: [self.canvas.delete(item) for item in effects])

    def _finish_story(self) -> None:
        self.mode, self.story_running = "idle", False
        self.say("História concluída. O ambiente real permaneceu intacto.", 5)

    def execute(self, text: str) -> None:
        parsed = parse_command(text)
        if parsed.action == "walk":
            try:
                self.walk_to(float(parsed.argument))
            except ValueError:
                self.say("Use um número, por exemplo: andar 500", 4)
        elif parsed.action == "jump": self.jump()
        elif parsed.action == "inspect": self.inspect()
        elif parsed.action == "minimize": self.minimize_external()
        elif parsed.action == "open": self.open_allowed_app(parsed.argument)
        elif parsed.action == "story": self.start_story()
        elif parsed.action == "portal": self.portal()
        elif parsed.action == "help":
            self.say("andar 500 | pular | olhar tela | minimizar janela | abrir calculadora | história | portal", 8)
        elif parsed.action != "empty":
            self.say("Comando desconhecido. Digite ajuda.", 4)

    def open_command_panel(self) -> None:
        if self.command_open:
            return
        # Capture the external target before the panel takes keyboard focus.
        candidate = foreground_window(self.own_hwnds)
        if candidate:
            self.last_external_window = candidate
        self.command_open = True
        panel = tk.Toplevel(self.root)
        panel.title("Comandos do Stickman")
        panel.geometry("540x300+80+80")
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
        tk.Label(panel, text="Ex.: olhar tela | abrir calculadora | minimizar janela | história",
                 bg="#171717", fg="#71c7ff", font=("Segoe UI", 10)).pack(anchor="w", padx=18)
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
        self.frame += 1
        if self.mode == "walk":
            delta = self.target_x-self.x
            if abs(delta) < 4:
                self.x, self.mode = self.target_x, "idle"
            else:
                self.x += max(-7, min(7, delta))
        if self.y < self.base_y or self.vy < 0:
            self.vy += 0.8
            self.y += self.vy
            if self.y >= self.base_y:
                self.y, self.vy, self.mode = self.base_y, 0, "idle"
        self._render()
        self.root.after(16, self._tick)

    def close(self) -> None:
        self.hotkeys.close()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    StickmanDesktop().run()


if __name__ == "__main__":
    main()
