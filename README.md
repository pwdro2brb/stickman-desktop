# Stickman Desktop

> Experimental animated desktop agent for Windows.

Stickman Desktop explores a simple idea: what if desktop automation had a visible character instead of an invisible background process?

The project renders an original stick figure over Windows, lets the character inspect parts of the desktop, execute explicitly authorized tools, interact with application windows and perform harmless visual stories. It is an early-stage proof of concept, not a general-purpose autonomous agent.

## Demo capabilities

- Transparent, always-on-top Windows overlay.
- Native Windows tray icon with restore, hide, actions and exit controls.
- Smooth articulated walking with foot contact, jumping, speech bubbles and visual effects.
- Head and eyes gently track the mouse without moving the character.
- Multiple-monitor overlay, including monitors to the left or above the primary display.
- Animated leaps onto window edges, walking on them and reacting to moving or disappearing support.
- Drag-and-release physics, waving, cursor following and visual exploration.
- Global `F2`, `F3` and `F4` hotkeys using Win32 `RegisterHotKey`.
- Detection of the last valid external foreground window.
- Live list of visible external windows, including their titles, sizes and positions.
- Safe minimization that excludes the overlay and command panel.
- Allowlist-based application launcher.
- Click-through mode, so the desktop remains usable.
- Reloadable JSON fight, greeting and portal scenes that do not modify files or applications.
- Bounded particle pooling that reuses Canvas items across effects.
- An original digital sparring echo, articulated poses and short-lived impact particles.
- Portuguese command parser with no cloud dependency.

## Safety model

The visual layer and the operational layer are deliberately separated.

- Visual fights are theatrical only.
- No file deletion or modification is implemented.
- No shell commands are accepted from the command panel.
- Applications must be explicitly listed in `config.json`.
- The overlay refuses to minimize itself.
- No microphone, camera, browser automation, PowerShell or internet connection is used.

## Requirements

- Windows 10 or Windows 11.
- Python 3.10 or newer with Tkinter.

## Quick start

Clone the repository:

```bash
git clone https://github.com/YOUR-USERNAME/stickman-desktop.git
cd stickman-desktop
```

Run without installing:

```bash
python run.py
```

Or install in editable mode:

```bash
python -m pip install -e .
stickman-desktop
```

## Controls

- `F2`: open the command panel from any focused application.
- `F3`: toggle click-through mode.
- `F4`: start the selected visual scene.
- Tray icon: double-click to restore the character in interactive mode; right-click for actions.
- Menu button: open the command panel while interactive mode is enabled.
- Drag a stroke of the character with the left mouse button, then release it to throw it.
- Faster releases produce stronger, damped bounces against desktop edges; repeated strong impacts can trigger a playful complaint.
- Double-click a stroke of the character to jump.
- Right-click the character for its action menu. These mouse controls require interactive mode (`F3`).

## Commands

```text
andar 500
andar -500,5
pular
subir na janela
descer
explorar
seguir mouse
parar
acenar
olhar tela
listar janelas
minimizar janela
abrir bloco de notas
abrir calculadora
abrir paint
abrir explorador
história
cenas
cena echo_duel
cena boas_vindas
recarregar cenas
ocultar
restaurar
portal
ajuda
```

Use `listar janelas` (also `janelas visíveis` or `ver janelas`) to open a live,
scrollable window list. It refreshes every 250 ms and excludes the Stickman's own
windows, hidden or minimized windows, windows hidden by Windows' compositor, the
desktop shell, and windows without a title or usable bounds. Covered windows can
still appear: this lists window metadata, without reading screen content or
checking whether another window covers it. Close the list with **Fechar** or `Esc`.

`andar` uses the Windows desktop's global X coordinate. Negative values reach
monitors to the left of the primary display; both `500.5` and `500,5` are accepted.
When standing on a window, the character walks within that window's top edge.

To try window interaction, select an application window, press `F2`, and enter
`subir na janela`. The character leaps onto its upper edge and follows it when
it moves. If resizing removes its support, or the window closes, hides or
minimizes, the character falls and can land on another edge or a monitor's floor.
Use `descer` to drop from a window. The edge needs at least 104 px of headroom
below the monitor's usable top and the window must be at least 80 px wide; move
a maximized or very high window down before trying to climb it.

`explorar` starts a visual walk with occasional leaps onto eligible windows.
`seguir mouse` follows the cursor horizontally without clicking applications.
`parar` stops exploration, cursor following and the current story; `acenar` plays
a greeting pose. Dragging the character gives direct control and interrupts its
current activity. These movements affect the rendered character; application
launch and minimization remain separate explicit commands.

The head and eyes follow the pointer even while the character stands still; this
is separate from the `seguir mouse` command, which makes the body walk. The gait
uses planted feet, lifted swing steps and consistent joint lengths to reduce
sliding and abrupt limb changes.

The feet rest at the usable desktop bottom, just above the taskbar. Windows
already removes the taskbar from the work area, so the default `ground_offset`
is now `0`. Positive values add an intentional gap. The rounded foot stroke is
accounted for separately at desktop floors and window edges.

