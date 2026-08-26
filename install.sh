#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
set -euo pipefail

PREFIX="${XDG_DATA_HOME:-$HOME/.local/share}/flydigi-apex4"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
ENV_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/environment.d"
RULE_SRC="udev/72-apex4-ds5.rules"
RULE_DST="/etc/udev/rules.d/72-apex4-ds5.rules"
SELF="$(cd "$(dirname "$0")" && pwd)"

hide_pad=0
check_only=0
uninstall=0
for arg in "$@"; do
  case "$arg" in
    --hide-pad) hide_pad=1 ;;
    --check) check_only=1 ;;
    --uninstall) uninstall=1 ;;
    -h|--help)
      cat <<EOF
usage: ./install.sh [--check] [--hide-pad] [--uninstall]

  --check      run the self-test and change nothing
  --hide-pad   also hide the physical pad from SDL, so Steam offers only the
               virtual DualSense and Steam Input can stay on. Implies enabling
               the autostart unit: with the pad hidden and the relay stopped
               there is no controller at all.
  --uninstall  remove everything this script installs
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
  systemctl --user disable --now flydigi-apex4 2>/dev/null || true
  rm -f "$UNIT_DIR/flydigi-apex4.service" "$ENV_DIR/apex4-ds5.conf"
  rm -rf "$PREFIX"
  systemctl --user daemon-reload || true
  echo "removed. The parts that need root:"
  echo "  sudo rm -f $RULE_DST /etc/modules-load.d/uhid.conf"
  echo "  sudo udevadm control --reload"
  exit 0
fi

echo "==> checking this machine first"
python3 "$SELF/tools/selftest.py" || {
  echo
  echo "Self-test failed. Installing anyway would just move the failure later;"
  echo "fix the above, or run with --check to see it again."
  exit 1
}

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
  sudo udevadm trigger --subsystem-match=input --subsystem-match=hidraw
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
