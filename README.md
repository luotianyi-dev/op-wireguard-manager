# Server Operation: Wireguard Manager

Python script to generate systemd-networkd configuration files for Wireguard.

## Usage

Ensure following things are installed:
 - python
 - poetry
 - openssh-server
 - wireguard-tools
 - systemd-networkd (enable and running)

```bash
# Install
poetry install
poetry shell

# Using
python3 wm.py            # Show the generated route table
python3 wm.py --help     # Show help
python3 wm.py --apply    # Apply the generated route table
```

## License
GPL-3.0-only
