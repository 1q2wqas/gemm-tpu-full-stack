"""
Checks whether the LLM has signalled a termination of the EDA flow
Requirements:
- LLM response dictionary output

Steps:
- Accesses "termination_flow" variable outputted by LLM
- Evaluates and returns the state of this variable

Output:
- If "termination_flow" == True, then the agentic EDA flow is terminated by returning the "True" bool
- If "termination_flow" == False, then the agentic EDA flow continues by returning the "False" bool which re-running Openlane
"""

def get_termination_status(response_dict):

    updated_settings = response_dict["updated_settings"]
    terminate_flow = updated_settings["terminate_flow"]

    if terminate_flow == True:

        print("\nLLM has returned termination signal to end the agentic EDA flow. \nAll results saved and logged in memory.json\n")
        return True
    
    else:
        print("\Agentic EDA flow will now be reinitiated as the LLM has not returned the termination signal\n")
        return False
