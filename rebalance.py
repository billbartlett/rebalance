#!/usr/bin/python3
import os
import re
import psutil
import pprint
from math import log2

"""
Hopefully, eventually, this will be a tool I can use to balance unraid shares. The idea is that when adding new drives, most new data is going to be exclusively written to the new drives unless some sort of balancing is done.  This is my attempt to write my own utility to do said balancing.
"""

### start functions
def find_disks(depth):
    """
    which disks are available to unraid.  to start, this is going to be janky and simply use /mnt/ with a max depth of 1, and match disk*
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
    this is pretty janky, again, but simply grab the list of directories under /mnt/user0, an an unraid-specific shortcut to access shares
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
                    # extract share name utilizing the grouping regex and remove single quotes
                    share_name = sharematch.group(1)
                    share_name = str(share_name.replace("'",""))
                    shares.append(share_name)
    shares.sort()
    return(shares)

def get_dirs(basedir):
    """
    build a list of all subdirectories in all shares, with a depth limit of 1

    depth is a method to limit how far down the directory structure the code will look.  I'm only interested in 1 level after the share name:
        /mnt/disk1/movies/this_directory_is_calculated

    since dirname will be /mnt/[disk_name]/[share_name] I only want to go one level deeper.  set depth as 2, and the first iteration will lower it to 1, and the code will stop once depth is not > 0.
    """

    # os.scandir() will encapsulate the directory name in single quotes
    # -- just kidding.  if there is a single quote in the directory name, it will be encapsulated in double quotes.
    #pattern = "'(.*)'"
    pattern = "['|\"](.*)['|\"]"
    depth = 3
    # does the directory exist?
    isDirectory = os.path.isdir(dirname)
    if isDirectory:
        with os.scandir(dirname) as p:
            depth -= 1
            for entry in p:
                # no symlinks
                if not os.path.islink(entry):
                    if entry.is_dir() and depth > 0:
                        dirmatch = re.search(pattern, str(entry))
                        if dirmatch:
                            # extract directory name utilizing the grouping regex
                            matched_dir = dirmatch.group(1)
                            full_dir_name = dirname + "/" + matched_dir

                            # append directory to dirlist
                            dirlist.append(full_dir_name)

                            # populate dirstats dictionary with directory size information
                            dirsize = get_tree_size(full_dir_name)
                            dirstats[full_dir_name] = dirsize

def get_tree_size(path):
    # total size of files in given path and subdirs.
    total = 0
    for entry in os.scandir(path):
        if entry.is_dir(follow_symlinks=False):
            total += get_tree_size(entry.path)
        else :
            total += entry.stat(follow_symlinks=False).st_size
    return total


def disk_used(disk):
    mount = "/mnt/" + disk
    usage = psutil.disk_usage(mount)
    used = usage.used
    diskstats[disk] = used

def average_disk(diskstats):
    # input should be the diskstats dictionary
    count = 0
    totalused = 0
    for disk, used in diskstats.items():
        count += 1
        totalused += used
    avgused = int(totalused/count)
    return(avgused)

def disk_distance(avg):
    """
    calculate the "distance" (of data) that the drive is from the target average
    example:  average usage is 2.5TB, and a disk has 4TB stored.  the distance is -1.5TB
    a negative distance indicates data needs to move off of the drive to bring it closer to the target average
    """
    for disk, used in diskstats.items():
        diskdistance[disk] = {}
        #print(type(disk))
        #print("disk: " + disk)
        #print("used: " + str(used))
        if avg > used:
            diff = int(avg - used)
            hdiff = str(datasize(diff))
            diskdistance[disk] = {'diff': diff, 'mover': 'target', 'hdiff': hdiff}
        if used > avg:
            diff = -1*(int(used - avg))
            hdiff = datasize(abs(diff))
            hdiff = "-" + str(hdiff)
            diskdistance[disk] = {'diff': diff, 'mover': 'source', 'hdiff': hdiff}

def datasize(num):
    # "human readable" formatting
    step_unit = 1024.0

    for x in ['bytes', 'KB', 'MB', 'GB', 'TB']:
        if num < step_unit:
            return "%3.1f %s" % (num, x)
        num /= step_unit

def calculate_moves(diskdistance):
    """
    import diskdistance (dictionary on which drives need to gain or lose data)
    start with smallest number (largest excess data) and largest number (needs most data)
    find the difference of the pair, and then traverse sharestats dictionary to find
    the closest match in data volume to move from source to target.
    """


### end functions

# define lists/dictionaries that will be used
disklist = []
sharelist = []
dirlist = []
dirstats = {}
sharestats = {}
diskstats = {}
diskdistance = {}
movertype = []

# find the disks and shares
disklist = find_disks(2)
sharelist = get_shares(2)

# first populate sharestats{} with disk usage information, per-share.
# then, find the top level directories for each share, on each disk
for sharename in sharelist:
    sharedir = "/mnt/user0/" + sharename
    shareusage = get_tree_size(sharedir)
    sharestats[sharedir] = shareusage

    for diskname in disklist:
        dirname = "/mnt/" + diskname + "/" + sharename
        disk_used(diskname)
        get_dirs(dirname)

"""
By the time the code gets here, we have established all of the data that we need to figure out what should be done.

    * list of all physical drives (sketchy code, but it's functional)
    * list of all shares on the array
    * list of all top level directories in each share  (/mnt/disk?/$share_name/$TLD)
    * disk usage for:
        * every physical drive (free space and percent free)
        * overall share disk usage
        * every TLD under every share, on every drive

Now, how to recommend what should be moved?  Good question.....
"""

# start with average size of data used.
# this will be the approximate target for each drive.
avg_disk_used = average_disk(diskstats)

# calculate amount of data each drive needs to gain or lose to get close to the target
disk_distance(avg_disk_used)


#pprint.pprint(diskstats)
#print("Avg: " + "| " + str(avg_disk_used) + " | " + str(datasize(avg_disk_used)))
#pprint.pprint(diskdistance)










