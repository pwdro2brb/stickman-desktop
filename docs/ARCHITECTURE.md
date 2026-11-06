# Architecture

## Modules

### `animation.py`

Renders articulated characters in **Traços** and the visual sparring echo. Poses
include breathing, walking, jumping, falling, dragging, waving and fighting.
Walking uses stance/swing foot targets and two-bone inverse kinematics, with
velocity-synchronized timing and smoothed pose changes. Head and eye tracking
uses a bounded, smoothed pointer target independently of body-facing direction.
Character parts reuse Canvas items. `Particles` pools Canvas IDs with a fixed
limit covering both active and free items. Expiration and `clear()` hide/recycle
items; reuse restores their color, width, position and visibility. `close()`
deletes every allocated item, is idempotent and prevents later allocations.
Scene cancellation clears active effects and removes portals/scheduled callbacks.

### `animation_state.py`

Chooses one animation mode per character from motion, active gestures and elapsed
time. The modes are idle, walk, jump, fall, drag, wave and fight. Airborne motion
and dragging take priority over timed gestures. Transitions and repeated gestures
start their frame clock again. The state machine provides the same mode and timing
to both renderers. **Traços** retains its travel-based gait, inverse kinematics and
live gaze.

### `characters.py`

Holds the roster definitions and per-character data. Every `DesktopCharacter` owns
its `Motion`, renderer, animation state, behavior, pose and impact state. Stable
IDs take precedence over display-name matches. Display names are normalized for
lookup and must match a single actor. Spawn placement favors space near the
selected character within the current work area.

### `sprites.py`

Loads a pack from a local `manifest.json` and PNG sheet. The original **Circuito**
pack lives in `assets/sprites/circuito/` and ships as package data. The manifest
describes the frame layout, foot anchor and timing for all seven modes. The loader
validates the sheet and frame bounds before decoding and shares Tk images across
renderers. Each sprite renderer updates one Canvas image, mirrors facing direction
and keeps the foot anchor aligned with the motion coordinates. Eye positions are
part of the artwork. **Traços** computes its gaze from the pointer.

### `scenes.py`

Loads bounded UTF-8 JSON scene files from `assets/scenes/`. The immutable catalog
contains valid scenes and per-file error messages. Validation rejects unknown
fields/actions, duplicate JSON keys and scene IDs, non-finite or Boolean numeric
values, files over 64 KiB and symbolic links. Scenes last 1–90 seconds, contain
1–64 timed steps, and are sorted stably by `at`; equal-time steps retain file order.

### `tray.py`

Owns a native Windows notification-area icon and its hidden message window.
Shell callbacks enqueue events for the app's Tk-thread polling cycle, rather than
calling application actions reentrantly from a Win32 callback. The native menu
supports restore, visibility, commands, window listing, exploration, scenes,
stopping, click-through and exit. Double-clicking restores interactive mode.
Explorer's `TaskbarCreated` message re-adds the icon after a shell restart.
Shutdown removes the icon and releases owned Win32 resources.

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

Owns the Tkinter overlay, roster selection, animation loop, command panel, tray
event routing and validated scene playback.

### `motion.py`

Platform-independent movement and support physics. `Surface` represents a window
edge or a monitor floor; `Motion` manages walking, jumps, animated leaps, falling,
dragging and landing using elapsed seconds. No movement method can change a real
application window or execute a tool.

## Tray lifecycle and hidden mode

The tray uses an original orange icon and Win32 APIs without extra dependencies.
`ocultar` cancels the scene and autonomous behaviors, clears effects, closes
auxiliary panels and withdraws the overlay. The tick loop pauses every character's
physics and rendering while hidden. Hotkey and tray polling continue. Restoring
resets the tick clock so hidden time does not become a large physics step,
recovers interactive mode and places off-screen characters back inside a usable
work area.

The tray menu and `restaurar` recover the overlay. `F2` restores and opens commands,
`F3` restores interactive mode, and `F4` restores and plays the selected scene.
If the tray failed to initialize or is unavailable, hiding is refused; startup
and the visible character continue to work. Exit releases tray resources, cancels
callbacks and closes the particle pool before destroying Tk.

## Declarative visual scenes

The packaged scenes are `echo_duel` (**Duelo com o eco**) and `boas_vindas`
(**Primeiros passos**). `pyproject.toml` includes their JSON files as package data,
so normal installations retain the default scenes. No dependency or version
change is required.

Each file has exactly `id`, `name`, `duration` and `steps`. Steps use direct
arguments, for example `{"at": 2, "action": "walk", "fraction": 0.5}`.
The allowed actions are `say`, `walk`, `jump`, `wave`, `climb`, `fight` and
`portal`. Walk fractions refer to the current work area's usable horizontal
span. Pose/portal actions have bounded duration; climb skips when no eligible
window edge is available.

The app dispatches validated steps through `_run_scene_step`; this path never
calls the command parser, `execute`, application launch or window minimization.
Scene JSON is data for visual actions, not a tool/plugin interface.

The `F2` panel contains a scene selector, **Iniciar** and **Recarregar**, with
catalog errors displayed below. Commands `cenas`, `cena <id>` and `recarregar
cenas` expose the same controls; `F4` plays the selection. A bad file does not
prevent valid scenes from loading, while ambiguous duplicate IDs are removed.
The selected character performs the scene. Starting another scene, changing
character selection, reloading, stopping or hiding cancels previous scheduled
steps and clears portals, poses, the echo and active particles.

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
monitor contributes its own floor at its usable bottom minus `ground_offset`
and the 3 px allowance for the rounded foot stroke. `ground_offset` defaults to
zero; the work area already excludes the taskbar, so subtracting the old 72 px
default again made the character float. Window contacts apply the same foot-stroke
allowance.
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