## Tray and visibility

The original orange tray icon appears in Windows' notification area. Double-click
it or choose **Restaurar personagem** to recover the overlay in interactive mode.
The right-click menu also offers show/hide, **Comandos (F2)**, **Janelas visíveis**,
**Explorar**, **História**, **Parar**, click-through controls (**F3**) and **Sair**.
Windows may place the icon in the notification area's overflow menu.

Use `ocultar` to hide the character. Hiding stops exploration, following and scenes,
clears visual effects and pauses movement/rendering. The tray and global shortcuts
remain available: `F2` restores and opens commands, `F3` restores interactive mode,
and `F4` restores and starts the selected scene. Use `restaurar` or the tray menu
for a direct restore. If the tray is unavailable, hiding is refused so the
character remains reachable.

## JSON scenes

Press `F2` and choose a **Cena visual**, then **Iniciar**. **Recarregar** (or
`recarregar cenas`) reloads scene files without restarting the app. The `cenas`
command opens the selector; `cena <id>` starts a particular scene, and `F4` uses
the current selection. Two original scenes are included:

| ID | Name |
| --- | --- |
| `echo_duel` | Duelo com o eco |
| `boas_vindas` | Primeiros passos |

Edit or add regular UTF-8 JSON files in
`src/stickman_desktop/assets/scenes/`. This directory is also included when the
package is installed. Each scene has an ID, a display name, a duration in seconds
and timed steps with their action arguments directly on the step:

```json
{
  "id": "saudacao",
  "name": "Uma saudação",
  "duration": 4,
  "steps": [
    {"at": 0, "action": "say", "text": "Pronto para outra aventura?"},
    {"at": 0.2, "action": "wave", "duration": 2.8},
    {"at": 3.2, "action": "jump"}
  ]
}
```

Only visual actions are accepted:

| Action | Arguments |
| --- | --- |
| `say` | `text` (up to 240 characters) |
| `walk` | `fraction` from 0 to 1 across the current monitor's work area |
| `jump` | None |
| `wave` | Optional `duration`, 0.2–5 seconds |
| `climb` | None; uses an eligible window edge if one is available |
| `fight` | Optional `duration`, 0.2–6 seconds |
| `portal` | Optional `duration`, 1–10 seconds |

Scenes can last 1–90 seconds and contain 1–64 steps; `at` must be within that
scene's duration. IDs use lowercase letters, digits, underscores or hyphens.
Invalid files are isolated and reported below the selector; valid scenes remain
available. Duplicate IDs are rejected. Reloading, hiding, `parar`, or starting a
different scene cancels prior scene callbacks and effects. JSON scenes cannot
launch apps, minimize windows, run commands or invoke operational tools.

## Configuration

Copy `config.example.json` to `config.json`, then edit the character and allowlist:

```json
{
  "character": {
    "name": "Pixel",
    "color": "#ff7a00",
    "start_x": 120,
    "ground_offset": 0
  },
  "authorized_apps": {
    "calculadora": ["calc.exe"]
  },
  "safety": {
    "allow_window_minimize": true,
    "allow_process_launch": true
  }
}
```

Do not add untrusted scripts, shells or unknown executables to the allowlist.

## Project structure

```text
stickman-desktop/
├── .github/workflows/tests.yml
├── docs/
│   ├── ARCHITECTURE.md
│   ├── PROJECT_VISION.md
│   └── ROADMAP.md
├── src/stickman_desktop/
│   ├── animation.py
│   ├── app.py
│   ├── assets/scenes/
│   ├── config.py
│   ├── core.py
│   ├── environment.py
│   ├── gestures.py
│   ├── motion.py
│   ├── scenes.py
│   ├── tray.py
│   └── windows.py
├── tests/
├── config.example.json
├── pyproject.toml
├── run.py
├── CONTRIBUTING.md
├── SECURITY.md
├── LICENSE
└── README.md
```

## Current limitations

- Monitor layout is refreshed approximately once per second. Mixed-DPI layouts may need a restart if changing scaling affects alignment.
- Window platforms use metadata; a partly covered window can still provide a surface.
- Perception is limited to window metadata, not buttons or screen content.
- Stories are scripted rather than generated dynamically.
- The character uses procedural lines, not sprite animation.
- Windows is the only supported operating system.

## Vision

Future versions may add Windows UI Automation, multiple original characters, extensions for supported applications, and optional local AI planning. See [PROJECT_VISION.md](docs/PROJECT_VISION.md) and [ROADMAP.md](docs/ROADMAP.md).

## Originality and inspiration

This repository contains an original implementation, original character identity and original code. It does not include artwork, characters, storylines or assets from third-party animation properties. Public contributions must follow the same rule.

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening an issue or pull request.

## Security

Read [SECURITY.md](SECURITY.md). Please do not publish proof-of-concept changes that weaken the allowlist or execute arbitrary user input.

## License

MIT License. See [LICENSE](LICENSE).
