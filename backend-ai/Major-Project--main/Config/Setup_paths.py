"""
Initialises OpenlaneFlow
Requirements:
- Design name configured correctly in Settings.py

Steps:
- Configures root folders accoriding to the host machine's architecture
- Assigns the exact path files

Output:
- Path files to be called in Main.py in string format
- Code consequently allows everyone to run the code without having to tamper with file paths
- Ensures all path files in host machine are in the equivalent location to these Mac file paths below:
    runs_path = "/Users/maximobratchell/openlane2/my_designs/pm32/runs"
    config_path = "/Users/maximobratchell/openlane2/my_designs/pm32/config.json"
    save_path = "/Users/maximobratchell/Major-Project-/memory.json"
    prompt_path = "/Users/maximobratchell/Major-Project-/prompt.json"
    notification_sound_path = "/Users/maximobratchell/Major-Project-/flow_end_notification.mp3"
    nix_flake_root_folder_path = "/Users/maximobratchell/openlane2"
"""

from pathlib import Path

# TO BE CALLED IN Main.py
def configure_paths(design_name_str):

    Major_Project_path = Path(__file__).resolve().parents[1]
    Home_path = Path.home()
    Openlane2_path = Home_path / "openlane2"
    obj_runs_path = Openlane2_path / "my_designs" / design_name_str / "runs"
    obj_config_path = Openlane2_path / "my_designs" / design_name_str / "config.json"
    obj_save_path = Major_Project_path / "memory.json"
    obj_prompt_path = Major_Project_path / "prompt.json"
    obj_notification_sound_path = Major_Project_path / "flow_end_notification.mp3"
    obj_nix_flake_root_folder_path = Openlane2_path

    runs_path = str(obj_runs_path)
    config_path = str(obj_config_path)
    save_path = str(obj_save_path)
    prompt_path = str(obj_prompt_path)
    notification_sound_path = str(obj_notification_sound_path)
    nix_flake_root_folder_path = str(obj_nix_flake_root_folder_path)

    return runs_path, config_path, save_path, prompt_path, notification_sound_path, nix_flake_root_folder_path
