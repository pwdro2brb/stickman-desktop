# Architecture

## Modules

### `core.py`

Pure command normalization and parsing. It is platform-independent and covered by unit tests.

### `config.py`

Loads project configuration and safe defaults.

### `windows.py`

Contains the Win32 boundary:

- global hotkey registration;
- foreground window metadata;
- safe window minimization;
- click-through style management;
- allowlisted process launch.

### `app.py`

Owns the Tkinter overlay, character state, animation loop, command panel and scripted story.

## Fixed MVP issues

### Hotkeys required overlay focus

The original prototype used Tk bindings. Version 0.2 registers `F2`, `F3` and `F4` with Win32 `RegisterHotKey`, then polls `WM_HOTKEY`. The shortcuts therefore do not depend on Tk focus.

### Minimize command hid the character

The first prototype could identify the overlay as the active window. Version 0.2 tracks the last valid external foreground window, records it before opening the panel and excludes both overlay and panel window handles from minimization.

## Trust boundary

Text entered into the command panel is parsed into predefined actions. It is never passed to a command shell. Application launch uses arrays from the allowlist in `config.json` and `shell=False`.
