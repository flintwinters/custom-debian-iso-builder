#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
debian_iso_customizer.py

A comprehensive utility for automating the customization of Debian network installation ISOs.

This script orchestrates the entire lifecycle of Debian ISO modification:
1.  Verification of system prerequisites (e.g., `xorriso`).
2.  Extraction of the source ISO's contents into a temporary workspace.
3.  Generation and injection of a preseed file for unattended installations.
4.  Modification of bootloader configurations (ISOLINUX for BIOS, GRUB for UEFI)
    to include a new, automated installation entry.
5.  Re-packaging of the modified file structure into a new, bootable ISO image.

Designed for idempotency and clarity, the script abstracts low-level shell commands
into a high-level, maintainable Python workflow. It is intended for system
administrators and developers who require consistent, repeatable, and automated
Debian deployments.

MIT License. Copyright (c) 2025 [Your Name].
"""

import os
import subprocess
import shutil
import typer
import yaml
import json
from pathlib import Path
from typing import Optional
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

# --- Typer App and Rich Console Initialization ---
app = typer.Typer(
    name="debian-customizer",
    help="A CLI tool to create custom Debian ISOs with unattended installation.",
    add_completion=False,
    no_args_is_help=True
)
console = Console()

# --- Constants & Configuration ---
SOURCE_ISO_PATH = "debian-13.0.0-amd64-netinst.iso"
WORKSPACE_DIR = "iso-extract"
CUSTOM_ISO_NAME = "custom-debian-13.iso"
PRESEED_FILENAME = "preseed.cfg"
POST_INSTALL_CONFIG = "post_install_config.yaml"
SSH_KEY_STAGING_DIR = "zebian-ssh"
SSH_PRIVATE_KEY_NAME = "id_ed25519"
SSH_PUBLIC_KEY_NAME = "id_ed25519.pub"


@app.callback()
def main():
    """Create customized Debian installer ISOs."""


def status(label: str, message: str, style: str):
    """Prints a compact, consistently styled status line."""
    console.print(f"[{style}]{label}:[/{style}] {message}")


def success(message: str):
    status("SUCCESS", message, "bold green")


def warning(message: str):
    status("WARNING", message, "bold yellow")


def error(message: str):
    status("ERROR", message, "bold red")


def skipped(message: str):
    status("SKIPPED", message, "bold yellow")


def verify_prerequisites():
    """Confirms that `xorriso` is available on the system PATH."""
    if not shutil.which("xorriso"):
        error("`xorriso` is not installed or not in the system PATH.")
        console.print("Please install it using: [cyan]sudo apt-get install -y xorriso[/cyan]")
        raise typer.Exit(code=1)


def load_post_install_config():
    """Loads and validates the YAML configuration used for ISO customization."""
    if not os.path.exists(POST_INSTALL_CONFIG):
        error(f"Post-install config not found at [yellow]'{POST_INSTALL_CONFIG}'[/yellow].")
        raise typer.Exit(code=1)

    with open(POST_INSTALL_CONFIG, "r") as f:
        return yaml.safe_load(f) or {}


def make_workspace_writable():
    """Adds owner write permissions to the generated extraction workspace."""
    for root, dirs, files in os.walk(WORKSPACE_DIR, topdown=False):
        for filename in files:
            path = os.path.join(root, filename)
            if not os.path.islink(path):
                os.chmod(path, 0o600)
        for dirname in dirs:
            path = os.path.join(root, dirname)
            if not os.path.islink(path):
                os.chmod(path, 0o700)
    os.chmod(WORKSPACE_DIR, 0o700)


def remove_workspace():
    """Removes the generated ISO extraction workspace, including read-only files."""
    if not os.path.exists(WORKSPACE_DIR):
        return

    try:
        make_workspace_writable()
        shutil.rmtree(WORKSPACE_DIR)
    except PermissionError:
        stale_workspace = f"{WORKSPACE_DIR}.stale"
        suffix = 1
        while os.path.exists(stale_workspace):
            suffix += 1
            stale_workspace = f"{WORKSPACE_DIR}.stale-{suffix}"
        os.rename(WORKSPACE_DIR, stale_workspace)
        warning(f"Moved unremovable workspace to [yellow]{stale_workspace}[/yellow].")


def extract_iso():
    """Extracts the source Debian ISO into the workspace directory."""
    remove_workspace()
    os.makedirs(WORKSPACE_DIR, exist_ok=True)
    command = [
        "xorriso", "-osirrox", "on:auto_chmod_on", "-indev", SOURCE_ISO_PATH,
        "-extract", "/", WORKSPACE_DIR
    ]
    subprocess.run(command, check=True, capture_output=True)
    make_workspace_writable()


def remove_existing_custom_iso():
    """Removes the previous generated ISO before rebuilding it."""
    if not os.path.lexists(CUSTOM_ISO_NAME):
        return
    if os.path.isdir(CUSTOM_ISO_NAME) and not os.path.islink(CUSTOM_ISO_NAME):
        error(f"Output path [yellow]'{CUSTOM_ISO_NAME}'[/yellow] is a directory.")
        raise typer.Exit(code=1)
    os.remove(CUSTOM_ISO_NAME)


def create_preseed_config():
    """Generates the preseed config from the YAML configuration file."""      
    config = load_post_install_config().get("preseed", {})                         
                                                                                 
    base_packages = " ".join(config.get("base_packages", []))                 
                                                                                 
    preseed_content = f"""                                                    
