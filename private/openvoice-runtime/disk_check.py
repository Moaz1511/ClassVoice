import shutil

for drive in ("C:\\", "E:\\"):
    usage = shutil.disk_usage(drive)
    print(drive, "free_bytes", usage.free, "total_bytes", usage.total)