Dragging a character interrupts its current activity and places it under
pointer control. Release velocity determines the throw strength. Thrown characters
bounce against desktop boundaries with energy loss, eventually settle, and
report strong impacts to the app for short, playful reactions after repeated
collisions. Normal jumps still land without a throw bounce. Walking is 140 px/s,
with gait timing tied to travel in **Traços**. Clicking selects the character,
double-clicking makes it jump and right-clicking opens its action menu. Mouse
interaction is disabled in click-through mode. `explorar` chooses visual walks
and eligible window leaps. `seguir mouse` follows the cursor horizontally
without sending mouse input.
`parar` cancels exploration, following and scheduled story actions for the selected
character. `acenar` temporarily changes its pose. The motion behaviors use only
window metadata and pointer coordinates.

The overlay begins with the configured main character and can hold up to three
companions. The tick loop updates all motions independently, using the same
snapshot of monitors and visible windows. The `F2` panel changes the command
target and appearance. Mouse actions select their target by its Canvas tag.
Switching appearance replaces the Canvas renderer while retaining motion and
animation state. Removing a companion releases its Canvas resources. The main
character remains available.

Mixed-DPI monitor alignment depends on Windows and Tk coordinate scaling. A
restart may be needed after changing display scaling; hardware combinations
still need manual verification. Window platforms come from metadata and can
correspond to partly covered windows.

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

- With default `ground_offset: 0`, confirm the rounded feet meet the taskbar's
  upper edge rather than hovering above it. Repeat with a side taskbar if available.
- Move the pointer above, below and around a stationary character; confirm smooth,
  bounded head and eye motion without turning the whole body or starting a walk.
- Compare a slow release and a fast throw near a desktop wall. Confirm the fast
  throw rebounds harder, loses energy across collisions and eventually rests.
  Check that repeated strong bounces can produce a brief complaint.
- Watch both walking directions, starting/stopping and jumping. Feet should stay
  planted during contact and rise during the swing phase; joints should keep
  plausible lengths.

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

For character and appearance checks:

1. Open `F2`, choose **Adicionar** in **Personagem e aparência**, and confirm
   Faísca appears in **Circuito**. Add Íris and Nimbo, then verify the roster stops
   at four characters.
2. Start `explorar` with one character. Select a second character by name and run
   `seguir mouse`, then `parar`. Confirm the first keeps exploring and the second
   stops. Try selecting by ID as well.
3. Click, drag, double-click and right-click different characters. Confirm the
   clicked character becomes the command target and receives the action.
4. While a companion is moving, switch between **Traços** and **Circuito**. Check
   both facing directions and all animation modes. Confirm the feet stay aligned
   with the floor and the pointer still moves the head and eyes in **Traços**.
5. Start a scene and select another character before a delayed action plays.
   Confirm the scene cancels and the new selection receives no leftover action.
6. Remove a selected companion and confirm it disappears while the main character
   stays available. Hide and restore with several characters present and confirm
   that hiding pauses every character.

For tray, scene and pooled-effect checks:

1. Start the app and locate the orange tray icon, including the notification
   overflow if Windows places it there. Open its menu and test commands,
   window listing, exploration, stopping and click-through controls.
2. Start exploration or a scene, then run `ocultar`; confirm the character,
   panels and effects disappear and motion stays paused. Double-click the icon
   to restore; confirm mouse interaction works immediately.
3. Repeat hiding and restore separately with `F2`, `F3` and `F4`; confirm the
   first opens commands, the second restores interactive mode and the third
   starts the selected scene. A failed tray initialization must keep the overlay
   visible and refuse hiding.
4. Open `cenas`, select **Primeiros passos**, press **Iniciar**, then select
   **Duelo com o eco**. Test `cena boas_vindas` and `cena echo_duel` as well.
5. Copy a scene JSON to a new regular file in the scene directory, give it a
   unique ID and name, then press **Recarregar**. Confirm it becomes selectable
   without restarting. Edit its text/timing and reload again.
6. Add malformed JSON, an unknown action such as `open`, and a duplicate ID in
   temporary test files. Reload; confirm errors appear and unrelated valid
   scenes remain usable. Remove the test files and reload to recover the catalog.
7. Start one scene, then start the other before the first finishes. Repeat with
   `parar`, hiding and reloading; wait beyond old scheduled times and confirm
   old dialogue, portals or the echo do not return.
8. Repeat fights/throws and stop/restart scenes many times. Live particles must
   disappear after expiry/stop, and total particle Canvas IDs must stay within
   the fixed pool cap. Exiting must delete active and free pooled items and
   remove the tray icon.

## Fixed MVP issues

### Hotkeys required overlay focus

The original prototype used Tk bindings. Version 0.2 registers `F2`, `F3` and `F4` with Win32 `RegisterHotKey`, then polls `WM_HOTKEY`. The shortcuts therefore do not depend on Tk focus.

### Minimize command hid the character

The first prototype could identify the overlay as the active window. Version 0.2 tracks the last valid external foreground window, records it before opening the panel and excludes both overlay and panel window handles from minimization.

## Trust boundary

Text entered into the command panel is parsed into predefined actions. It is never passed to a command shell. Application launch uses arrays from the allowlist in `config.json` and `shell=False`.

## Animation references

The implementation uses original code informed by two procedural-animation ideas:
[Alan Zucconi's two-bone IK explanation](https://www.alanzucconi.com/2018/05/02/ik-2d-1/)
for solving joint geometry, and
[Kovar, Schreiner and Gleicher's footskate cleanup research](https://graphics.cs.wisc.edu/Papers/2002/KSG02/)
for preserving planted foot contacts. These are mathematical and animation
references; no character assets or third-party animation frames are included.