# --- Localization ---                                                        
d-i debian-installer/language string {config.get('language', 'en')}           
d-i debian-installer/country string {config.get('country', 'US')}             
d-i debian-installer/locale string {config.get('locale', 'en_US.UTF-8')}      
d-i keyboard-configuration/xkb-keymap select {config.get('keyboard_map', 'us')}                                                                          
                                                                              
# --- Network ---                                                             
d-i netcfg/get_domain string {config.get('domain_name', 'local')}             
d-i hw-detect/load_firmware boolean true                                      
                                                                              
# --- User Account ---                                                        
d-i passwd/root-login boolean false                                           
d-i passwd/make-user boolean true                                             
d-i passwd/user-fullname string {config.get('user_fullname', 'User')}         
d-i passwd/username string {config.get('username', 'user')}                   
d-i passwd/user-password-crypted password {config.get('crypted_password')}    
                                                                              
# --- Clock and Timezone ---                                                  
d-i clock-setup/utc boolean true                                              
d-i time/zone string {config.get('timezone', 'UTC')}                          
d-i clock-setup/ntp boolean true                                              
                                                                              
# --- Partitioning ---                                                        
d-i partman-auto/method string {config.get('partitioning_method', 'lvm')}     
d-i partman-auto-lvm/guided_size string {config.get('partitioning_size',      
'max')}                                                                         
d-i partman-partitioning/confirm_write_new_label boolean true                 
d-i partman/choose_partition select finish                                    
d-i partman/confirm boolean true                                              
d-i partman/confirm_nooverwrite boolean true                                  
                                                                              
# --- APT ---                                                                 
d-i apt-setup/non-free boolean true                                           
d-i apt-setup/contrib boolean true                                            
                                                                              
# --- Packages ---                                                            
tasksel tasksel/first multiselect ssh-server                                  
d-i pkgsel/include string {base_packages}                                     
d-i pkgsel/upgrade select full-upgrade                                        
d-i pkgsel/update-policy select unattended-upgrades                           
                                                                              
# --- Bootloader ---                                                          
d-i grub-installer/only_debian boolean true                                   
                                                                              
# --- Final Commands ---                                                      
d-i preseed/late_command string \\
    cp /cdrom/post_install_setup.sh /target/tmp/post_install_setup.sh; \\     
    if [ -d /cdrom/{SSH_KEY_STAGING_DIR} ]; then cp -a /cdrom/{SSH_KEY_STAGING_DIR} /target/tmp/{SSH_KEY_STAGING_DIR}; fi; \\
    chmod +x /target/tmp/post_install_setup.sh; \\                            
    in-target /tmp/post_install_setup.sh;                                     
d-i finish-install/reboot boolean true                                        
                                                                              
# --- Automation ---                                                          
d-i auto-install/enable boolean true                                          
d-i debian-installer/priority string critical                                 
d-i debconf/priority string critical                                          
    """.strip()                                                               
                                                                              
    dest_preseed_path = os.path.join(WORKSPACE_DIR, PRESEED_FILENAME)         
    with open(dest_preseed_path, "w") as f:                                   
        f.write(preseed_content)  


def update_bootloader_configs():
    """Modifies ISOLINUX and GRUB to default to a fully unattended install."""
    # --- ISOLINUX (BIOS) Modification ---
    isolinux_cfg_path = os.path.join(WORKSPACE_DIR, "isolinux", "isolinux.cfg")
    
    # Read original content
    with open(isolinux_cfg_path, "r") as f:
        original_isolinux_content = f.read()

    # Create new default entry and prepend it
    isolinux_autoinstall_config = """
