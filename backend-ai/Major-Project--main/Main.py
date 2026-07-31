"""
(As of right now)
Runs Main Section of Flow
Requirements:
- File paths to be configured in the same manner as documented in Setup_paths.py
- API key configured to a local location in the host's machine that can be directy accessed with "os.getenv("OPENAI_API_KEY")"
- Virtual environment activated prior to running Main.py in CLI

Steps:
- Import all required global functions and variables
- Initiate while loop which continually runs Openlane and calls the LLM
- Agentic flow is terminated by the LLM by continually screening for a termination signal

Output:
- All results in JSON format - ready for graphing code to be run
"""

import os
from Flow.Terminator import get_termination_status
from Config.Setup_paths import configure_paths
from Flow.Runner import run_openlane_flow
from Flow.Parser import get_metrics_data
from Flow.Errors import process_errors
from Agent.State_builder import StateBuilder
from Agent.Memory import Memory
from Agent.Decision_engine import build_and_save_prompt
from Agent.Call_API import execute_API_call
from Config.Settings import design_name_str, openlane_timeout_duration, desired_metrics, ConfigChanges, reasoning_dict, input_USD_Mtok, cache_hit_input_USD_Mtok, output_USD_Mtok
from Config.Schema import build_schema
from Governance.API_cost import get_API_call_cost_USD, log_API_call_cost
from Actions.Executor import execute_validated_info


# Configure file paths relative to the machine thats executing this code
runs_path, config_path, save_path, prompt_path, notification_sound_path, nix_flake_root_folder_path = configure_paths(design_name_str)

# Initiate automated Openlane-LLM flow initialise flow variables
count = 1
TERMINATION_STATUS = False

print("\n" + "=" * 60) # debugging / TO BE DELETED
print("STARTING AGENTIC OPENLANE-LLM FLOW") # debugging / TO BE DELETED
print("=" * 60) # debugging / TO BE DELETED


while TERMINATION_STATUS == False:

    print(f"Agentic Openlane-LLM flow starting.\n Iteration: {count}") # debugging / TO BE DELETED
    count += 1

    # ================================================================
    # Run main OpenLane-LLM flow
    # ================================================================

    # Step 1: Create instances, initiate classes and access design-specific parameters for the rest of the flow
    builder = StateBuilder()
    memory = Memory(save_path)
    output_schema, DESIGN_NAME_verified = build_schema(ConfigChanges, config_path)

    # Step 2: Run Openlane within a nix shell
    result = run_openlane_flow(nix_flake_root_folder_path, config_path, openlane_timeout_duration, notification_sound_path)

    # Step 3: Check for Openlane flow error - to be inputted into the prompt.json
    flow_success, error_list, error_message, error_summary = process_errors(result, openlane_timeout_duration)

    # Step 4: Parse metrics from Openlane flow
    raw_metrics = get_metrics_data(runs_path, desired_metrics, flow_success)

    # Step 5: Build state
    state = builder.build_state(
        raw_metrics=raw_metrics,
        runs_path=runs_path,
        design_name=DESIGN_NAME_verified,
        config_path=config_path,
        flow_success=flow_success,
        error_summary=error_summary,
        desired_metrics=desired_metrics,
        previous_state=memory.get_previous_state(),
    )

    # Step 6: Store into memory
    result = memory.process_state(state)
    memory.print_summary(result["memory_summary"])
    print(f"Plateau: {result['plateau']}")

    # Step 7: Build and save LLM prompt
    build_and_save_prompt(
        config_path=config_path,
        memory_path=save_path,
        design_name=DESIGN_NAME_verified,
    )
    builder.print_state(result["state"])

    # Step 8: Send prompt to API (followed by printing the response and loading all results)
    response, response_dict = execute_API_call(prompt_path, output_schema, reasoning_dict)

    # Step 9: Validate LLM response and update config.json file if safety-conditions are satisfied
    executor_result = execute_validated_info(
        config_path=config_path,
        response_dict=response_dict,
        apply_on_warnings=True,
        memory=memory,
        run_id=state["run_id"],
    )

    if executor_result["validation_status"] == "valid":
        pass
    elif executor_result["validation_status"] == "valid_with_warnings":
        pass
    elif executor_result["validation_status"] == "invalid":
        pass

    # Step 10: Calculate API call cost
    API_call_cost_USD = get_API_call_cost_USD(response, input_USD_Mtok, cache_hit_input_USD_Mtok, output_USD_Mtok)

    # Step 11: Store API call cost to memory
    costs_path = os.path.join(os.path.dirname(save_path), "api_costs.json")
    run_id = sorted(d for d in os.listdir(runs_path) if os.path.isdir(os.path.join(runs_path, d)))[-1]
    log_API_call_cost(response, costs_path, run_id, input_USD_Mtok, cache_hit_input_USD_Mtok, output_USD_Mtok)


    TERMINATION_STATUS = get_termination_status(response_dict)
    if count == 100:
        TERMINATION_STATUS = True


"""
END OF CODE

- This code will be called repetitively in Main.py
- Main.py will handle termination logic, only terminating when the LLM outputs a specific set of boolean logic
- Graphing code to be written once results are collected and stored to memory
"""



