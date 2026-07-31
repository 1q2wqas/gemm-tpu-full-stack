"""
Checks whether the LLM has signalled a termination of the EDA flow
Requirements:
- LLM response dictionary output
- Length of time before the Openlane flow is terminated through a timeout sequence

Steps:
- Checks all major sign-off criteria have been passed and returns a dictionary of failed criteria (if any)
- Errors cstegorised into: regular failure, timeout failure or none

Output:
- A dictionary containing all needed error information
"""
# WRAPPER FUNCTION - TO BE CALLED IN Main.py
def process_errors(result, openlane_timeout_duration):

    check_dict = check_openlane_success(result["stdout"])
    flow_success, error_message, error_list = error_handling(result, check_dict, openlane_timeout_duration)
    error_summary = error_processing(flow_success, error_message, error_list)

    return flow_success, error_message, error_list, error_summary

# =================================================================================
#   Sub-functions called in wrapper function:
# =================================================================================

def check_openlane_success(stdout):

    tail = "\n".join(stdout.splitlines()[-500:])  # searching last 500 lines

    # Main sign-off criteria
    antenna_pass_status = "* Antenna\nPassed" in tail
    lvs_pass_status = "* LVS\nPassed" in tail
    drc_pass_status = "* DRC\nPassed" in tail

    # Timing sign-off criteria
    if "Setup violations found" in tail: 
        setup_pass_status = False 
    else:
        setup_pass_status = True
    if "Hold violations found" in tail: 
        hold_pass_status = False 
    else:
        hold_pass_status = True
    if "Max Slew violations found" in tail: 
        slew_pass_status = False 
    else:
        slew_pass_status = True  
    if "Max Cap violations found" in tail: 
        cap_pass_status = False 
    else:
        cap_pass_status = True  


    check_dict = {
        "antenna_check": antenna_pass_status,
        "lvs_check": lvs_pass_status,
        "drc_check": drc_pass_status,
        "setup_check": setup_pass_status,
        "hold_check": hold_pass_status,
        "slew_check": slew_pass_status,
        "cap_check": cap_pass_status
    }

    return check_dict

def error_handling(result, check_dict, openlane_timeout_duration):
    
    print("\n" + "=" * 60) # debugging / TO BE DELETED
    print("ERROR PROCESSING") # debugging / TO BE DELETED
    print("=" * 60) # debugging / TO BE DELETED

    if result["timeout"] == True:
        flow_success = False

        error_lines = result["stdout"].splitlines()
        last_lines = "\n".join(error_lines[-100:])

        error_message = (
            "Openlane flow timeout failure; flow execution exceeded the time limit of "
            f"{openlane_timeout_duration / 60} minutes. Please amend the config.json parameters.\n"
            "The last 100 lines captured before timeout:\n" + last_lines
        )
        error_list = None
        print("Error message:", error_message) # debugging / TO BE DELETED

        return flow_success, error_list, error_message

    failure_list = []

    for key in check_dict:
        if check_dict[key] == False:
            failure_list.append(key)

    if not failure_list:
        
        flow_success = True
        error_message = None
        error_list = []
        print("Successful Openlane flow!") # debugging / TO BE DELETED

    else:

        flow_success = False

        error_lines = result["stdout"].splitlines()
        last_lines = "\n".join(error_lines[-100:])

        error_message = (
            "Regular Openlane flow failure; ammend the config.json file parameters.\n"
            "Openlane flow failed with the following error message(s):\n" + last_lines
        )
        error_list = failure_list
        print("Error message:", error_message) # debugging / TO BE DELETED


    return flow_success, error_list, error_message

def error_processing(flow_success, error_message, error_list):

    if not flow_success:
        error_summary = {
            "failed_checks": error_list,
            "error_type": "signoff" if error_list else "timeout",
            "recoverable": True,
            "message": error_message,
        }
    else:
        error_summary = {
            "failed_checks": [],
            "error_type": None,
            "recoverable": False,
            "message": None,
        }

    return error_summary