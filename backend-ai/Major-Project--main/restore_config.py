import os

def find_backups():
    print(f"Searching in: {os.getcwd()}")
    found = False
    # Walk through all directories
    for root, dirs, files in os.walk("."):
        for file in files:
            if "backup_" in file or "config.json" in file:
                print(f"FOUND: {os.path.join(root, file)}")
                found = True
    
    if not found:
        print("Truly no backups or config files found in this directory tree.")

if __name__ == "__main__":
    find_backups()