#!/usr/bin/python3
import os, re, shutil
import psutil, pprint, shelve
import itertools
from math import log2

# utilizing rich for prettier text output
from rich import print
from rich.console import Console
import logging
from rich.logging import RichHandler
console = Console()
log = logging.getLogger("rich")

FORMAT = "%(message)s"
logging.basicConfig(
    level="NOTSET", format=FORMAT, datefmt="[%X]", handlers=[RichHandler()]
)


"""
Hopefully, eventually, this will be a tool I can use to balance unraid shares. The idea
is that when adding new drives, most new data is going to be exclusively written to the
new drives unless some sort of balancing is done.  This is my attempt to write my own
utility to do said balancing.
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

    depth is a method to limit how far down the directory structure the code will look.
    I'm only interested in 1 level after the share name:
        /mnt/disk1/movies/this_directory_is_calculated

    since dirname will be /mnt/[disk_name]/[share_name] I only want to go one level
    deeper.  set depth as 2, and the first iteration will lower it to 1, and the code
    will stop once depth is not > 0.

    os.scandir() will encapsulate the directory name in single quotes
      -- just kidding.  if there is a single quote in the directory name, it will be
     encapsulated in double quotes.
    """
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
    a negative distance indicates data needs to move off of the drive to bring it closer
    to the target average
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
    start with smallest number (largest excess data) and largest number (needs most data)
    find the difference of the pair, and then traverse diskdistance dictionary to find
    the closest match in data volume to move from source to target.
    """
    # maxdisk = needs most data, mindisk = needs to lose the most data
    maxdisk = max(int(diff['diff']) for diff in diskdistance.values())
    mindisk = min(int(diff['diff']) for diff in diskdistance.values())
    #diskdiff = int((abs(mindisk) - maxdisk))
    #print("max: %d | min: %d | diff: %d" % (maxdisk, abs(mindisk), diskdiff))

    # perform this loop until mindisk and maxdisk are within 50gb.
    # For the sake of this exercise, that will suffice as "balanced"
    #while diskdiff > 53687063712:
    scansizes = []
    matched_dirs = {}
    move_list = {}
    tuplesum = 0
    # can mindisk supply enough data by itself to bring maxdisk to average,
    # without falling below average itself:
    if abs(mindisk) > maxdisk:
        # yes?  then figure out what to move
        # at this point, all we have is the bytecount for mindisk and maxdisk.
        # determine which drives those belong to
        for disk,info in diskdistance.items():
            if info['diff'] == maxdisk:
                maxdrive = disk
            if info['diff'] == mindisk:
                mindrive = disk
        # find list of file sizes that reside on mindisk, and append to a list.
        # also create a dictionary of matched directories and corresponding sizes
        for filedir, dirsize in dirstats.items():
            matchdir = re.search(mindrive, filedir)
            if matchdir:
                if dirsize == 0:
                    continue
                scansizes.append(dirsize)
                matched_dirs[dirsize] = filedir
        #sort the directory sizes largest to smallest.
        scansizes.sort(reverse=True)

        """
        itertools.combinations will provide an exhaustive list of all possible
        combinations.  When dealing with hundreds of different directory sizes, the
        numbers start to get very large, very fast.
          for example: with 400+ directories, even showing only 4 subsequences of
          those 400+, I was in the tens of millions of combinations/calculations.
          (take these 400+ numbers, and show me all the combinations of four of them)

        to combat that, I have sorted the directory sizes in decending order.
        that helps because we know the very first list of numbers returned from
        itertools is going to be the first N numbers in the list, and thus will be
        the highest possible combination of numbers at that subsequence check.  we
        can skip literally billions of calculations by simply checking if those
        first N numbers are larger than our target tolerance.  If they aren't, go to
        the next iteration.
        """
        # maximum directory combinations to test.
        max_dirs = 50

        # tolerance is how close the total needs to be to the target in order
        # to move forward.  between 90% and 105% of the target seems reasonable.
        tolerance_low = int((.9 * maxdisk))
        tolerance_high = int((1.05 * maxdisk))

        counter = 0
        for i in range(1,max_dirs):
            # tt is a temp variable to store the first list of numbers returned.
            tt = list(itertools.islice(itertools.combinations(scansizes,i), 1))

            # since itertools returns a list of tuples, we have to first take the
            # tuple out of a list, and then sum it.  probably cleaner ways to do this
            for tuplemath in tt:
                tuplesum = int(sum(list(tuplemath)))

            # check tuplesum against our tolerance
            if tuplesum < tolerance_low:
                #print("%d: nope: %d vs low tolerance (%d)" % (i, tuplesum, tolerance_low))
                continue
            else:
                # now we have a list of filesizes that match our minimum.
                # check to make sure the list is within maximum tolerance
                if tuplesum < tolerance_high:
                    # earlier created matched_dirs will make it 'easy' to find the
                    # directories that need moved.
                    # first go through directory sizes from the list tuplemath above
                    for dirsize in tuplemath:
                        # search through matched_dirs for corresponding size, and
                        # append to a new dictionary:  move_list
                        for mdirsize,mdir in matched_dirs.items():
                            if mdirsize == dirsize:
                                #move_list.append(mdir)
                                move_list[dirsize] = mdir
                break
        return tuplesum, move_list, maxdrive, mindrive
        #diskdiff = 1

def check_md5(source_dir, target_dir):
    # traverse a directory of files


def move_data(move_list, source, target):
    # function to move the data (move_list) from source to target

    # iterate through move_list to find the share names.  we need to verify that
    # the source share /mnt/disk?/SHARE_NAME exists on the target
    for size, source_dir in move_list.items():
        # regex to match share name and directory to move
        sharematch = re.search(r"\/mnt/" + source + "\/(.*)\/(.*)", source_dir)
        if sharematch:
            sharename = sharematch.group(1)
            movedir = sharematch.group(2)
            # test to see if directory exists on target
            target_prefix = "/mnt/" + target + "/"
            target_share_dir = target_prefix + sharename
            target_dir = target_share_dir + "/" + movedir
            if os.path.isdir(target_share_dir):
                #print("source: %s | target: %s" % (source_dir, target_dir))
                # the time has come to move some files.
                # I've chosen to copy so that I can verify md5sums before deleting
                print("copying %s to %s" % (source_dir, target_dir))
                #shutil.copytree(source_dir, target_dir)
                # verify files match
                check_md5(source_dir, target_dir)
                continue
            else:
                log.fatal("NOT FOUND: %s" % target_share_dir)
                # target directory doesn't exist.  try to create it.
                try:
                    os.mkdir(target_share_dir)
                    print("mv %s %s" % (source_dir, target_dir))
                except OSError as error:
                    log.fatal(error)
                    break
        else:
            # if we don't get a share match.  something is wrong, though I don't
            # really know what it would be.
            log.fatal("No share matched.  Something is fishy.")
            break





### end functions

# define lists/dictionaries that will be used
disklist = []
sharelist = []
dirlist = []
#dirstats = {}
dirstats = shelve.open('dirs.db')
#sharestats = {}
#sharestats = shelve.open('shares.db')
diskstats = {}
diskdistance = {}
movertype = []

# find the disks and shares
disklist = find_disks(2)
sharelist = get_shares(2)

# first populate sharestats{} with disk usage information, per-share.
# then, find the top level directories for each share, on each disk
for sharename in sharelist:
    #    sharedir = "/mnt/user0/" + sharename
    #    shareusage = get_tree_size(sharedir)
    #    sharestats[sharedir] = shareusage
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
"""

# start with average size of data used.
# this will be the approximate target for each drive.
avg_disk_used = average_disk(diskstats)
# calculate amount of data each drive needs to gain or lose to get close to the target
disk_distance(avg_disk_used)
movesum, movelist, maxdrive, mindrive = calculate_moves(diskdistance)
move_data(movelist, mindrive, maxdrive)

#print("Moving (%s): from %s to %s" % (datasize(movesum), mindrive, maxdrive))
#print(movelist)
#console.log("All local variables", log_locals=True)
#pprint.pprint(movelist)
#print("------- Disk Stats ----------")
#pprint.pprint(diskstats)
#print("------- Share Stats ----------")
#pprint.pprint(sharestats)
#print("------- Distance ----------")
#pprint.pprint(diskdistance)
#print("Avg: " + "| " + str(avg_disk_used) + " | " + str(datasize(avg_disk_used)))

dirstats.close()
#sharestats.close()





