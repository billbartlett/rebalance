#!/usr/bin/python3
import re
import psutil
import shelve
import subprocess
import argparse
import glob
from pathlib import Path
from rich import print
from rich.console import Console
from rich.table import Table

# Setup Logging
console = Console()

# Constants
ROOT_DIR = Path("/mnt")
USER_SHARES_DIR = ROOT_DIR / "user"
DB_SHARES = "shares.db"
DB_DIRS = "dirs.db"

# Argument Parser
parser = argparse.ArgumentParser(description="Rebalance Unraid shares using rsync.")
parser.add_argument("--execute", action="store_true", help="Execute the move (default is dry-run)")
parser.add_argument("--rescan", action="store_true", help="Rescan directories and shares (ignores DB)")
args = parser.parse_args()

### **Utility Functions**

def datasize(num):
    """Converts bytes to a human-readable format while still preserving negative numbers for reporting."""
    sign = "-" if num < 0 else ""  # Store negative sign if needed
    num = abs(num)  # Work with the absolute value for conversion

    for unit in ["bytes", "KB", "MB", "GB", "TB", "PB"]:
        if num < 1024:
            return f"{sign}{num:.2f} {unit}"  # Apply negative sign only to the final output
        num /= 1024

    return f"{sign}{num:.2f} PB"  # Handles extremely large values

def get_fs_usage(path):
    """Gets used space for a specific disk path, similar to 'df'."""
    return psutil.disk_usage(path).used  # Returns only used space in bytes

