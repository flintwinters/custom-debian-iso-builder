# Helix: Custom Debian ISO Creator

A Python-based CLI tool for building customized Debian netinstall ISOs with a focus on automation and minimal user intervention during installation.

This tool automates the process of modifying a standard Debian ISO from a single YAML configuration file. It generates the installer preseed internally, updates the bootloader, and produces a hands-free Debian install ISO.

## Features

- **YAML-Configured Installer**: Uses `helix_config.yaml` as the user-facing source of truth for ISO paths, Debian installer answers, packages, and SSH key behavior.
- **Generated Preseed**: Writes the Debian Installer preseed directly into the extracted ISO workspace; it is not edited as a standalone project file.
- **Optimized Bootloader**: Modifies the ISOLINUX and GRUB bootloaders to default to the unattended installation with a minimal timeout.
- **CLI Interface**: Built with `Typer` and `Rich` for a modern and user-friendly command-line experience.
- **USB Flashing**: Automatically detects connected USB drives and offers to flash the generated ISO, with streamlined confirmation for single-drive setups.
- **Safe & Conservative**: Designed to be cautious, especially when detecting and flashing to USB drives.

## Prerequisites

- **Operating System**: A Debian-based Linux distribution.
- **Python**: Version 3.8 or higher.
- **Required Libraries**: `typer`, `rich`, and `pyyaml`. Install them with:
  ```bash
  uv sync
  ```
- **System Utilities**: The `xorriso` package is required for rebuilding the ISO.
  ```bash
  sudo apt-get update && sudo apt-get install -y xorriso
  ```
- **Source ISO**: A Debian netinstall ISO file named `debian-13.0.0-amd64-netinst.iso` must be present in the project's root directory.

## Configuration

Customization is managed through `helix_config.yaml`:

- `iso`: Source ISO, extraction workspace, and output ISO path.
- `packages`: APT packages installed into the target system.
- `ssh_key`: SSH key type and optional target user.
- `preseed`: Debian Installer values such as locale, user, timezone, filesystem, partitioning, and base packages.

The install user's password is not stored in YAML. `create` prompts for it, then writes only a SHA-512 crypt hash into the generated installer preseed. For non-interactive runs, pass the plaintext through `--install-password`.

Installer failure diagnostics are enabled by default. If Debian Installer fails, Helix writes `/var/log/helix-installer-diagnostics.tar` in the installer environment, copies it to `/target/root/` when the target filesystem is mounted, and prints the configured syslog tail to the installer console and tty4.

## Usage

To create the custom ISO, simply run the script from the project's root directory:

```bash
uv run python helix_iso_customizer.py create
```

For automation:

```bash
uv run python helix_iso_customizer.py create --install-password 'password' --no-copy-ssh-keys --no-flash-usb
```

The script will perform all the necessary steps and output the new ISO file as `helix-debian-13.iso`. If a USB drive is connected, it will prompt you to flash the ISO to the drive.

## License

This project is licensed under the MIT License.
