"""
Retreives metrics of the most recent Openlane run
Requirements:
- File path for the 'runs' directory
- Openlane flow success status
- Desirable metrics to be parsed to the LLM
- (ATM - violation criteria, but right now this does nothing and is probably handled by validator.py - CHECK THIS THEN SCHEDULE FOR REMOVAL)

Steps:
- Obtains performance metrics of the Openlane flow
- Runs

Output:
- Performance metrics parsed into the state builder
"""

import os, csv

# TO BE CALLED IN Main.py
def get_metrics_data(runs_direc_path, desired_metrics, flow_success):

    print("\n" + "=" * 60)
    print("PARSING FLOW METRICS")
    print("=" * 60)

    # If flow failed before completion, still attempt parsing
    if flow_success == False:
        print("Flow failed before completion - attempting metric parsing anyway")

    try:
        # Run each sub-function in order
        last_run_dir_path = get_last_run_directory_path(runs_direc_path)
        final_direc_path = get_final_direc_path(last_run_dir_path)
        metrics_csv_path = get_metrics_csv_path(final_direc_path)
        metrics_data_dict = make_metrics_data_dict(metrics_csv_path, desired_metrics)

        return metrics_data_dict

    except Exception as e:
        print(f"[Parser] Failed to parse metrics: {e}")
        return None


# =================================================================================
#   Sub-functions called in wrapper function:
# =================================================================================
def get_last_run_directory_path(runs_direc_path):

    # List all run directories from the current directory (this step is done to avoid listing any files)
    all_run_direcs = [direc for direc in os.listdir(runs_direc_path) if os.path.isdir(os.path.join(runs_direc_path, direc))]

    # Error handling
    if not all_run_direcs:
        raise FileNotFoundError("No previous run directories found in the specified path")

    # Arrange the run directories in order of creation time and get the most recent one's name
    last_run_direc_name = sorted(all_run_direcs)[-1]

    # Assertain full path for the most recent run directory
    last_run_dir_path = os.path.join(runs_direc_path, last_run_direc_name)

    print(last_run_dir_path) # debugging // to be deleted
    
    return last_run_dir_path


def get_final_direc_path(last_run_dir_path):
    # Search the most recent run directory and get the path name for the directory named final (if present)
    if 'final' in os.listdir(last_run_dir_path):
        final_direc_path = os.path.join(last_run_dir_path, 'final')
        print("Final directory path:", final_direc_path) # debugging // to be deleted
        return final_direc_path

    # Error handling
    raise FileNotFoundError("Directory: 'final' - not found")


def get_metrics_csv_path(final_direc_path):

    # List all files in the final directory
    files = os.listdir(final_direc_path)

    # Search the 'final' run directory and get the path name for metrics.csv (if present)
    if 'metrics.csv' in files:
        metrics_csv_path = os.path.join(final_direc_path, 'metrics.csv')
        print("Metrics CSV path:", metrics_csv_path) # debugging // to be deleted
        return metrics_csv_path

    # Error handling
    raise FileNotFoundError("File: 'metrics.csv' - not found")


def make_metrics_data_dict(metrics_csv_path, desired_metrics):

    metrics_data_dict = {}

    with open(metrics_csv_path, 'r') as csvfile:
        datareader = csv.reader(csvfile)

        for row in datareader:


            # Appends all metric data to a data dictionary
            if row[0] in desired_metrics:
                metrics_data_dict[row[0]] = row[1]
    
        print(metrics_data_dict) # debugging // to be deleted

        return metrics_data_dict

