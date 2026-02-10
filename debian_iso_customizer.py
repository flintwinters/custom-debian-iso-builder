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


def _verify_prerequisites():
    """Confirms that `xorriso` is available on the system PATH."""
    if not shutil.which("xorriso"):
        console.print("[bold red]Error:[/bold red] `xorriso` is not installed or not in the system PATH.")
        console.print("Please install it using: [cyan]sudo apt-get install -y xorriso[/cyan]")
        raise typer.Exit(code=1)


def _extract_iso():
    """Extracts the source Debian ISO into the workspace directory."""
    os.makedirs(WORKSPACE_DIR, exist_ok=True)
    command = [
        "xorriso", "-osirrox", "on", "-indev", SOURCE_ISO_PATH,
        "-extract", "/", WORKSPACE_DIR
    ]
    subprocess.run(command, check=True, capture_output=True)


def _create_preseed_config():
    """Generates the preseed config from the YAML configuration file."""      
    if not os.path.exists(POST_INSTALL_CONFIG):                               
        console.print(f"[bold red]Error:[/bold red] Post-install config not at [yellow]'{POST_INSTALL_CONFIG}'[/yellow].")                            
        raise typer.Exit(code=1)                                              
                                                                                 
    with open(POST_INSTALL_CONFIG, "r") as f:                                 
        config = yaml.safe_load(f).get("preseed", {})                         
                                                                                 
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


def _update_bootloader_configs():
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


def _generate_post_install_script():
    """Generates the post-install script from a YAML config."""
    if not os.path.exists(POST_INSTALL_CONFIG):
        console.print(f"[bold red]Error:[/bold red] Post-install config not found at [yellow]'{POST_INSTALL_CONFIG}'[/yellow].")
        raise typer.Exit(code=1)

    with open(POST_INSTALL_CONFIG, "r") as f:
        config = yaml.safe_load(f)

    packages = " ".join(config.get("packages", []))
    ssh_key_config = config.get("ssh_key", {})
    ssh_key_type = ssh_key_config.get("type", "ed25519")
    ssh_user = ssh_key_config.get("user", "user")

    script_content = f"""#!/bin/bash
set -e

# --- Install packages ---
apt-get update
apt-get install -y --no-install-recommends {packages}

# --- Generate SSH key ---
sudo -u {ssh_user} ssh-keygen -t {ssh_key_type} -f /home/{ssh_user}/.ssh/id_rsa -N ""

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


def _find_usb_drives():
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


def _rebuild_iso():
    """Rebuilds the workspace into a new, bootable ISO image."""
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


def _flash_usb_drive(device: str, force: bool = False):
    """Flashes the custom ISO to the selected USB drive."""
    console.print(f"[bold yellow]Preparing to flash {CUSTOM_ISO_NAME} to {device}...[/bold yellow]")
    
    # Unmount the device first
    try:
        subprocess.run(["sudo", "umount", f"{device}*"], check=True, capture_output=True)
    except subprocess.CalledProcessError:
        # Ignore errors if the device is not mounted
        pass

    console.print(f"[bold red]WARNING: This will destroy all data on {device}.[/bold red]")
    if not force and not typer.confirm("Are you absolutely sure you want to continue?"):
        console.print("[yellow]Operation cancelled.[/yellow]")
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
        console.print(f"[bold green]Successfully flashed {CUSTOM_ISO_NAME} to {device}.[/bold green]")
        
        # Eject the device
        console.print(f"[bold yellow]Ejecting {device}...[/bold yellow]")
        subprocess.run(["sudo", "eject", device], check=True, capture_output=True)
        console.print(f"[bold green]Successfully ejected {device}.[/bold green]")


@app.command()
def create():
    """
    Builds a customized Debian ISO with unattended installation.
    """
    console.print("[bold cyan]Starting Debian ISO Customization Process[/bold cyan]")

    console.print("[bold cyan]Starting Debian ISO Customization Process[/bold cyan]")

    with console.status("[bold green]Verifying prerequisites...[/bold green]"):
        _verify_prerequisites()
    console.print("SUCCESS: Prerequisites verified.")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True,
    ) as progress:
        progress.add_task(description="Extracting ISO...", total=None)
        _extract_iso()
    console.print(f"SUCCESS: Source ISO extracted to [yellow]'{WORKSPACE_DIR}/'[/yellow].")

    with console.status("[bold green]Generating preseed configuration...[/bold green]"):
        _create_preseed_config()
    console.print(f"SUCCESS: Preseed file [yellow]'{PRESEED_FILENAME}'[/yellow] copied to workspace.")

    with console.status("[bold green]Generating post-install script...[/bold green]"):
        _generate_post_install_script()
    console.print("SUCCESS: Post-install script generated from YAML config.")

    with console.status("[bold green]Updating bootloader menus...[/bold green]"):
        _update_bootloader_configs()
    console.print("SUCCESS: ISOLINUX and GRUB configurations updated.")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True,
    ) as progress:
        progress.add_task(description="Rebuilding custom ISO...", total=None)
        _rebuild_iso()
    console.print(f"SUCCESS: Custom ISO [yellow]'{CUSTOM_ISO_NAME}'[/yellow] created successfully.")

    # --- Optional: Flash to USB ---
    usb_drives = _find_usb_drives()
    if usb_drives:
        if len(usb_drives) == 1:
            selected_drive = usb_drives[0]['name']
            console.print(f"\n[bold cyan]Detected single USB Drive:[/bold cyan] {selected_drive} ({usb_drives[0]['size']})")
            if typer.confirm(f"Do you want to flash the ISO to {selected_drive}?", default=True):
                _flash_usb_drive(selected_drive, force=True)
                console.print(f"\n[bold green]SUCCESS: ISO successfully flashed to {selected_drive}.[/bold green]")
            else:
                console.print("[yellow]Flashing cancelled by user.[/yellow]")
        else:
            console.print("\n[bold cyan]Available USB Drives Detected:[/bold cyan]")
            for i, drive in enumerate(usb_drives):
                console.print(f"  [bold]{i+1}[/bold]: {drive['name']} ({drive['size']})")
            
            if typer.confirm("\nDo you want to flash the ISO to a USB drive?"):
                choice = typer.prompt("Enter the number of the drive to flash")
                try:
                    drive_index = int(choice) - 1
                    if 0 <= drive_index < len(usb_drives):
                        selected_drive = usb_drives[drive_index]['name']
                        _flash_usb_drive(selected_drive)
                        console.print(f"\n[bold green]SUCCESS: ISO successfully flashed to {selected_drive}.[/bold green]")
                    else:
                        console.print("[bold red]Invalid selection.[/bold red]")
                except ValueError:
                    console.print("[bold red]Invalid input. Please enter a number.[/bold red]")

    console.print("\n[bold green]Process complete.[/bold green]")

if __name__ == "__main__":
    app()