DEFAULT autoinstall
LABEL autoinstall
    MENU LABEL Automated Install
    KERNEL /install.amd/vmlinuz
    APPEND initrd=/install.amd/initrd.gz --- quiet auto=true priority=critical preseed/file=/cdrom/preseed.cfg
    """.strip()

    # Combine and write back, setting a short timeout
    modified_isolinux_content = f"TIMEOUT 10\n{isolinux_autoinstall_config}\n{original_isolinux_content}"
    with open(isolinux_cfg_path, "w") as f:
        f.write(modified_isolinux_content)

    # --- GRUB (UEFI) Modification ---
    grub_cfg_path = os.path.join(WORKSPACE_DIR, "boot", "grub", "grub.cfg")

    # Read original content
    with open(grub_cfg_path, "r") as f:
        original_grub_content = f.read()

    # Create new default entry
    grub_autoinstall_entry = """
menuentry 'Automated Unattended Install' --class auto {
    linux    /install.amd/vmlinuz --- quiet auto=true priority=critical preseed/file=/cdrom/preseed.cfg
    initrd   /install.amd/initrd.gz
}
    """.strip()

    # Combine and write back, setting the new entry as default with a short timeout
    modified_grub_content = f'set timeout=1\nset default="0"\n\n{grub_autoinstall_entry}\n\n{original_grub_content}'
    with open(grub_cfg_path, "w") as f:
        f.write(modified_grub_content)


def generate_post_install_script():
    """Generates the post-install script from a YAML config."""
    config = load_post_install_config()

    packages = " ".join(config.get("packages", []))
    ssh_key_config = config.get("ssh_key", {})
    ssh_key_type = ssh_key_config.get("type", "ed25519")
    ssh_user = ssh_key_config.get("user", "user")
    generated_key_path = f"/home/{ssh_user}/.ssh/id_{ssh_key_type}"

    script_content = f"""#!/bin/bash
set -e

# --- Install packages ---
apt-get update
apt-get install -y --no-install-recommends {packages}

# --- Configure SSH key ---
install -d -m 700 -o {ssh_user} -g {ssh_user} /home/{ssh_user}/.ssh

if [ -f /tmp/{SSH_KEY_STAGING_DIR}/{SSH_PRIVATE_KEY_NAME} ] && [ -f /tmp/{SSH_KEY_STAGING_DIR}/{SSH_PUBLIC_KEY_NAME} ]; then
    install -m 600 -o {ssh_user} -g {ssh_user} /tmp/{SSH_KEY_STAGING_DIR}/{SSH_PRIVATE_KEY_NAME} /home/{ssh_user}/.ssh/{SSH_PRIVATE_KEY_NAME}
    install -m 644 -o {ssh_user} -g {ssh_user} /tmp/{SSH_KEY_STAGING_DIR}/{SSH_PUBLIC_KEY_NAME} /home/{ssh_user}/.ssh/{SSH_PUBLIC_KEY_NAME}
    rm -rf /tmp/{SSH_KEY_STAGING_DIR}
elif [ ! -f {generated_key_path} ]; then
    sudo -u {ssh_user} ssh-keygen -t {ssh_key_type} -f {generated_key_path} -N ""
fi

