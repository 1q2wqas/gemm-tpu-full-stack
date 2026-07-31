import json, os, copy
# from datetime import datetime
from Actions.Validator import Validator
from Agent.Decision_engine import update_best_run_from_llm

# code that creates backup config.json uncommented by Maximo

def apply_config_changes(config_path, approved_changes):
    """
    Applies approved parameter changes to config.json.

    Args:
        config_path (str): path to config.json
        approved_changes (dict): validated parameter changes

    Returns:
        dict
    """

    if not approved_changes:
        print("Executor: No changes to apply.")
        return {
            "success": False,
            "updated_config": None,
            "original_config": None,
            "changes_applied": {},
            # "backup_path": None,
        }

    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path, "r") as f:
        config = json.load(f)

    original_config = copy.deepcopy(config)

    # timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # backup_path = f"{config_path}.backup_{timestamp}"
    
    # shutil.copy(config_path, backup_path)

    # print(f"Executor: Backup created at {backup_path}")

    changes_applied = {}

    for param, new_value in approved_changes.items():
        old_value = config.get(param, None)
        config[param] = new_value
        changes_applied[param] = {
            "old": old_value,
            "new": new_value
        }

    try:
        with open(config_path, "w") as f:
            json.dump(config, f, indent=4)
    except OSError as e:
        # shutil.copy(backup_path, config_path)
        raise RuntimeError(f"Unable to write config file: {config_path}") from e
    except TypeError as e:
        raise RuntimeError("Configuration contains invalid JSON values.") from e

    print("Executor: Config updated successfully.")
    print("\n===== CONFIG CHANGES =====")
    for param, change in changes_applied.items():
        print(f"{param}: {change['old']} → {change['new']}")

    return {
        "success": True,
        "updated_config": config,
        "original_config": original_config,
        "changes_applied": changes_applied,
        # "backup_path": backup_path,
    }

def execute_validated_info(config_path, response_dict, apply_on_warnings=True, memory=None, run_id=None):
    """
    Validates LLM-suggested config changes and applies them if allowed

    Three possible outcomes:
    1. Valid with no warnings  -> apply changes
    2. Invalid with errors     -> do not apply
    3. Valid with warnings     -> apply if apply_on_warnings=True, else skip
    
    Args:
    config_path (str): path to config.json
        response_dict (dict): LLM-suggested config patch
        apply_on_warnings (bool): whether to apply changes when warnings exist

    Returns:
        dict: execution summary
    """

    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path, "r") as f:
        baseline_config = json.load(f)

    validator = Validator()
    validation_result = validator.validate_llm_response(response_dict, baseline_config)

    # Update best run based on LLM judgement (only updates if is_best_run=True)
    if memory is not None and run_id is not None:
        update_best_run_from_llm(validation_result, memory)

    errors = getattr(validation_result, "errors", [])
    warnings = getattr(validation_result, "warnings", [])
    normalised_patch = getattr(validation_result, "normalised_patch", {})

    # Case 1 and 3: valid
    if validation_result.valid:
        if warnings:
            print("Validation status: VALID WITH WARNINGS")
            print("Warnings:")
            for warn in warnings:
                print(f"- {warn.code}: {warn.message}")

            if not apply_on_warnings:
                print("\nExecutor: Changes NOT applied because warnings require reconsideration.")
                return {
                    "success": False,
                    "validation_status": "valid_with_warnings",
                    "errors": [],
                    "warnings": [
                        {"code": w.code, "message": w.message} for w in warnings
                    ],
                    "changes_applied": {},
                    "execution_result": None,
                }
            
            print("\nExecutor: Proceeding despite warnings...")
            exec_result = apply_config_changes(config_path, normalised_patch)

            return {
                "success": exec_result["success"],
                "validation_status": "valid_with_warnings",
                "errors": [],
                "warnings": [
                    {"code": w.code, "message": w.message} for w in warnings
                ],
                "changes_applied": exec_result["changes_applied"],
                "execution_result": exec_result,
            }

        else:
            print("Validation status: VALID")
            exec_result = apply_config_changes(config_path, normalised_patch)
            return {
                "success": exec_result["success"],
                "validation_status": "valid",
                "errors": [],
                "warnings": [],
                "changes_applied": exec_result["changes_applied"],
                "execution_result": exec_result,
            }
    else:

        # Case2 :invalid
        print("Validation status: INVALID")
        print("Errors:")
        for err in errors:
            print(f"- {err.code}: {err.message}")
        print("Warnings:")
        for warn in warnings:
            print(f"- {warn.code}: {warn.message}")    

        return {
            "success": False,
            "validation_status": "invalid",
            "errors": [{"code": e.code, "message": e.message} for e in errors],
            "warnings": [{"code": w.code, "message": w.message} for w in warnings],
            "changes_applied": {},
            "execution_result": None,
        }

# def restore_config(config_path, backup_path):
#     if not os.path.exists(backup_path):
#         raise FileNotFoundError(f"Backup not found: {backup_path}")

#     shutil.copy(backup_path, config_path)
#     print(f"Executor: Config restored from {backup_path}")           


