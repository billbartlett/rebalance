#!/usr/bin/env python3
import os,re

def find_disks(rootdir,depth):
    """
    which disks are available to unraid.  to start, this is going to be janky
    and simply use /mnt/ with a max depth of 1, and match disk*
    """
    depth -= 1
    print(rootdir + "abcd")
    regex = re.compile('disk*')
    with os.scandir(rootdir) as p:
        for entry in p:
            yield entry.path
            if entry.is_dir() and depth > 0:
                if regex.match(entry):
                    print(entry)


rootdir = "/mnt/"
find_disks(rootdir, 2)
