# UNFINISHED CODE - DO NOT USE - CAN ONLY DEBUG WHEN MEMORY STRUCTURE IS FINALISED

# wrapper function to check all criteria
def check_stop_conditions(memory, invalid_output_threshold, window_length, plateau_threshold_proportion):
    
    error_check()
    invalid_output_tracker(memory, invalid_output_threshold)
    valid_metrics_checker(memory)
    metrics_evaluation(memory, window_length, plateau_threshold_proportion)

    return

# need to turn all these functions below into their own seperate files for better modularity

def invalid_output_tracker(memory, invalid_output_threshold): # TO BE FINALISED ONCE MEMORY STRUCTURE IS FINALISED

    # compute the amount of concurrent output failures by iterating through most recent memory entries
    for entry in memory.invalid_outputs:
        # find out what type of data structure memory.py is
        # then select the most recent validity status of LLM output
            # if invalid, record this and then go to the previous memory entry
            # if valid, break the loop and return the number of concurrent failures recorded so far
    # compare total invalid outputs to the threshold defined in settings.py

    # if invalid outputs exceeds tolerated threshold, raise an error
    if concurrent_failures > invalid_output_threshold:
        raise InvalidLLMOutputError("LLM output has been invalid for more than the allowed threshold")
    else:
        return None

def valid_metrics_checker(memory):
    # check if all metrics are valid (checking for NaN values, negative values, etc) and raise an error if not
    # NEED MEMORY.PY STRUCUTRE BEFORE THIS CAN BE IMPLEMENTED
    return


def metrics_evaluation(memory, window_length, plateau_threshold_proportion):


    # unwrap metrics with regard to power, latency, etc
    window_power_metrics = memory.metrics.power[-window_length:]
    window_latency_metrics = memory.metrics.latency[-window_length:]
    # etc for other metrics

    # compute whether each metric has plateaud and return a boolean for each metric
    plateau_detector(window_power_metrics, window_latency_metrics, plateau_threshold_proportion) # etc for other metrics
 
    # evaluate no-improvmenent counter
    if power_plateau:
        power_improvement = improvement_detector(memory, window_power_metrics)
    elif latency_plateau:
        latency_improvement = improvement_detector(memory, window_latency_metrics)
    # etc for other metrics

    # if consecutive non-improvements exceeds tolerated threshold, raise an error
    if consecutive_non_improvements > plateau_threshold:
        raise LLMPerformancePlateauError("LLM output performance metric has not improved for more than the allowed threshold")
    else:
        return None


# discuss with group whether any other functionality needs to be added
###################################################################################################################################

def plateau_detector(window_power_metrics, window_latency_metrics, plateau_threshold_proportion):
    # compute whether each metric has plateaud and return a boolean for each metric
    if ((max(window_power_metrics) - min(window_power_metrics)) / max(memory.metrics.power)) < plateau_threshold_proportion:
        power_plateau = True
    else:
        power_plateau = False
    if ((max(window_latency_metrics) - min(window_latency_metrics)) / max(memory.metrics.latency)) < plateau_threshold_proportion:
        latency_plateau = True
    else:
        latency_plateau = False
    # etc for other metrics
    return power_plateau, latency_plateau # etc for other metrics

def improvement_detector(memory, window_power_metrics, window_latency_metrics):
    # compute whether each metric has improved compared to previous window and return a boolean for each metric
    if max(window_power_metrics) < max(memory.metrics.power):
        power_non_improvement = True
    else:
        power_non_improvement = False
    if max(window_latency_metrics) < max(memory.metrics.latency):
        latency_non_improvement = True
    else:
        latency_non_improvement = False
    # etc for other metrics
    return power_non_improvement, latency_non_improvement # etc for other metrics

    # some logic to call get_api_balance(), but this only gets the balance and so theres
    # no decision making logic

    # NEED TO CREATE A DECISION MATRIX BASED ON ALL THE BOOLEAN VALUES

def error_check():
    return
