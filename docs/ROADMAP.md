# Roadmap

## 0.2 - GitHub-ready MVP

- [x] Package layout
- [x] Global hotkeys
- [x] Safe external-window minimization
- [x] Allowlisted application launch
- [x] Unit tests for the parser
- [x] CI workflow
- [x] Security and contribution documentation

## 0.3 - Window awareness

- [x] Enumerate visible windows (`listar janelas`, live metadata list)
- [x] Support multiple monitors (virtual desktop and per-monitor floors)
- [x] Walk on window edges (`subir na janela`, `andar`, `descer`)
- [x] React to moved and resized windows (follow support or fall when it disappears)
- [x] Add a proper tray icon and restore menu (native Win32, hide/restore and actions)

## 0.4 - Animation system

- [x] Smooth head and eye tracking of the pointer
- [x] Walking with planted foot contacts and articulated joint solving
- [x] Velocity-based throws, damped bounces and impact reactions
- [x] Correct foot contact with the taskbar and window edges

- [ ] Replace procedural limbs with an animation state machine
- [ ] Load original sprite packs
- [x] Configurable scenes in JSON (validated visual actions, selection and live reload)
- [ ] Multiple characters
- [x] Particle pooling and effect cleanup (bounded reusable Canvas items and explicit shutdown)

## 0.5 - Accessibility perception

- [ ] Integrate Windows UI Automation
- [ ] Detect buttons, fields, menus and tabs
- [ ] Add a perception inspector
- [ ] Require confirmation before UI actions

## 0.6 - Tool framework

- [ ] Tool registry
- [ ] Risk levels
- [ ] Confirmation policies
- [ ] Action audit log
- [ ] Plugin interface

## 1.0 - Stable experiment

- [ ] Installer
- [ ] Accessibility documentation
- [ ] Comprehensive Windows tests
- [ ] Original visual identity
- [ ] Extension protocol for supported environments
