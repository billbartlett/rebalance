# Unraid Share Rebalancer

This script balances data across Unraid disks by moving directories from overfilled disks to underfilled ones using `rsync`. It ensures all drives participate in balancing while maintaining a minimum move size of 1GB.

## Features
- **Automatic Disk Balancing**: Moves large directories first, followed by smaller refinements.
- **Uses Rsync for Reliability**: Supports `--dry-run` mode by default.
- **Database Caching**: Avoids unnecessary rescans with `shares.db` and `dirs.db`.
- **Progress Reporting**: Displays planned moves and disk usage before/after adjustments.

## Requirements
- pip install rich psutil

## Usage
```bash
python rebalance.py [--execute] [--rescan]
  --execute: Perform actual moves (defaults to displaying proposed moves).
  --rescan:  Rescan disk usage instead of using cached data.
