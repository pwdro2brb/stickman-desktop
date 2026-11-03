# Architecture

## Modules

### `animation.py`

Renders the original articulated character and its visual sparring echo. Poses
include breathing, walking, jumping, falling, dragging, waving and fighting.
Character parts reuse Canvas items. Impact particles have a fixed count limit
and expire automatically; scene cancellation removes portals and scheduled callbacks.

### `core.py`

Pure command normalization and parsing. It is platform-independent and covered by unit tests.

### `config.py`

Loads project configuration and safe defaults.

### `windows.py`

Contains the Win32 boundary:

- global hotkey registration;
- foreground window metadata;
- visible external window enumeration;
- monitor rectangles and work areas;
- cursor position;
- safe window minimization;
- click-through style management;
- allowlisted process launch.

### `app.py`

Owns the Tkinter overlay, character state, animation loop, command panel and scripted story.

### `motion.py`

Platform-independent movement and support physics. `Surface` represents a window
edge or a monitor floor; `Motion` manages walking, jumps, animated leaps, falling,
dragging and landing using elapsed seconds. No movement method can change a real
application window or execute a tool.

## Window awareness

`enumerate_visible_windows()` returns fresh `WindowInfo` snapshots for titled,
visible, non-minimized top-level windows with usable bounds. It skips the desktop
shell, DWM-cloaked windows and explicitly excluded handles. Foreground detection
uses the same filters. `top_level_window()` resolves Tk's native wrappers so the
overlay, command panel and window list are all excluded by their actual handles.
Win32 function signatures preserve pointer-sized window handles on 64-bit Python.

The app refreshes its window catalog every 250 ms. The previous external target
is matched by handle against the new catalog, updating its title and bounds and
discarding it when it closes, hides or minimizes. Inspection and minimization
refresh again immediately before using the target. A failed enumeration clears
the catalog and target; the next polling cycle retries automatically.

The Portuguese command `listar janelas` opens one live, scrollable metadata table.
Rows keep their handles as internal identities while titles, dimensions and
positions update. This is metadata perception only: windows covered by other
windows may still be listed. It does not capture pixels, change window focus or
move application windows as part of enumeration.

## Desktop movement and interaction

`enumerate_monitors()` provides each monitor's rectangle, usable work area and
primary flag. The overlay spans their virtual desktop bounding rectangle, whose
origin can be negative. The app translates global Windows coordinates into local
canvas coordinates; `andar` arguments remain global desktop X coordinates. Each
monitor contributes its own floor at its usable bottom minus `ground_offset`.
Topology is refreshed approximately once per second, preserving the character's
global position when the virtual origin changes. A monitor API failure preserves
the last known layout.

Visible windows provide upper-edge platforms when they have at least 104 px of
headroom below the usable monitor top and at least 80 px of width. `subir na
janela` targets the most recent valid external foreground window and animates a
leap; a maximized window with no headroom is rejected with guidance to move it
down. Grounded walking stays inside the window edge. Updated snapshots move a
supported character with its window; loss of support after resize, hiding,
minimization or closure causes a fall. `descer` drops through the current support
instead of immediately landing back on it. Landing considers the crossing of a
surface during descent, rather than requiring an exact frame position.

Dragging a character stroke interrupts its current activity and places it under
pointer control. Releasing resumes physics. Double-clicking jumps and
right-clicking opens the character's action menu. Mouse interaction is disabled
in click-through mode. `explorar` chooses visual walks and eligible window leaps;
`seguir mouse` follows the cursor horizontally without sending mouse input.
`parar` cancels exploration, following and scheduled story actions. `acenar`
temporarily changes the character's pose. These behaviors add no dependencies
and do not move, resize, click or minimize application windows.

Mixed-DPI monitor alignment depends on Windows and Tk coordinate scaling. A
restart may be needed after changing display scaling; hardware combinations
still need manual verification. Window platforms come from metadata and can
correspond to partly covered windows. Sprite animation, multiple characters and
a tray icon remain future work.

### Windows verification

Run `python -m pytest` for parser, motion physics, catalog integration and simulated Win32 tests.
For a desktop check, run `python run.py`, press `F2`, and enter `listar janelas`:

1. Open two titled application windows; confirm titles, sizes and positions.
2. Move, resize and rename one; confirm the corresponding row updates.
3. Minimize or close one; confirm its row disappears. Restore it and confirm it returns.
4. Confirm the overlay, command panel and metadata list do not appear in the list.
5. Run `listar janelas` again; confirm it reuses the same list window.
6. Focus an external window, open `F2`, and use `olhar tela` or `minimizar janela`;
   confirm the external target is used. A closed or minimized target must not be reused.
7. Close the list with `Esc` or **Fechar**, then reopen it; animation and hotkeys must continue.

For movement and interaction checks:

1. Place a normal application window at least 104 px below the usable monitor top.
   Select it, press `F2`, and run `subir na janela`; confirm an animated leap to its edge.
2. Use `andar` with a distant X value; confirm walking stops inside that edge.
   Move the application window and confirm the character follows it.
3. Shrink the supporting edge out from under the character, then repeat with
   minimizing or closing the window; confirm it falls and lands on a valid surface.
4. Run `descer` while on a window; confirm it drops instead of landing back on the same edge.
   Try climbing a maximized window and confirm the guidance about headroom.
5. Drag a character stroke, release it above a window and confirm it lands.
   Double-click to jump, right-click for the action menu, then test `acenar`.
6. Start `explorar`, then `parar`; start `seguir mouse`, move the pointer, then
   `parar`. Confirm neither mode clicks or changes application windows. Start a
   story, stop it, and wait past its scheduled ending to confirm it stays stopped.
7. With monitors left of or above the primary display, drag the character to each,
   use a negative `andar` X where appropriate, and check window-edge alignment and
   the separate floors. Rearrange monitors and confirm the layout refreshes.
8. Toggle `F3` and confirm character mouse gestures follow click-through state
   while `F2` and `F4` remain available.

## Fixed MVP issues

### Hotkeys required overlay focus

The original prototype used Tk bindings. Version 0.2 registers `F2`, `F3` and `F4` with Win32 `RegisterHotKey`, then polls `WM_HOTKEY`. The shortcuts therefore do not depend on Tk focus.

### Minimize command hid the character

The first prototype could identify the overlay as the active window. Version 0.2 tracks the last valid external foreground window, records it before opening the panel and excludes both overlay and panel window handles from minimization.

## Trust boundary

Text entered into the command panel is parsed into predefined actions. It is never passed to a command shell. Application launch uses arrays from the allowlist in `config.json` and `shell=False`.
