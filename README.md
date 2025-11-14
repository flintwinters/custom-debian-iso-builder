# Zebian: Custom Debian ISO Creator

A Python-based CLI tool for building customized Debian netinstall ISOs with a focus on automation and minimal user intervention during installation.

This tool automates the process of modifying a standard Debian ISO to include a preseed file for unattended installation, a JSON-configured post-installation script, and an optimized bootloader for a fast, hands-free setup.

## Features

- **Automated Preseeding**: Uses a `preseed.cfg` file to automate the entire Debian installation process.
- **JSON-Configured Post-Installation**: Dynamically generates a post-install script from a `post_install_config.json` file to set up a development environment.
- **Optimized Bootloader**: Modifies the ISOLINUX and GRUB bootloaders to default to the unattended installation with a minimal timeout.
- **CLI Interface**: Built with `Typer` and `Rich` for a modern and user-friendly command-line experience.
- **USB Flashing**: Automatically detects connected USB drives and offers to flash the generated ISO, with streamlined confirmation for single-drive setups.
- **Safe & Conservative**: Designed to be cautious, especially when detecting and flashing to USB drives.

## Prerequisites

- **Operating System**: A Debian-based Linux distribution.
- **Python**: Version 3.8 or higher.
- **Required Libraries**: `typer` and `rich`. Install them with:
  ```bash
  pip install typer rich
  ```
- **System Utilities**: The `xorriso` package is required for rebuilding the ISO.
  ```bash
  sudo apt-get update && sudo apt-get install -y xorriso
  ```
- **Source ISO**: A Debian netinstall ISO file named `debian-13.0.0-amd64-netinst.iso` must be present in the project's root directory.

## Configuration

Customization is managed through two primary files:

1.  **`preseed.cfg`**: This file controls the Debian installer. You can modify it to change localization, partitioning schemes, default packages, and more. By default, it is configured for a minimal, non-interactive installation.

2.  **`post_install_config.json`**: This file defines the post-installation setup.
    -   `packages`: A list of APT packages to be installed after the base system is set up.
    -   `ssh_key`: An object specifying the `type` (e.g., `ed25519`) and `user` for SSH key generation.

## Usage

To create the custom ISO, simply run the script from the project's root directory:

```bash
sudo python3 debian_iso_customizer.py
```

The script will perform all the necessary steps and output the new ISO file as `custom-debian-13.iso`. If a USB drive is connected, it will prompt you to flash the ISO to the drive.

## License

This project is licensed under the MIT License.
