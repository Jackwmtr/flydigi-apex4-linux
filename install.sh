#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
set -euo pipefail

PREFIX="${XDG_DATA_HOME:-$HOME/.local/share}/flydigi-apex4"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
ENV_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/environment.d"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/flydigi-apex4"
RULE_SRC="udev/72-apex4-ds5.rules"
RULE_DST="/etc/udev/rules.d/72-apex4-ds5.rules"
SELF="$(cd "$(dirname "$0")" && pwd)"

hide_pad=0
check_only=0
uninstall=0
force=0
for arg in "$@"; do
  case "$arg" in
    --hide-pad) hide_pad=1 ;;
    --check) check_only=1 ;;
    --force) force=1 ;;
    --uninstall) uninstall=1 ;;
    -h|--help)
      cat <<EOF
usage: ./install.sh [--check] [--hide-pad] [--force] [--uninstall]

  --check      run the self-test and change nothing
  --force      install even if the self-test fails -- for setting a machine up
               before the pad is plugged in
  --hide-pad   also hide the physical pad from SDL, so Steam offers only the
               virtual DualSense and Steam Input can stay on. Implies enabling
               the autostart unit: with the pad hidden and the relay stopped
               there is no controller at all.
  --uninstall  remove everything this script installs, including the settings
               file, and put the machine back as it was
EOF
      exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

command -v python3 >/dev/null || { echo "python3 is required" >&2; exit 1; }

if [ "$check_only" = 1 ]; then
  exec python3 "$SELF/tools/selftest.py"
fi

if [ "$uninstall" = 1 ]; then
  echo "==> silencing the motors first"
  # The pad holds whatever rumble level it was last given, so removing the relay
  # while an effect is running would leave it buzzing with nothing left to stop it.
  python3 "$PREFIX/tools/rumble-off.py" 2>/dev/null \
    || python3 "$SELF/tools/rumble-off.py" 2>/dev/null \
    || echo "    (no pad on the bus, nothing to silence)"

  echo "==> stopping and removing the service"
  # Older names this project used, so an upgrade-then-uninstall leaves nothing.
  for unit in flydigi-apex4 flydigi-legacy-ds5 apex4-ds5; do
    systemctl --user disable --now "$unit" 2>/dev/null || true
    rm -f "$UNIT_DIR/$unit.service"
  done
  systemctl --user daemon-reload || true

  echo "==> removing files"
  rm -rf "$PREFIX"
  rm -f "$ENV_DIR/apex4-ds5.conf"
  rm -f "$CONFIG_DIR/config.json"
  rmdir "$CONFIG_DIR" 2>/dev/null || true

  echo "==> removing the parts that need root"
  if sudo sh -c "rm -f '$RULE_DST' /etc/modules-load.d/uhid.conf && \
                 udevadm control --reload && \
                 udevadm trigger --subsystem-match=input --subsystem-match=hidraw \
                                 --subsystem-match=misc"; then
    echo "    ok"
  else
    echo "    could not; do it by hand:" >&2
    echo "      sudo rm -f $RULE_DST /etc/modules-load.d/uhid.conf" >&2
    echo "      sudo udevadm control --reload" >&2
  fi

  echo
  echo "Done. The uhid module is left loaded -- harmless, and it will simply not"
  echo "load by itself after a reboot any more."
  if [ -f "$ENV_DIR/apex4-ds5.conf" ]; then
    echo "NOTE: could not remove $ENV_DIR/apex4-ds5.conf -- the pad stays hidden."
  else
    echo "Restart Steam so it sees the physical pad again."
  fi
  exit 0
fi

echo "==> checking this machine first"
if ! python3 "$SELF/tools/selftest.py"; then
  if [ "$force" = 0 ]; then
    echo
    echo "Self-test failed. Installing anyway would just move the failure later;"
    echo "fix the above, or run with --check to see it again. If the pad simply"
    echo "is not plugged in yet, --force installs regardless."
    exit 1
  fi
  echo
  echo "    self-test failed; continuing because --force was given"
fi

echo "==> installing to $PREFIX"
mkdir -p "$PREFIX" "$UNIT_DIR"
cp -r "$SELF/apex4ds5" "$SELF/apex4-ds5" "$SELF/tools" "$PREFIX/"

echo "==> user service"
sed "s|%PREFIX%|$PREFIX|g" "$SELF/systemd/flydigi-apex4.service" \
  > "$UNIT_DIR/flydigi-apex4.service"
systemctl --user daemon-reload

echo "==> udev rule (needs root; this is the only step that does)"
if sudo cp "$SELF/$RULE_SRC" "$RULE_DST"; then
  sudo udevadm control --reload
  # misc matters as much as the other two: /dev/uhid lives there, and on SteamOS
  # it comes up root-only, so without this the rule takes effect only at the next
  # reboot. On Fedora-derived systems the node is already open to everyone, which
  # is why this went unnoticed.
  sudo udevadm trigger --subsystem-match=input --subsystem-match=hidraw \
                       --subsystem-match=misc
else
  echo "could not install the rule; do it by hand:" >&2
  echo "  sudo cp $SELF/$RULE_SRC $RULE_DST && sudo udevadm control --reload" >&2
fi

echo "==> making sure uhid is loaded, now and at boot"
if sudo sh -c 'modprobe uhid && printf "uhid\n" > /etc/modules-load.d/uhid.conf'; then
  echo "    ok"
else
  echo "    could not; do it by hand if the self-test complains about uhid:" >&2
  echo "      sudo modprobe uhid && echo uhid | sudo tee /etc/modules-load.d/uhid.conf" >&2
fi

if [ "$hide_pad" = 1 ]; then
  echo "==> hiding the physical pad from SDL"
  mkdir -p "$ENV_DIR"
  cp "$SELF/env/apex4-ds5.conf" "$ENV_DIR/"
  echo "    Steam must be restarted to pick this up."
fi

echo "==> default settings file"
python3 "$PREFIX/apex4-ds5" --write-config || true

echo "==> enabling autostart"
systemctl --user enable --now flydigi-apex4

echo
echo "Done. Status:  systemctl --user status flydigi-apex4"
echo "Logs:          journalctl --user -u flydigi-apex4 -f"
if [ "$hide_pad" = 1 ]; then
  echo
  echo "Note: with --hide-pad, stopping the relay leaves no controller at all."
fi
