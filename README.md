# Stickman Desktop

> Experimental animated desktop agent for Windows.

Stickman Desktop explores a simple idea: what if desktop automation had a visible character instead of an invisible background process?

The project renders an original stick figure over Windows, lets the character inspect parts of the desktop, execute explicitly authorized tools, interact with application windows and perform harmless visual stories. It is an early-stage proof of concept, not a general-purpose autonomous agent.

## Demo capabilities

- Transparent, always-on-top Windows overlay.
- Animated walking, jumping, speech bubbles and visual effects.
- Global `F2`, `F3` and `F4` hotkeys using Win32 `RegisterHotKey`.
- Detection of the last valid external foreground window.
- Safe minimization that excludes the overlay and command panel.
- Allowlist-based application launcher.
- Click-through mode, so the desktop remains usable.
- Scripted fight and portal scenes that do not modify files or applications.
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
- `F4`: start a short visual story.
- Menu button: open the command panel while interactive mode is enabled.

## Commands

```text
andar 500
pular
olhar tela
minimizar janela
abrir bloco de notas
abrir calculadora
abrir paint
abrir explorador
história
portal
ajuda
```

## Configuration

Copy `config.example.json` to `config.json`, then edit the character and allowlist:

```json
{
  "character": {
    "name": "Pixel",
    "color": "#ff7a00",
    "start_x": 120,
    "ground_offset": 72
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
│   ├── app.py
│   ├── config.py
│   ├── core.py
│   └── windows.py
├── tests/test_core.py
├── config.example.json
├── pyproject.toml
├── run.py
├── CONTRIBUTING.md
├── SECURITY.md
├── LICENSE
└── README.md
```

## Current limitations

- The visual overlay is optimized for a single primary monitor.
- Perception is limited to window metadata, not buttons or screen content.
- Stories are scripted rather than generated dynamically.
- The character uses procedural lines, not sprite animation.
- Windows is the only supported operating system.

## Vision

Future versions may add Windows UI Automation, window-edge physics, multiple original characters, configurable story files, extensions for supported applications, and optional local AI planning. See [PROJECT_VISION.md](docs/PROJECT_VISION.md) and [ROADMAP.md](docs/ROADMAP.md).

## Originality and inspiration

This repository contains an original implementation, original character identity and original code. It does not include artwork, characters, storylines or assets from third-party animation properties. Public contributions must follow the same rule.

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening an issue or pull request.

## Security

Read [SECURITY.md](SECURITY.md). Please do not publish proof-of-concept changes that weaken the allowlist or execute arbitrary user input.

## License

MIT License. See [LICENSE](LICENSE).
