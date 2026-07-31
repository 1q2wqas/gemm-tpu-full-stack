"""
Initialises OpenlaneFlow
Requirements:
- Root folder path of the nix flake (found in folder: openlane 2)
- File path for the design's configuration path

Steps:
- Begins a new thread and initiates a timer to run in this thread (allowing it to run in parallel to the main Openlane thread)
- Runs Openlane in a nix shell through CLI
- Automatically closes the nix shell and returns to virtual environment
- Plays a notification sound once the Openlane flow is terminated

Output:
- Openlane flow performance metrics saved locally
- Openlane terminal output stored for downstream processing
UPDATE ALL
"""

import subprocess, time, threading, sys


# TO BE CALLED IN Main.py
def run_openlane_flow(nix_flake_root_folder_path, config_path, openlane_timeout_duration, notification_sound_path):

    print("\n" + "=" * 60) # debugging / TO BE DELETED
    print("RUNNING OPENLANE") # debugging / TO BE DELETED
    print("=" * 60) # debugging / TO BE DELETED
    print("Attempting to run Openlane in Nix shell...") # debugging / TO BE DELETED

    stop_event, timer_thread = initialise_stopwatch(openlane_timeout_duration)
    result = run_openlane_in_nix(nix_flake_root_folder_path, config_path, openlane_timeout_duration, stop_event, timer_thread)
    notification_sound(notification_sound_path)
    
    return result

# =================================================================================
#   Sub-functions called in wrapper function:
# =================================================================================

def notification_sound(notification_sound_path):
    subprocess.Popen(["afplay", notification_sound_path])


def openlane_flow_timer(start_time, stop_event, openlane_timeout_duration):
    while not stop_event.is_set():
        elapsed = int(time.time() - start_time)

        mins = (elapsed % 3600) // 60
        secs = elapsed % 60
        timeout = openlane_timeout_duration / 60
        
        sys.stdout.write(f"\rOpenlane Run-Time Elapsed: {mins:02d}:{secs:02d} - Timeout duration: {timeout:.0f} mins ")
        sys.stdout.flush()

        time.sleep(1)

    print()


def initialise_stopwatch(openlane_timeout_duration):
    
    # Record time and making a seperate thread that starts and runs a timer
    start_time = time.time()
    stop_event = threading.Event()
    openlane_timeout_duration = openlane_timeout_duration

    timer_thread = threading.Thread(
        target=openlane_flow_timer,
        args=(start_time, stop_event, openlane_timeout_duration),
        daemon=True
    )
    
    timer_thread.start()

    return stop_event, timer_thread


def run_openlane_in_nix(nix_flake_root_folder_path, config_path, openlane_timeout_duration, stop_event, timer_thread):

    try:
        result = subprocess.run(
            ["nix", "develop", nix_flake_root_folder_path, "--command", "openlane", config_path],
            capture_output=True,
            text=True,
            timeout=openlane_timeout_duration
        )

        return {
            "stdout": str(result.stdout),
            "stderr": str(result.stderr),
            "returncode": str(result.returncode),
            "timeout": False
        }
    
    except subprocess.TimeoutExpired as e:
        
        print("Timeout occurred! Run time exceeded " f"{openlane_timeout_duration} seconds") # debugging / TO BE DELETED

        stdout = e.stdout or ""
        stderr = e.stderr or ""
        
        return {
            "stdout": stdout.decode("utf-8"),
            "stderr": stderr.decode("utf-8"),
            "returncode": None,
            "timeout": True
        }
    
    finally:
        # Stop timer and rejoin threads
        stop_event.set()
        timer_thread.join()
        