def run_du(path):
    """Uses 'du -sb' to get total used space and returns in bytes."""
    result = subprocess.run(["du", "-sb", str(path)], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    return int(result.stdout.split()[0]) if result.stdout else 0  # Keeps in bytes


### **Load or Scan Data**
def load_or_scan_shares():
    """Loads shares data from DB or rescans if not found."""
    with shelve.open(DB_SHARES) as db:
        if args.rescan or not bool(db):  # Rescan only if requested or DB is empty
            console.print("Scanning shares...")
            sharestats = {
                share.name: run_du(USER_SHARES_DIR / share)
                for share in sorted(USER_SHARES_DIR.iterdir()) if share.is_dir()
            }
            db.clear()
            db.update(sharestats)  # Save to DB
        else:
            sharestats = dict(db)  # Load existing data
    return sharestats

def load_or_scan_directories():
    """Loads directory data from DB or rescans if not found."""
    with shelve.open(DB_DIRS) as db:
        if args.rescan or not bool(db):  # Rescan only if requested or DB is empty
            console.print("Scanning directories...")
            dirstats = {}
            for disk in sorted(ROOT_DIR.iterdir()):
                if disk.is_dir() and re.match(r"^disk[0-9]+$", disk.name):
                    for share in sorted((ROOT_DIR / disk).iterdir()):
                        if share.is_dir():
                            for entry in sorted(share.iterdir()):
                                if entry.is_dir():
                                    dirstats[str(entry)] = run_du(entry)
            db.clear()
            db.update(dirstats)  # Save to DB
        else:
            dirstats = dict(db)  # Load existing data
    return dirstats

# Get disk usage information
def get_disk_stats():
    diskstats = {}
    for disk in sorted(ROOT_DIR.iterdir()):
        if disk.is_dir() and re.match(r"^disk[0-9]+$", disk.name):
            diskstats[disk.name] = get_fs_usage(str(disk))  # Store used space in bytes
    return diskstats

def get_disk_distance(diskstats):
    """Calculates how much each disk is above or below the average in bytes, but prints in TB for readability."""
    total_used = sum(diskstats.values())  # Ensure total is in bytes
    num_disks = len(diskstats)

    if num_disks == 0:
        raise ValueError("No valid disks found!")

    avg_used = total_used // num_disks  # Compute the average in bytes

    diskdistance = {}
    for disk in diskstats:
        used_bytes = diskstats[disk]  # Ensure this is in bytes
        diff_bytes = used_bytes - avg_used  # Ensure both values are in bytes

        diskdistance[disk] = {"diff": diff_bytes}

    return diskdistance

def calculate_moves(diskdistance, dirstats, min_move_size=1_000_000_000):
    """
    Selects best directories to move from overfilled disks to underfilled disks
    using a two-phase approach: 
      1. Major balancing (large directories)
      2. Refinement (smaller directories)
    """
    movelist = {}
    total_moved = 0

    # **PHASE 1: Move large directories first**
    while True:
        maxdisk = max(diskdistance, key=lambda d: diskdistance[d]["diff"])
        mindisk = min(diskdistance, key=lambda d: diskdistance[d]["diff"])

        maxdiff = diskdistance[maxdisk]["diff"]
        mindiff = diskdistance[mindisk]["diff"]

        # Stop if no valid move exists
        if maxdiff <= 0 or mindiff >= 0:
            break

        # Filter directories that belong to maxdisk, fit within mindisk's space, and meet min_move_size
        eligible_dirs = {size: path for path, size in dirstats.items() if maxdisk in path and size <= maxdiff and size >= min_move_size}

        if not eligible_dirs:
            break  # No more valid large moves

        # Pick the largest possible directory that fits
        best_size = max(eligible_dirs)
        best_dir = eligible_dirs[best_size]

        # Move it and update tracking
        movelist[best_size] = (best_dir, maxdisk, mindisk)
        diskdistance[maxdisk]["diff"] -= best_size
        diskdistance[mindisk]["diff"] += best_size
        total_moved += best_size

    return movelist, total_moved

### **Move Execution Using Rsync**
def rsync_move(source, destination, execute=False):
    """
    Uses rsync to move files/directories with checksum verification.
    
    - Expands wildcards using `glob.glob()` to prevent shell expansion issues.
    - Iterates over files and moves them individually.
    - Cleans up empty source directory after move.
    """
    source = Path(source)
    destination = Path(destination)

    if not source.exists():
        print(f"Skipping: Source not found {source}")
        return False

    # Expand source files using glob
    source_files = glob.glob(f"{source}/*")

    if not source_files:
        print(f"Skipping: No files to move in {source}")
        return False

    # Rsync each file separately
    for file in source_files:
        rsync_cmd = [
            "rsync",
            "-a",
            "--progress",
            "--remove-source-files" if execute else "--dry-run",
            file,
            str(destination),
        ]

        try:
            print(f"Running: {' '.join(rsync_cmd)}")
            result = subprocess.run(rsync_cmd, check=True, text=True)

            if result.returncode == 0:
                print(f"Moved: {file} → {destination}")
            else:
                print(f"Rsync failed: {result.stderr}")

        except subprocess.CalledProcessError as e:
            print(f"Rsync error: {e}")

    # Remove empty source directory
    if execute and not any(source.iterdir()):
        source.rmdir()

    return True

def rsync_move_old(source, destination, execute=False):
    """
    Uses rsync to move files/directories with checksum verification.
    """
    source = Path(source)
    destination = Path(destination)

    source_files = glob.glob(f"{source}/*")  # Expands to a list of files
    print(source_files)

    #print(f"source: {source}  dest: {destination}")
    exit()

    if not source.exists():
        print(f"Skipping: Source not found {source}")
        return False
    
    rsync_cmd = [
        "rsync", "-av", "--progress",
        "--remove-source-files" if execute else "--dry-run",
        str(source) + "/*", str(destination)
    ]

    print(f"Running: {' '.join(rsync_cmd)}")
    try:
        result = subprocess.run(rsync_cmd, check=True, text=True)

        if result.returncode == 0:
            if execute and source.is_dir():
                source.rmdir()  # Removes empty directories
            return True
        else:
            print(f"Rsync failed: {result.stderr}")
            return False

    except subprocess.CalledProcessError as e:
        print(f"Rsync error: {e}")
        return False

def move_data(movelist, diskstats, diskdistance, execute=False):
    # Moves selected directories from source to target using rsync.
    diskstats_after = diskstats.copy()  # Clone original disk usage for "After" values

    # this is the target for each drive... 
    avg_used = sum(diskstats.values()) // len(diskstats)

    # Apply moves to update "Used After"
    for size, (source_dir, source, target) in movelist.items():
        diskstats_after[source] -= size
        diskstats_after[target] += size  # Update disk usage after move

    # Compute the new average usage for Distance After calculation
    avg_used_after = sum(diskstats_after.values()) // len(diskstats_after)

    # Planned Moves Table
    table = Table(title="Planned Moves")
    table.add_column("Source Disk", justify="center")
    table.add_column("Target Disk", justify="center")
    table.add_column("Directory", overflow="fold", max_width=60)
    table.add_column("Size", justify="right")

    for size, (source_dir, source, target) in movelist.items():
        table.add_row(source, target, source_dir, datasize(size))

    console.print(table)

    # Disk Stats Before/After Table
    #stats_table = Table(title="Disk Usage Before/After Moves")
    stats_table = Table(title=f"Disk Usage Before/After Moves (Target: {datasize(avg_used)})")
    stats_table.add_column("Disk", justify="center")
    stats_table.add_column("Used Before", justify="right")
    stats_table.add_column("Distance Before", justify="right")
    stats_table.add_column("Used After", justify="right")
    stats_table.add_column("Distance After", justify="right")

    for disk in sorted(diskstats.keys()):
        used_before = diskstats[disk]
        used_after = diskstats_after[disk]
        avg_used_before = sum(diskstats.values()) // len(diskstats)
        diff_before = used_before - avg_used_before  # Distance Before
        diff_after = used_after - avg_used_after  # Corrected Distance After Calculation

        stats_table.add_row(
            disk,
            datasize(used_before),
            datasize(diff_before),
            datasize(used_after),
            datasize(diff_after),
        )

    console.print(stats_table)

    if execute:
        for size, (source_dir, source, target) in movelist.items():
            target_dir = source_dir.replace(f"/mnt/{source}", f"/mnt/{target}")
            rsync_move(source_dir, target_dir, execute=execute)


### **Main Execution Flow**
def main():
    sharestats = load_or_scan_shares()
    dirstats = load_or_scan_directories()
    diskstats = get_disk_stats()
    diskdistance = get_disk_distance(diskstats)

    movelist, movesum = calculate_moves(diskdistance, dirstats)

    move_data(movelist, diskstats, diskdistance, execute=args.execute)

if __name__ == "__main__":
    main()
