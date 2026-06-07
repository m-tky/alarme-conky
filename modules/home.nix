{ self }:
{ config, lib, pkgs, ... }:

let
  cfg = config.programs.wayland-conky;
  flakePkgs = self.packages.${pkgs.system};

  # ── Palette presets ─────────────────────────────────────────────────────────
  # Each palette is a flat attrset of color slots used by the conky template.
  # Adding a new theme: drop a palette here and extend the `variant` enum.
  palettes = {
    nightfox = {
      bg = "1e2030"; fg = "cdcecf"; muted = "71839b"; divider = "39506d";
      section = "719cd6"; counter = "63cdcf"; highlight = "dbc074";
      alert = "c94f6d"; ok = "81b29a"; accent = "9d79d6";
    };
    carbonfox = {
      bg = "161616"; fg = "f2f4f8"; muted = "7b7c7e"; divider = "393939";
      section = "78a9ff"; counter = "33b1ff"; highlight = "fff1f1";
      alert = "ee5396"; ok = "25be6a"; accent = "be95ff";
    };
    duskfox = {
      bg = "232136"; fg = "e0def4"; muted = "817c9c"; divider = "393552";
      section = "9ccfd8"; counter = "c4a7e7"; highlight = "f6c177";
      alert = "eb6f92"; ok = "a3be8c"; accent = "ea9a97";
    };
    dawnfox = {
      bg = "faf4ed"; fg = "575279"; muted = "9893a5"; divider = "dfdad9";
      section = "286983"; counter = "56949f"; highlight = "ea9d34";
      alert = "b4637a"; ok = "618774"; accent = "907aa9";
    };
    dayfox = {
      bg = "f6f2ee"; fg = "3d2b5a"; muted = "6e6a86"; divider = "e1d6c7";
      section = "2848a9"; counter = "287980"; highlight = "ac5402";
      alert = "a5222f"; ok = "396847"; accent = "5d5079";
    };
    nordfox = {
      bg = "2e3440"; fg = "cdcecf"; muted = "60728a"; divider = "3b4252";
      section = "81a1c1"; counter = "88c0d0"; highlight = "ebcb8b";
      alert = "bf616a"; ok = "a3be8c"; accent = "b48ead";
    };
    terafox = {
      bg = "152528"; fg = "e6eaea"; muted = "667379"; divider = "29464c";
      section = "5a93aa"; counter = "a1cdd8"; highlight = "e6eaea";
      alert = "e85c51"; ok = "7aa4a1"; accent = "ad5c7c";
    };
    catppuccin-mocha = {
      bg = "1e1e2e"; fg = "cdd6f4"; muted = "585b70"; divider = "313244";
      section = "cba6f7"; counter = "89dceb"; highlight = "f9e2af";
      alert = "f38ba8"; ok = "a6e3a1"; accent = "cba6f7";
    };
  };

  # User-visible color attrset = preset palette merged with explicit overrides.
  colors = (palettes.${cfg.theme.variant} or palettes.nightfox)
        // cfg.theme.colors;

  stateFile = "${config.home.homeDirectory}/.cache/wayland-conky/state.json";

  # ── Per-block shell scripts ─────────────────────────────────────────────────
  # Each block is a small bash file checked into ../src/conky/scripts/ — the
  # script source stays free of Nix quoting concerns, and we wrap it with an
  # env-prelude that injects colour hexes, the state-file path, and the jq
  # binary. The wrapper itself stays trivial so the writeShellScript indented
  # string doesn't need any escape tricks.
  mkBlock = name: pkgs.writeShellScript "wc-${name}" ''
    export STATE_FILE='${stateFile}'
    export JQ='${pkgs.jq}/bin/jq'
    export COLOR_OK='${colors.ok}'
    export COLOR_HIGHLIGHT='${colors.highlight}'
    export COLOR_ALERT='${colors.alert}'
    export COLOR_ACCENT='${colors.accent}'
    export COLOR_SECTION='${colors.section}'
    exec ${pkgs.bash}/bin/bash ${../src/conky/scripts}/${name}.sh "$@"
  '';

  ageScript       = mkBlock "age";
  todayScript     = mkBlock "today";
  doneTodayScript = mkBlock "done_today";
  inboxScript     = mkBlock "inbox";
  habitsScript    = mkBlock "habits";
  pomoScript      = mkBlock "pomo";
  calScript       = mkBlock "cal";
  notesScript     = mkBlock "notes";
  errScript       = mkBlock "err";
  counterScript   = mkBlock "counter";

  # ── conkyrc ─────────────────────────────────────────────────────────────────
  # Use `''${...}` Nix-escape for conky's own `${...}` placeholders; `${...}`
  # stays a Nix interpolation that substitutes hex colors and script paths.
  conkyConf = pkgs.writeText "wayland-conky.conf" ''
    conky.config = {
        out_to_wayland = true,
        out_to_console = false,
        out_to_x = false,
        background = false,
        update_interval = 1.0,

        alignment = '${cfg.alignment}',
        gap_x = 20,
        gap_y = 24,
        minimum_width = ${toString cfg.minWidth},
        ${lib.optionalString (cfg.maxWidth != null)
          "maximum_width = ${toString cfg.maxWidth},"}
        border_inner_margin = 12,
        border_outer_margin = 0,

        own_window = true,
        own_window_type = 'panel',
        own_window_argb_visual = true,
        own_window_argb_value = ${toString cfg.backgroundOpacity},
        own_window_colour = '${colors.bg}',
        own_window_transparent = false,
        double_buffer = true,

        use_xft = true,
        font = '${cfg.font}',
        override_utf8_locale = true,
        default_color = '${colors.fg}',
        color1 = '${colors.section}',
        color2 = '${colors.counter}',
        color3 = '${colors.highlight}',
        color4 = '${colors.alert}',
        color5 = '${colors.ok}',
        color6 = '${colors.muted}',
        color7 = '${colors.divider}',
        color8 = '${colors.accent}',
    };

    conky.text = [[
    ''${color1}TASK''${color}   ''${execpi 5 ${ageScript}}
    ''${color7}────────────────────────────''${color}

    ''${color2}''${execi 5 ${counterScript} overdue}''${color}  Overdue
    ''${color2}''${execi 5 ${counterScript} today}''${color}  Today
    ''${color2}''${execi 5 ${counterScript} this_week}''${color}  This week

    ''${color1}── Today ──────────────''${color}
    ''${execi 5 ${todayScript}}
    ''${execpi 30 ${doneTodayScript}}
    ''${execpi 30 ${inboxScript}}

    ''${color1}── Habits ─────────────''${color}
    ''${execi 30 ${habitsScript}}
    ''${execpi 1 ${pomoScript}}

    ''${color1}── Calendar ───────────''${color}
    ''${execpi 30 ${calScript}}
    ''${execpi 30 ${notesScript}}
    ''${execpi 5 ${errScript}}
    ]];
  '';

  # Configuration shared by fetcher, CLI, and setup script.
  appConfigToml = pkgs.writeText "wayland-conky-config.toml" ''
    api_base_url = "${cfg.apiBaseUrl}"
    poll_seconds = ${toString cfg.pollSeconds}
    ${lib.optionalString (cfg.firebaseWebApiKey != null)
      "firebase_web_api_key = \"${cfg.firebaseWebApiKey}\""}
  '';

