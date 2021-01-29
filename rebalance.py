#!/usr/bin/python3
import os,re

"""
Hopefully, eventually, this will be a tool I can use to balance unraid shares.  
The idea is that when adding new drives, most new data is going to be exclusively 
written to the new drives unless some sort of balancing is done.  This is my 
attempt to write my own utility to do said balancing.
"""

disklist = []
sharelist = []

def find_disks(depth):
    """
    which disks are available to unraid.  to start, this is going to be janky
    and simply use /mnt/ with a max depth of 1, and match disk*
    """
    rootdir = "/mnt"
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
                    disk_name = str(diskmatch.group(1))
                    disks.append(disk_name)
    disks.sort()
    return(disks)

def get_shares(depth):
    """
    this is pretty janky, again, but simply grab the list of directories under /mnt/user0, an
    an unraid-specific shortcut to access shares
    """
    rootdir = "/mnt/user0/"
    shares = []
    pattern = "('\w+')"
    with os.scandir(rootdir) as p:
        depth -= 1
        for entry in p:
            #yield entry.path
            if entry.is_dir() and depth > 0:
                sharematch = re.search(pattern, str(entry))
                if sharematch:
                    # extract share name utilizing the grouping from pattern string, and remove single quotes
                    share_name = sharematch.group(1)
                    share_name = str(share_name.replace("'",""))
                    shares.append(share_name)
    shares.sort()
    return(shares)




disklist = find_disks(2)
sharelist = get_shares(2)





#for x in disklist:
#    print(x)
#
#for x in sharelist:
#    print(x)


