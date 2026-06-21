#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
helix_iso_customizer.py

A utility for building Helix Debian network installation ISOs.

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
import secrets
import string
from pathlib import Path
from typing import Optional
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

# --- Typer App and Rich Console Initialization ---
app = typer.Typer(
    name="helix",
    help="Create Helix Debian ISOs with unattended installation.",
    add_completion=False,
    no_args_is_help=True
)
console = Console()

# --- Constants & Configuration ---
DEFAULT_SOURCE_ISO_PATH = "debian-13.0.0-amd64-netinst.iso"
DEFAULT_WORKSPACE_DIR = "iso-extract"
DEFAULT_CUSTOM_ISO_NAME = "helix-debian-13.iso"
DEFAULT_CONFIG_PATH = "helix_config.yaml"
INSTALLER_PRESEED_FILENAME = "preseed.cfg"
SSH_KEY_STAGING_DIR = "helix-ssh"
KWIN_SCRIPT_STAGING_DIR = "helix-kwin-scripts"
WALLPAPER_STAGING_DIR = "helix-wallpaper"
SSH_PRIVATE_KEY_NAME = "id_ed25519"
SSH_PUBLIC_KEY_NAME = "id_ed25519.pub"
SHA512_CRYPT_SALT_CHARS = string.ascii_letters + string.digits + "./"


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
    """Confirms required system tools are available on the PATH."""
    if not shutil.which("xorriso"):
        error("`xorriso` is not installed or not in the system PATH.")
        console.print("Please install it using: [cyan]sudo apt-get install -y xorriso[/cyan]")
        raise typer.Exit(code=1)
    if not shutil.which("openssl"):
        error("`openssl` is not installed or not in the system PATH.")
        console.print("Please install it using: [cyan]sudo apt-get install -y openssl[/cyan]")
        raise typer.Exit(code=1)


def load_config(config_path: str):
    """Loads and validates the YAML configuration used for ISO customization."""
    if not os.path.exists(config_path):
        error(f"Config not found at [yellow]'{config_path}'[/yellow].")
        raise typer.Exit(code=1)

    with open(config_path, "r") as f:
        return yaml.safe_load(f) or {}


def iso_config(config: dict):
    """Returns ISO build paths from YAML with stable defaults."""
    iso = config.get("iso", {})
    return {
        "source": iso.get("source", DEFAULT_SOURCE_ISO_PATH),
        "workspace": iso.get("workspace", DEFAULT_WORKSPACE_DIR),
        "output": iso.get("output", DEFAULT_CUSTOM_ISO_NAME),
    }


def package_list(*package_groups):
    """Returns a deduplicated package string while preserving config order."""
    packages = []
    for group in package_groups:
        for package in group:
            if package not in packages:
                packages.append(package)
    return " ".join(packages)


def debian_bool(value: bool):
    """Formats Python booleans for Debian Installer preseed values."""
    return "true" if value else "false"