in
{
  options.programs.wayland-conky = {
    enable = lib.mkEnableOption "wayland-conky widget";

    apiBaseUrl = lib.mkOption {
      type = lib.types.str;
      default = "http://localhost:8001";
      example = "http://orangepi3b:8002";
      description = ''
        Base URL of the task backend (no trailing slash). Default is
        the local dev backend; point at your deployed instance for
        prod use.
      '';
    };

    firebaseWebApiKey = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      example = "AIzaSy…";
      description = ''
        Firebase Web API key for the project the task backend
        authenticates against. Read from your Firebase project's web
        app config — public by Firebase design, but each user must
        supply their own. Written into config.toml so
        ``wayland-conky-setup`` can mint PATs.
      '';
    };

    pollSeconds = lib.mkOption {
      type = lib.types.ints.positive;
      default = 30;
      description = "How often the fetcher hits the API in the background.";
    };

    output = lib.mkOption {
      type = lib.types.str;
      default = "";
      example = "DP-1";
      description = ''
        wl_output name to pin the widget to. Empty = first available.
        Currently advisory: conky picks via xinerama_head, niri honours
        it for the first matching output.
      '';
    };

    alignment = lib.mkOption {
      type = lib.types.enum [
        "top_left" "top_right" "top_middle"
        "bottom_left" "bottom_right" "bottom_middle"
        "middle_left" "middle_right" "middle_middle"
      ];
      default = "top_right";
      description = "Where the widget anchors on the chosen output.";
    };

    minWidth = lib.mkOption {
      type = lib.types.ints.positive;
      default = 320;
      description = ''
        Lower bound on the panel width. Conky's layer-shell surface
        will never shrink below this; it grows up to ``maxWidth`` (or
        unbounded if that's null) to fit the widest visible line.
      '';
    };

    maxWidth = lib.mkOption {
      type = lib.types.nullOr lib.types.ints.positive;
      default = null;
      example = 420;
      description = ''
        Upper bound on the panel width. ``null`` (default) means the
        panel grows freely to fit content — task titles never wrap.
        Set a concrete value if you want a stable maximum and accept
        that long titles ellipsize.
      '';
    };

    font = lib.mkOption {
      type = lib.types.str;
      # Moralerspace Argon: a Japanese-aware monospace built on the
      # IBM Plex Mono + Hack lineage. Picked over plain FiraCode/JBM
      # because mixed JP/EN task titles render with correct half/full
      # widths — Japanese glyphs occupy exactly two ASCII cells, which
      # keeps the calendar columns aligned even when a title above
      # contains kanji. MUST stay monospace; a proportional fallback
      # like IBM Plex Sans JP breaks the calendar grid.
      #
      # Size 10 matches kitty (`font_size 10`) and fuzzel so the three
      # surfaces feel like one.
      default = "Moralerspace Argon:size=10";
      description = "Conky font string. MUST be monospace, or the calendar grid won't align.";
    };

    backgroundOpacity = lib.mkOption {
      type = lib.types.ints.between 0 255;
      default = 180;
      description = "ARGB alpha (0=transparent, 255=opaque). 180 ≈ 70% opacity.";
    };

    theme = {
      variant = lib.mkOption {
        type = lib.types.enum [
          "nightfox" "carbonfox" "duskfox" "dawnfox" "dayfox"
          "nordfox" "terafox" "catppuccin-mocha"
        ];
        default = "nightfox";
        description = "Built-in palette preset.";
      };
      colors = lib.mkOption {
        type = lib.types.attrsOf lib.types.str;
        default = { };
        example = { alert = "ff0000"; };
        description = ''
          Individual palette overrides. Keys: bg fg muted divider section
          counter highlight alert ok accent. Values are 6-char hex without
          a leading #.
        '';
      };
    };

    niri.installKeybinds = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = ''
        Append the Mod+Alt+ task widget keybinds to programs.niri.settings.binds.
        Set false if you wire them in by hand.
      '';
    };
  };

  config = lib.mkIf cfg.enable {
    home.packages = [
      pkgs.conky
      pkgs.fuzzel
      pkgs.jq
      pkgs.libnotify
      pkgs.wl-clipboard  # widget-cli `jump` falls back to clipboard
      flakePkgs.fetcher
      flakePkgs.widget-cli
      flakePkgs.setup
    ];

    # Static config files the daemons read.
    xdg.configFile."wayland-conky/config.toml".source = appConfigToml;
    xdg.configFile."wayland-conky/conky.conf".source = conkyConf;

    # ── systemd user services ──────────────────────────────────────────────
    systemd.user.services.wayland-conky-fetcher = {
      Unit = {
        Description = "wayland-conky background fetcher";
        After = [ "graphical-session.target" "network-online.target" ];
        PartOf = [ "graphical-session.target" ];
      };
      Service = {
        Type = "simple";
        ExecStart = "${flakePkgs.fetcher}/bin/wayland-conky-fetcher";
        Restart = "on-failure";
        RestartSec = 5;
        Environment = [
          "PATH=${pkgs.libnotify}/bin:/run/current-system/sw/bin"
        ];
      };
      Install.WantedBy = [ "graphical-session.target" ];
    };

    systemd.user.services.wayland-conky = {
      Unit = {
        Description = "wayland-conky panel (conky on layer-shell)";
        After = [ "graphical-session.target" "wayland-conky-fetcher.service" ];
        Requires = [ "wayland-conky-fetcher.service" ];
        PartOf = [ "graphical-session.target" ];
      };
      Service = {
        Type = "simple";
        ExecStart = "${pkgs.conky}/bin/conky -c ${conkyConf}";
        Restart = "on-failure";
        RestartSec = 3;
      };
      Install.WantedBy = [ "graphical-session.target" ];
    };

    # ── niri keybinds (Mod+Alt+ namespace) ────────────────────────────────
    programs.niri.settings.binds = lib.mkIf cfg.niri.installKeybinds {
      "Mod+Alt+T".action.spawn =
        [ "${flakePkgs.widget-cli}/bin/task-widget" "add" ];
      "Mod+Alt+Shift+T".action.spawn =
        [ "${flakePkgs.widget-cli}/bin/task-widget" "add" "--guided" ];
      "Mod+Alt+D".action.spawn =
        [ "${flakePkgs.widget-cli}/bin/task-widget" "done" ];
      "Mod+Alt+S".action.spawn =
        [ "${flakePkgs.widget-cli}/bin/task-widget" "snooze" ];
      "Mod+Alt+J".action.spawn =
        [ "${flakePkgs.widget-cli}/bin/task-widget" "jump" ];
      "Mod+Alt+P".action.spawn =
        [ "${flakePkgs.widget-cli}/bin/task-widget" "pomodoro" ];
      "Mod+Alt+H".action.spawn =
        [ "${flakePkgs.widget-cli}/bin/task-widget" "habit" ];
      "Mod+Alt+Space".action.spawn =
        [ "${flakePkgs.widget-cli}/bin/task-widget" "palette" ];
      "Mod+Alt+G".action.spawn =
        [ "${flakePkgs.widget-cli}/bin/task-widget" "calendar" ];
      "Mod+Alt+X".action.spawn =
        [ "${flakePkgs.widget-cli}/bin/task-widget" "delete" ];
      # Refresh: SIGUSR1 the fetcher and toast immediately so the user
      # gets visible confirmation; the actual data update lands shortly
      # after when the fetcher's next iteration writes state.json.
      "Mod+Alt+R".action.spawn =
        [ "${pkgs.writeShellScript "wc-refresh" ''
            ${pkgs.systemd}/bin/systemctl --user kill --signal=SIGUSR1 \
              wayland-conky-fetcher.service 2>/dev/null || true
            ${pkgs.libnotify}/bin/notify-send -a wayland-conky -u low \
              "Refreshing…" "Fetcher poked"
          ''}" ];
      "Mod+Alt+C".action.spawn =
        [ "${flakePkgs.widget-cli}/bin/task-widget" "toggle-conky" ];
    };
  };
}
