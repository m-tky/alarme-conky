# alarme-conky

A Wayland-native desktop widget and CLI for the Alarme task app.
Designed for [niri](https://github.com/YaLTeR/niri) but runs on any
compositor that implements `wlr-layer-shell-v1` (Hyprland, Sway,
River…).

The widget is a conky panel that shows the day's tasks, inbox, done
list, habits, current Pomodoro, a clickable calendar, and an error
line. The CLI is a fuzzel-driven set of one-shot commands for adding,
completing, snoozing, deleting tasks and so on. A small Python daemon
polls the backend on a 30-second tick (or on demand via SIGUSR1) and
writes a JSON snapshot that conky reads.

Everything is packaged as a Nix flake exposing a home-manager module,
so the entire setup (binaries, config files, systemd user units, niri
keybinds) lands declaratively.

## Architecture

```
┌─────────────────┐      ┌──────────────────────┐
│ Alarme backend  │◄─────│ wayland-conky-fetcher│  ← polls every 30s,
│  (FastAPI)      │      │  (Python daemon)     │    SIGUSR1 wakes early
└─────────────────┘      └──────────┬───────────┘
                                    │ writes
                                    ▼
                         ~/.cache/wayland-conky/state.json
                                    │
                ┌───────────────────┼──────────────────┐
                ▼                                      ▼
        ┌───────────────┐                    ┌──────────────────┐
        │ conky panel   │                    │ task-widget CLI  │
        │ (layer-shell) │                    │ (fuzzel prompts) │
        └───────────────┘                    └──────────────────┘
                                                      ▲
                                                      │ Mod+Alt+T,D,X,…
                                                      │
                                                ┌─────┴────┐
                                                │   niri   │
                                                └──────────┘
```

## Requirements

- A running Alarme backend (FastAPI, see [the task app
  repo](https://github.com/m-tky/task)) reachable over HTTP — Tailscale
  is the canonical transport, but any URL the fetcher can resolve works.
- A Firebase project the backend authenticates against:
  - Web API key (public — read off your Firebase project's web app
    config).
  - A service-account JSON for minting custom tokens. **Keep this file
    out of git.** Drop it at `~/.config/wayland-conky/service-account.json`.
- A Wayland compositor with `wlr-layer-shell-v1`.
- NixOS + home-manager are first-class; everything else needs you to
  port the home-manager module by hand.

## Install (NixOS + home-manager)

Add the flake to your home-manager `flake.nix`:

```nix
inputs.alarme-conky = {
  url = "github:m-tky/alarme-conky";
  inputs.nixpkgs.follows = "nixpkgs";
};
```

Then import the module in your home config:

```nix
{ inputs, ... }:
{
  imports = [ inputs.alarme-conky.homeManagerModules.default ];

  programs.wayland-conky = {
    enable = true;
    apiBaseUrl = "https://alarme.example.com";        # your backend
    firebaseWebApiKey = "AIzaSy…";                    # your Firebase project
    theme.variant = "nightfox";                       # or carbonfox, duskfox, …
  };
}
```

`home-manager switch`, then bootstrap the PAT:

```bash
# Put your service-account JSON in place first.
ln -s /path/to/firebase-adminsdk-*.json \
      ~/.config/wayland-conky/service-account.json

wayland-conky-setup --email you@example.com
# → systemctl --user restart wayland-conky-fetcher.service
```

The setup script signs in via the Firebase Admin SDK (custom token →
ID token exchange), issues a PAT against `/auth/api-keys`, and writes
the result to `~/.config/wayland-conky/token` (chmod 600).

## Configuration

Every option lives under `programs.wayland-conky`:

| Option | Default | Notes |
|---|---|---|
| `apiBaseUrl` | `http://localhost:8001` | Backend base URL, no trailing slash |
| `firebaseWebApiKey` | `null` | Required — Firebase project Web API key |
| `pollSeconds` | `30` | Background fetch cadence |
| `output` | `""` | wl_output to pin to ("" = first available) |
| `alignment` | `top_right` | conky alignment string |
| `minWidth` | `320` | Panel width lower bound |
| `maxWidth` | `null` | `null` → grow to fit; set int for hard cap |
| `font` | `Moralerspace Argon:size=10` | Must be monospace |
| `backgroundOpacity` | `180` | ARGB alpha 0–255 |
| `theme.variant` | `nightfox` | Built-in palette preset |
| `theme.colors` | `{}` | Per-slot hex overrides |
| `niri.installKeybinds` | `true` | Wire Mod+Alt+ binds via niri-flake |

Palettes: `nightfox`, `carbonfox`, `duskfox`, `dawnfox`, `dayfox`,
`nordfox`, `terafox`, `catppuccin-mocha`.

## Keybinds

The home-manager module appends a `Mod+Alt+` namespace to niri:

| Key | Action |
|---|---|
| `Mod+Alt+T` | Add task (fuzzel — supports inline `#proj @14:00 ~tag !high *` syntax) |
| `Mod+Alt+Shift+T` | Add task (guided: title → project → date → priority → flags) |
| `Mod+Alt+D` | Mark a today/overdue task done |
| `Mod+Alt+X` | Delete a task (confirm prompt) |
| `Mod+Alt+S` | Snooze a today/overdue task |
| `Mod+Alt+J` | Jump (fuzzy pick any task → open in app / copy id) |
| `Mod+Alt+P` | Pomodoro start / stop (duration picker) |
| `Mod+Alt+H` | Toggle today's habit check |
| `Mod+Alt+M` | (optional) calendar popup — currently mapped via `G` (legacy) |
| `Mod+Alt+G` | Calendar popup (GTK4, marks busy days, inline-add) |
| `Mod+Alt+C` | Show / hide the conky panel |
| `Mod+Alt+R` | Force the fetcher to refresh now |
| `Mod+Alt+Space` | Command palette — every subcommand with live context |

## Backend dependencies

The widget assumes the Alarme backend exposes:

- `GET /api/v1/tasks?status=…&limit=…` — paginated `TaskListResponse`
- `POST /api/v1/tasks` — `TaskCreate` body
- `PATCH /api/v1/tasks/{id}` — `TaskUpdate` body with `expected_version`
- `DELETE /api/v1/tasks/{id}` — soft delete (deleted_at)
- `GET /api/v1/habits`, `GET /api/v1/habits/today`
- `PUT /api/v1/habits/{id}/logs` — `{date, count}`
- `POST /api/v1/pomodoro/start`, `PATCH /api/v1/pomodoro/{id}/complete`
- `POST /api/v1/parse-deadline`
- `GET /api/v1/projects`, `GET /api/v1/tags`, `POST /api/v1/tags`
- `POST /api/v1/auth/api-keys` (Firebase-only) — PAT issuance
- `GET /api/v1/auth/api-keys`, `DELETE /api/v1/auth/api-keys/{id}`

PAT auth dispatches on the `tsk_pat_` bearer prefix; Firebase ID
tokens travel through the existing path.

## Development

```bash
git clone https://github.com/m-tky/alarme-conky
cd alarme-conky
nix develop
# → fetcher, task-widget, wayland-conky-setup are on PATH
# → conky, fuzzel, jq, libnotify, wl-clipboard available
```

The flake's `packages` outputs are `fetcher`, `widget-cli`, and `setup`.
`nix build .#widget-cli` produces a wrapper that drops the `task-widget`
binary in `./result/bin/`.

## License

[MIT](LICENSE) © 2026 Takuya Mukai