def crypt_password(plaintext_password: str):
    """Returns a SHA-512 crypt hash for Debian Installer password preseeding."""
    if not shutil.which("openssl"):
        error("`openssl` is not installed or not in the system PATH.")
        raise typer.Exit(code=1)

    salt = "".join(secrets.choice(SHA512_CRYPT_SALT_CHARS) for _ in range(16))
    result = subprocess.run(
        ["openssl", "passwd", "-6", "-salt", salt, "-stdin"],
        input=f"{plaintext_password}\n",
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def get_install_password(install_password: Optional[str]):
    """Reads the plaintext install password from CLI option or hidden prompt."""
    if install_password is not None:
        return install_password
    return typer.prompt(
        "Install user password",
        hide_input=True,
        confirmation_prompt=True,
    )


def make_workspace_writable(workspace_dir: str):
    """Adds owner write permissions to the generated extraction workspace."""
    for root, dirs, files in os.walk(workspace_dir, topdown=False):
        for filename in files:
            path = os.path.join(root, filename)
            if not os.path.islink(path):
                os.chmod(path, 0o600)
        for dirname in dirs:
            path = os.path.join(root, dirname)
            if not os.path.islink(path):
                os.chmod(path, 0o700)
    os.chmod(workspace_dir, 0o700)


def remove_workspace(workspace_dir: str):
    """Removes the generated ISO extraction workspace, including read-only files."""
    if not os.path.exists(workspace_dir):
        return

    try:
        make_workspace_writable(workspace_dir)
        shutil.rmtree(workspace_dir)
    except PermissionError:
        stale_workspace = f"{workspace_dir}.stale"
        suffix = 1
        while os.path.exists(stale_workspace):
            suffix += 1
            stale_workspace = f"{workspace_dir}.stale-{suffix}"
        os.rename(workspace_dir, stale_workspace)
        warning(f"Moved unremovable workspace to [yellow]{stale_workspace}[/yellow].")


def extract_iso(source_iso_path: str, workspace_dir: str):
    """Extracts the source Debian ISO into the workspace directory."""
    remove_workspace(workspace_dir)
    os.makedirs(workspace_dir, exist_ok=True)
    command = [
        "xorriso", "-osirrox", "on:auto_chmod_on", "-indev", source_iso_path,
        "-extract", "/", workspace_dir
    ]
    subprocess.run(command, check=True, capture_output=True)
    make_workspace_writable(workspace_dir)


def remove_existing_custom_iso(custom_iso_name: str):
    """Removes the previous generated ISO before rebuilding it."""
    if not os.path.lexists(custom_iso_name):
        return
    if os.path.isdir(custom_iso_name) and not os.path.islink(custom_iso_name):
        error(f"Output path [yellow]'{custom_iso_name}'[/yellow] is a directory.")
        raise typer.Exit(code=1)
    os.remove(custom_iso_name)


def create_preseed_config(config: dict, workspace_dir: str, crypted_password: str):
    """Generates the preseed config from the YAML configuration file."""      
    preseed_config = config.get("preseed", {})
    ssh_key_config = config.get("ssh_key", {})
    ssh_user = ssh_key_config.get("user") or preseed_config.get("username", "user")
    ssh_key_type = ssh_key_config.get("type", "ed25519")
    generated_key_path = f"/home/{ssh_user}/.ssh/id_{ssh_key_type}"
    tasks = ", ".join(preseed_config.get("tasks", ["ssh-server"]))
    extra_preseed_lines = preseed_config.get("extra", [])
    extra_preseed = ""
    if extra_preseed_lines:
        extra_preseed = "\n\n# --- Extra YAML Preseed Entries ---\n" + "\n".join(extra_preseed_lines)
                                                                                 
    packages = package_list(
        preseed_config.get("base_packages", []),
        config.get("packages", []),
    )
                                                                                 
    preseed_content = f"""                                                    
# --- Localization ---                                                        
d-i debian-installer/language string {preseed_config.get('language', 'en')}           
d-i debian-installer/country string {preseed_config.get('country', 'US')}             
d-i debian-installer/locale string {preseed_config.get('locale', 'en_US.UTF-8')}      
d-i keyboard-configuration/xkb-keymap select {preseed_config.get('keyboard_map', 'us')}                                                                          
                                                                              
# --- Network ---                                                             
d-i netcfg/get_domain string {preseed_config.get('domain_name', 'local')}             
d-i hw-detect/load_firmware boolean {debian_bool(preseed_config.get('load_firmware', True))}                                      
                                                                              
# --- User Account ---                                                        
d-i passwd/root-login boolean {debian_bool(preseed_config.get('root_login', False))}                                           
d-i passwd/make-user boolean {debian_bool(preseed_config.get('make_user', True))}                                             
d-i passwd/user-fullname string {preseed_config.get('user_fullname', 'User')}         
d-i passwd/username string {preseed_config.get('username', 'user')}                   
d-i passwd/user-password-crypted password {crypted_password}    
                                                                              
# --- Clock and Timezone ---                                                  
d-i clock-setup/utc boolean {debian_bool(preseed_config.get('clock_utc', True))}                                              
d-i time/zone string {preseed_config.get('timezone', 'UTC')}                          
d-i clock-setup/ntp boolean {debian_bool(preseed_config.get('clock_ntp', True))}                                              
                                                                              
# --- Partitioning ---                                                        
d-i partman-auto/method string {preseed_config.get('partitioning_method', 'lvm')}     
d-i partman-auto-lvm/guided_size string {preseed_config.get('partitioning_size',      
'max')}                                                                         
d-i partman-auto/choose_recipe select {preseed_config.get('partition_recipe', 'atomic')}                                    
d-i partman/default_filesystem string {preseed_config.get('filesystem', 'ext4')}                                    
d-i partman/mount_style select {preseed_config.get('mount_style', 'uuid')}                                    
d-i partman-md/device_remove_md boolean {debian_bool(preseed_config.get('remove_existing_raid', True))}                 
d-i partman-lvm/device_remove_lvm boolean {debian_bool(preseed_config.get('remove_existing_lvm', True))}                 
d-i partman-lvm/confirm boolean {debian_bool(preseed_config.get('confirm_lvm', True))}                 
d-i partman-lvm/confirm_nooverwrite boolean {debian_bool(preseed_config.get('confirm_lvm_nooverwrite', True))}                 
d-i partman-partitioning/confirm_write_new_label boolean {debian_bool(preseed_config.get('confirm_write_new_label', True))}                 
d-i partman/choose_partition select {preseed_config.get('choose_partition', 'finish')}                                    
d-i partman/confirm boolean {debian_bool(preseed_config.get('confirm_partitioning', True))}                                              
d-i partman/confirm_nooverwrite boolean {debian_bool(preseed_config.get('confirm_nooverwrite', True))}                                  
                                                                              
# --- APT ---                                                                 
d-i apt-setup/non-free boolean {debian_bool(preseed_config.get('apt_non_free', True))}                                           
d-i apt-setup/contrib boolean {debian_bool(preseed_config.get('apt_contrib', True))}                                            
                                                                              
# --- Packages ---                                                            
tasksel tasksel/first multiselect {tasks}                                  
d-i pkgsel/include string {packages}                                          
d-i pkgsel/upgrade select {preseed_config.get('package_upgrade', 'full-upgrade')}                                        
d-i pkgsel/update-policy select {preseed_config.get('update_policy', 'unattended-upgrades')}                           
                                                                              
# --- Bootloader ---                                                          
d-i grub-installer/only_debian boolean {debian_bool(preseed_config.get('grub_only_debian', True))}                                   
                                                                              
# --- Final Commands ---                                                      
d-i preseed/late_command string \\
    in-target install -d -m 700 -o {ssh_user} -g {ssh_user} /home/{ssh_user}/.ssh; \\
    if [ -d /cdrom/{WALLPAPER_STAGING_DIR}/wallpapers ]; then \\
        rm -rf /target/usr/share/wallpapers; \\
        cp -a /cdrom/{WALLPAPER_STAGING_DIR}/wallpapers /target/usr/share/wallpapers; \\
        for plasma_defaults in /target/usr/share/plasma/look-and-feel/*/contents/defaults; do \\
            [ -e "$plasma_defaults" ] || continue; \\
            sed -i 's/^Image=.*/Image=Helix/' "$plasma_defaults"; \\
        done; \\
    fi; \\
    if [ -d /cdrom/{KWIN_SCRIPT_STAGING_DIR} ]; then \\
        cp -a /cdrom/{KWIN_SCRIPT_STAGING_DIR} /target/tmp/{KWIN_SCRIPT_STAGING_DIR}; \\
        for kwin_script in /target/tmp/{KWIN_SCRIPT_STAGING_DIR}/*.kwinscript; do \\
            [ -e "$kwin_script" ] || continue; \\
            in-target runuser -u {ssh_user} -- plasmapkg2 -t kwinscript -i /tmp/{KWIN_SCRIPT_STAGING_DIR}/$(basename "$kwin_script"); \\
        done; \\
        rm -rf /target/tmp/{KWIN_SCRIPT_STAGING_DIR}; \\
    fi; \\
    if [ -f /cdrom/{SSH_KEY_STAGING_DIR}/{SSH_PRIVATE_KEY_NAME} ] && [ -f /cdrom/{SSH_KEY_STAGING_DIR}/{SSH_PUBLIC_KEY_NAME} ]; then \\
        cp /cdrom/{SSH_KEY_STAGING_DIR}/{SSH_PRIVATE_KEY_NAME} /target/home/{ssh_user}/.ssh/{SSH_PRIVATE_KEY_NAME}; \\
        cp /cdrom/{SSH_KEY_STAGING_DIR}/{SSH_PUBLIC_KEY_NAME} /target/home/{ssh_user}/.ssh/{SSH_PUBLIC_KEY_NAME}; \\
        in-target chown {ssh_user}:{ssh_user} /home/{ssh_user}/.ssh/{SSH_PRIVATE_KEY_NAME} /home/{ssh_user}/.ssh/{SSH_PUBLIC_KEY_NAME}; \\
        chmod 600 /target/home/{ssh_user}/.ssh/{SSH_PRIVATE_KEY_NAME}; \\
        chmod 644 /target/home/{ssh_user}/.ssh/{SSH_PUBLIC_KEY_NAME}; \\
    elif [ ! -f /target{generated_key_path} ]; then \\
        in-target ssh-keygen -t {ssh_key_type} -f {generated_key_path} -N ""; \\
        in-target chown {ssh_user}:{ssh_user} {generated_key_path} {generated_key_path}.pub; \\
    fi; \\
    in-target apt-get clean; \\
    rm -rf /target/var/lib/apt/lists/*;                                     
d-i finish-install/reboot boolean {debian_bool(preseed_config.get('finish_reboot', True))}{extra_preseed}

# --- Automation ---                                                          
d-i auto-install/enable boolean {debian_bool(preseed_config.get('auto_install', True))}                                          
d-i debian-installer/priority string {preseed_config.get('installer_priority', 'critical')}                                 
d-i debconf/priority string {preseed_config.get('debconf_priority', 'critical')}                                          
    """.strip()                                                               
                                                                              
    dest_preseed_path = os.path.join(workspace_dir, INSTALLER_PRESEED_FILENAME)         
    with open(dest_preseed_path, "w") as f:                                   
        f.write(preseed_content)  


def configured_kwin_scripts(config: dict, config_dir: Path):
    """Returns KWin script package paths from YAML."""
    script_paths = []
    for script in config.get("kwin_scripts", []):
        script_path = Path(script)
        if not script_path.is_absolute():
            script_path = config_dir / script_path
        script_paths.append(script_path)
    return script_paths


def stage_kwin_scripts(config: dict, workspace_dir: str, config_dir: Path):
    """Copies configured KWin script packages into the ISO workspace."""
    scripts = configured_kwin_scripts(config, config_dir)
    if not scripts:
        return

    staging_dir = Path(workspace_dir) / KWIN_SCRIPT_STAGING_DIR
    if staging_dir.exists():
        shutil.rmtree(staging_dir)

    staged_scripts = []
    for script in scripts:
        if not script.exists():
            warning(f"KWin script package [yellow]'{script}'[/yellow] not found. Skipping.")
            continue
        staging_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        shutil.copy2(script, staging_dir / script.name)
        staged_scripts.append(script.name)

    if staged_scripts:
        success(f"Staged KWin scripts: [yellow]{', '.join(staged_scripts)}[/yellow].")


def configured_wallpaper(config: dict, config_dir: Path):
    """Returns the configured wallpaper path from YAML."""
    wallpaper = config.get("wallpaper")
    if not wallpaper:
        return None
    if isinstance(wallpaper, dict):
        wallpaper = wallpaper.get("source")
    if not wallpaper:
        return None

    wallpaper_path = Path(wallpaper)
    if not wallpaper_path.is_absolute():
        wallpaper_path = config_dir / wallpaper_path
    return wallpaper_path


def stage_wallpaper(config: dict, workspace_dir: str, config_dir: Path):
    """Copies the configured wallpaper into the ISO as the only Plasma wallpaper."""
    wallpaper_path = configured_wallpaper(config, config_dir)
    if not wallpaper_path:
        return

    if not wallpaper_path.exists():
        warning(f"Wallpaper [yellow]'{wallpaper_path}'[/yellow] not found. Skipping.")
        return

    staging_dir = Path(workspace_dir) / WALLPAPER_STAGING_DIR
    if staging_dir.exists():
        shutil.rmtree(staging_dir)

    wallpaper_package = staging_dir / "wallpapers" / "Helix"
    image_dir = wallpaper_package / "contents" / "images"
    image_dir.mkdir(mode=0o755, parents=True)
    shutil.copy2(wallpaper_path, image_dir / "wallpaper.jpg")
    shutil.copy2(wallpaper_path, wallpaper_package / "contents" / "screenshot.jpg")
    metadata = {
        "KPlugin": {
            "Id": "Helix",
            "Name": "Helix",
            "License": "LicenseRef-Local",
        }
    }
    with open(wallpaper_package / "metadata.json", "w") as f:
        json.dump(metadata, f, indent=4)
        f.write("\n")
    success(f"Staged wallpaper [yellow]'{wallpaper_path.name}'[/yellow].")


def update_bootloader_configs(workspace_dir: str):
    """Modifies ISOLINUX and GRUB to default to a fully unattended install."""
    # --- ISOLINUX (BIOS) Modification ---
    isolinux_cfg_path = os.path.join(workspace_dir, "isolinux", "isolinux.cfg")
    
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
    grub_cfg_path = os.path.join(workspace_dir, "boot", "grub", "grub.cfg")

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


def stage_current_user_ssh_keys(workspace_dir: str, ssh_user: str, copy_ssh_keys: Optional[bool] = None):
    """Optionally copies the current user's ed25519 keypair into the ISO workspace."""
    staging_dir = Path(workspace_dir) / SSH_KEY_STAGING_DIR
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


def get_ssh_install_user(config: dict):
    """Returns the account that should receive imported or generated SSH keys."""
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


def flash_selected_usb_drive(custom_iso_name: str, device: str, confirm_flash: Optional[bool] = None):
    """Flashes a selected USB drive, optionally pre-answering the destructive confirmation."""
    if confirm_flash is False:
        skipped("USB flashing cancelled by command option.")
        return False

    flash_usb_drive(custom_iso_name, device, force=confirm_flash is True)
    return True


def handle_usb_flashing(
    custom_iso_name: str,
    flash_usb: Optional[bool] = None,
    usb_device: Optional[str] = None,
    confirm_flash: Optional[bool] = None,
):
    """Optionally flashes the generated ISO to USB using command options or prompts."""
    if flash_usb is False:
        skipped("USB flashing.")
        return

    if usb_device:
        flash_selected_usb_drive(custom_iso_name, usb_device, confirm_flash)
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
            flash_selected_usb_drive(custom_iso_name, selected_drive, confirm_flash if confirm_flash is not None else True)
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
                flash_selected_usb_drive(custom_iso_name, selected_drive, confirm_flash)
            else:
                error("Invalid selection.")
        except ValueError:
            error("Invalid input. Please enter a number.")


def rebuild_iso(workspace_dir: str, custom_iso_name: str):
    """Rebuilds the workspace into a new, bootable ISO image."""
    remove_existing_custom_iso(custom_iso_name)
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
        "-o", custom_iso_name,
        workspace_dir
    ]
    subprocess.run(command, check=True, capture_output=True)


