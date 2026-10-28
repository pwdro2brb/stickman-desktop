# Project vision

## The idea

Stickman Desktop is an experiment in embodied desktop automation. Traditional assistants live in text boxes and return text. This project gives automation a visible, animated presence that occupies the desktop, communicates intent and represents progress.

The character is not presented as conscious and does not receive unrestricted computer access. It is a visual interface over a permission-based tool system.

## Product principles

1. **Visible agency**: important actions should be represented visually.
2. **Explicit authority**: every real capability must exist as an authorized tool.
3. **Theatrical safety**: fights and destruction affect rendered effects, not user data.
4. **Progressive perception**: start with window metadata, then accessibility APIs, then optional visual perception.
5. **Original identity**: characters, stories and visual assets must be original.
6. **Local-first MVP**: useful behavior should not require a cloud account.

## Target capabilities

### Live visually over Windows

A transparent overlay renders characters above normal applications. Characters can walk, jump, speak and react to window geometry.

### Understand parts of the screen

Perception should evolve in layers:

- foreground window metadata;
- visible window enumeration;
- Windows UI Automation controls;
- optional OCR and computer vision.

### Use authorized tools

Tools are allowlisted, classified by risk and independently testable. Natural-language interpretation must never become an unrestricted shell.

### Control applications

Preferred order of integration:

1. documented APIs;
2. Windows UI Automation;
3. application-specific connectors;
4. screen automation only when necessary.

### Execute useful tasks

Characters may open tools, inspect status, launch approved workflows, monitor automation and explain errors.

### Interact with the user

Interaction may include typed commands, context menus, global hotkeys, drag-and-drop and later optional speech.

### Perform stories and fights

The story engine controls animation, dialogue, particles and simulated impacts. Real actions remain separate and require permission.

### Transition between environments

A transition can be purely visual or synchronized with a purpose-built extension or game mod. The character does not literally cross incompatible runtimes; multiple representations share state to create that experience.

## Long-term architecture

```text
Animation engine
    ├── character state
    ├── movement and physics
    ├── effects and stories
    └── overlay renderer

Perception
    ├── Win32 window metadata
    ├── UI Automation
    ├── OCR
    └── optional vision

Agent layer
    ├── command interpretation
    ├── planning
    ├── memory
    └── personality

Tool layer
    ├── Windows tools
    ├── file tools
    ├── application connectors
    └── automation integrations

Safety layer
    ├── allowlist
    ├── risk classification
    ├── confirmation
    └── audit log
```
