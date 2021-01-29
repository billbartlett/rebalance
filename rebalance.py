#!/usr/bin/python3
import os,re

"""
which disks are available to unraid.  to start, this is going to be janky
and simply use /mnt/ with a max depth of 1, and match disk*
"""

def find_disks(rootdir, depth):
    disks = []
    pattern = "(disk[0-9])"
    with os.scandir(rootdir) as p:
        depth -= 1
        for entry in p:
            #yield entry.path
            if entry.is_dir() and depth > 0:
                diskmatch = re.search(pattern, str(entry))
                if diskmatch:
                    # <DirEntry 'disk8'>
                    # extract disk name from string similar to above utilizing the grouping from pattern string
                    disk_name = diskmatch.group(1)
                    disks.append(disk_name)
    return(disks)

rootdir = "/mnt/"
disklist = find_disks(rootdir, 2)

print("-----------")
for x in disklist:
    print(x)