def flash_usb_drive(custom_iso_name: str, device: str, force: bool = False):
    """Flashes the custom ISO to the selected USB drive."""
    warning(f"Writing [yellow]{custom_iso_name}[/yellow] to [yellow]{device}[/yellow].")
    
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
        "sudo", "dd", f"if={custom_iso_name}", f"of={device}", "bs=4M", "status=progress"
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
        success(f"Flashed [yellow]{custom_iso_name}[/yellow] to [yellow]{device}[/yellow].")
        
        # Eject the device
        subprocess.run(["sudo", "eject", device], check=True, capture_output=True)
        success(f"Ejected [yellow]{device}[/yellow].")


@app.command()
def create(
    config_path: str = typer.Option(
        DEFAULT_CONFIG_PATH,
        "--config",
        help="YAML configuration file for the ISO build.",
    ),
    install_password: Optional[str] = typer.Option(
        None,
        "--install-password",
        help="Plaintext install user password. It is SHA-512 crypted before writing the generated preseed.",
    ),
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
    console.print("[bold cyan]Creating Helix ISO[/bold cyan]")
    config = load_config(config_path)
    config_dir = Path(config_path).resolve().parent
    iso = iso_config(config)

    with console.status("[bold green]Verifying prerequisites...[/bold green]"):
        verify_prerequisites()

    crypted_password = crypt_password(get_install_password(install_password))

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True,
    ) as progress:
        progress.add_task(description="Extracting ISO...", total=None)
        extract_iso(iso["source"], iso["workspace"])

    stage_current_user_ssh_keys(iso["workspace"], get_ssh_install_user(config), copy_ssh_keys)
    stage_kwin_scripts(config, iso["workspace"], config_dir)
    stage_wallpaper(config, iso["workspace"], config_dir)

    with console.status("[bold green]Generating preseed configuration...[/bold green]"):
        create_preseed_config(config, iso["workspace"], crypted_password)

    with console.status("[bold green]Updating bootloader menus...[/bold green]"):
        update_bootloader_configs(iso["workspace"])

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True,
    ) as progress:
        progress.add_task(description="Rebuilding custom ISO...", total=None)
        rebuild_iso(iso["workspace"], iso["output"])
    success(f"Created [yellow]'{iso['output']}'[/yellow].")

    handle_usb_flashing(iso["output"], flash_usb, usb_device, confirm_flash)

if __name__ == "__main__":
    app()