# --- Clean up ---
apt-get clean
rm -rf /var/lib/apt/lists/*

echo "Post-installation setup complete."
"""
    
    script_path = os.path.join(WORKSPACE_DIR, "post_install_setup.sh")
    with open(script_path, "w") as f:
        f.write(script_content)
    
    # Make the script executable
    os.chmod(script_path, 0o755)


def stage_current_user_ssh_keys(ssh_user: str, copy_ssh_keys: Optional[bool] = None):
    """Optionally copies the current user's ed25519 keypair into the ISO workspace."""
    staging_dir = Path(WORKSPACE_DIR) / SSH_KEY_STAGING_DIR
    if staging_dir.exists():
        shutil.rmtree(staging_dir)

    ssh_dir = Path.home() / ".ssh"
    private_key = ssh_dir / SSH_PRIVATE_KEY_NAME
    public_key = ssh_dir / SSH_PUBLIC_KEY_NAME

    if not private_key.exists() or not public_key.exists():
        message = f"No complete SSH keypair found at {private_key} and {public_key}."
        if copy_ssh_keys:
            error(message)
            raise typer.Exit(code=1)
        warning(f"{message} Skipping key import.")
        return

    should_copy = copy_ssh_keys
    if should_copy is None:
        should_copy = typer.confirm(
            f"Copy {private_key} and {public_key} into the ISO for user '{ssh_user}'? This embeds the private key in the ISO.",
            default=True
        )
    if not should_copy:
        skipped("SSH key import.")
        return

    staging_dir.mkdir(mode=0o700, parents=True)
    shutil.copy2(private_key, staging_dir / SSH_PRIVATE_KEY_NAME)
    shutil.copy2(public_key, staging_dir / SSH_PUBLIC_KEY_NAME)
    os.chmod(staging_dir / SSH_PRIVATE_KEY_NAME, 0o600)
    os.chmod(staging_dir / SSH_PUBLIC_KEY_NAME, 0o644)
    success(f"SSH keypair staged for [yellow]'{ssh_user}'[/yellow].")


def get_ssh_install_user():
    """Returns the account that should receive imported or generated SSH keys."""
    config = load_post_install_config()
    return (
        config.get("ssh_key", {}).get("user")
        or config.get("preseed", {}).get("username")
        or "user"
    )


def find_usb_drives():
    """Finds connected USB drives that are whole disks."""
    try:
        result = subprocess.run(
            ["lsblk", "-J", "-o", "NAME,SIZE,TYPE,TRAN"],
            check=True,

            capture_output=True,
            text=True
        )
        devices = json.loads(result.stdout).get("blockdevices", [])
        # Conservatively filter for removable USB disks
        usb_drives = [
            {"name": f"/dev/{dev['name']}", "size": dev["size"]}
            for dev in devices
            if dev.get("tran") == "usb" and dev.get("type") == "disk"
        ]
        return usb_drives
    except (FileNotFoundError, json.JSONDecodeError, subprocess.CalledProcessError):
        return []


def flash_selected_usb_drive(device: str, confirm_flash: Optional[bool] = None):
    """Flashes a selected USB drive, optionally pre-answering the destructive confirmation."""
    if confirm_flash is False:
        skipped("USB flashing cancelled by command option.")
        return False

    flash_usb_drive(device, force=confirm_flash is True)
    return True


def handle_usb_flashing(
    flash_usb: Optional[bool] = None,
    usb_device: Optional[str] = None,
    confirm_flash: Optional[bool] = None,
):
    """Optionally flashes the generated ISO to USB using command options or prompts."""
    if flash_usb is False:
        skipped("USB flashing.")
        return

    if usb_device:
        flash_selected_usb_drive(usb_device, confirm_flash)
        return

    usb_drives = find_usb_drives()
    if not usb_drives:
        if flash_usb:
            error("No USB drives detected. Provide --usb-device to flash a specific device.")
            raise typer.Exit(code=1)
        return

    if len(usb_drives) == 1:
        selected_drive = usb_drives[0]['name']
        console.print(f"\n[bold cyan]Detected single USB Drive:[/bold cyan] {selected_drive} ({usb_drives[0]['size']})")
        should_flash = flash_usb
        if should_flash is None:
            should_flash = typer.confirm(f"Do you want to flash the ISO to {selected_drive}?", default=True)
        if should_flash:
            flash_selected_usb_drive(selected_drive, confirm_flash if confirm_flash is not None else True)
        else:
            skipped("USB flashing cancelled by user.")
        return

    console.print("\n[bold cyan]Available USB Drives Detected:[/bold cyan]")
    for i, drive in enumerate(usb_drives):
        console.print(f"  [bold]{i+1}[/bold]: {drive['name']} ({drive['size']})")

    if flash_usb:
        error("Multiple USB drives detected. Provide --usb-device to avoid interactive selection.")
        raise typer.Exit(code=1)

    if typer.confirm("\nDo you want to flash the ISO to a USB drive?", default=True):
        choice = typer.prompt("Enter the number of the drive to flash")
        try:
            drive_index = int(choice) - 1
            if 0 <= drive_index < len(usb_drives):
                selected_drive = usb_drives[drive_index]['name']
                flash_selected_usb_drive(selected_drive, confirm_flash)
            else:
                error("Invalid selection.")
        except ValueError:
            error("Invalid input. Please enter a number.")


def rebuild_iso():
    """Rebuilds the workspace into a new, bootable ISO image."""
    remove_existing_custom_iso()
    command = [
        "xorriso", "-as", "mkisofs",
        "-isohybrid-mbr", "/usr/lib/ISOLINUX/isohdpfx.bin",
        "-c", "isolinux/boot.cat",
        "-b", "isolinux/isolinux.bin",
        "-no-emul-boot", "-boot-load-size", "4", "-boot-info-table",
        "-eltorito-alt-boot",
        "-e", "boot/grub/efi.img",
        "-no-emul-boot",
        "-isohybrid-gpt-basdat",
        "-o", CUSTOM_ISO_NAME,
        WORKSPACE_DIR
    ]
    subprocess.run(command, check=True, capture_output=True)


def flash_usb_drive(device: str, force: bool = False):
    """Flashes the custom ISO to the selected USB drive."""
    warning(f"Writing [yellow]{CUSTOM_ISO_NAME}[/yellow] to [yellow]{device}[/yellow].")
    
    # Unmount the device first
    try:
        subprocess.run(["sudo", "umount", f"{device}*"], check=True, capture_output=True)
    except subprocess.CalledProcessError:
        # Ignore errors if the device is not mounted
        pass

    warning(f"This will destroy all data on [yellow]{device}[/yellow].")
    if not force and not typer.confirm("Are you absolutely sure you want to continue?", default=True):
        skipped("Operation cancelled.")
        raise typer.Exit()

    command = [
        "sudo", "dd", f"if={CUSTOM_ISO_NAME}", f"of={device}", "bs=4M", "status=progress"
    ]
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True,
    ) as progress:
        progress.add_task(description=f"Flashing to {device}...", total=None)
        subprocess.run(
            command,
            check=True,
            stderr=subprocess.PIPE,
            stdout=subprocess.PIPE
        )
        success(f"Flashed [yellow]{CUSTOM_ISO_NAME}[/yellow] to [yellow]{device}[/yellow].")
        
        # Eject the device
        subprocess.run(["sudo", "eject", device], check=True, capture_output=True)
        success(f"Ejected [yellow]{device}[/yellow].")


@app.command()
def create(
    copy_ssh_keys: Optional[bool] = typer.Option(
        None,
        "--copy-ssh-keys/--no-copy-ssh-keys",
        help="Copy or skip the current user's ~/.ssh/id_ed25519 keypair without prompting.",
    ),
    flash_usb: Optional[bool] = typer.Option(
        None,
        "--flash-usb/--no-flash-usb",
        help="Flash or skip USB writing without prompting.",
    ),
    usb_device: Optional[str] = typer.Option(
        None,
        "--usb-device",
        help="USB block device to flash, such as /dev/sdb. Bypasses USB selection prompts.",
    ),
    confirm_flash: Optional[bool] = typer.Option(
        None,
        "--confirm-flash/--no-confirm-flash",
        help="Confirm or cancel the destructive USB write without prompting.",
    ),
):
    """
    Builds a customized Debian ISO with unattended installation.
    """
    console.print("[bold cyan]Creating custom Debian ISO[/bold cyan]")

    with console.status("[bold green]Verifying prerequisites...[/bold green]"):
        verify_prerequisites()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True,
    ) as progress:
        progress.add_task(description="Extracting ISO...", total=None)
        extract_iso()

    stage_current_user_ssh_keys(get_ssh_install_user(), copy_ssh_keys)

    with console.status("[bold green]Generating preseed configuration...[/bold green]"):
        create_preseed_config()

    with console.status("[bold green]Generating post-install script...[/bold green]"):
        generate_post_install_script()

    with console.status("[bold green]Updating bootloader menus...[/bold green]"):
        update_bootloader_configs()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True,
    ) as progress:
        progress.add_task(description="Rebuilding custom ISO...", total=None)
        rebuild_iso()
    success(f"Created [yellow]'{CUSTOM_ISO_NAME}'[/yellow].")

    handle_usb_flashing(flash_usb, usb_device, confirm_flash)

if __name__ == "__main__":
    app()
