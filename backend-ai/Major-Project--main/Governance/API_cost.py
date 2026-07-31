"""
Assertains total cost of API call
Requirements:
- Ensure the output of the API call is correctly inputted into the cost function
- Ensure all types of token costs (per million) are inputted from Settings.py

Steps:
- Works out the cost of each type of token
- Adds these together to get the total cost of the API call

Output:
- Total cost of the API call in USD
"""

import json
import os

# TO BE CALLED IN MAIN.PY
def get_API_call_cost_USD(response, input_USD_Mtok, cache_hit_input_USD_Mtok, output_USD_Mtok):

    # Calculate input cost USD (not including cache hits)
    base_input_tokens = response.usage.input_tokens - response.usage.input_tokens_details.cached_tokens
    base_input_cost_USD = (base_input_tokens / 1000000) * input_USD_Mtok

    # Calculate cache hit input cost USD
    cache_hit_input_tokens = response.usage.input_tokens_details.cached_tokens
    cache_hit_input_cost_USD = (cache_hit_input_tokens / 1000000) * cache_hit_input_USD_Mtok

    # Calcuate output cost USD
    output_tokens = response.usage.output_tokens
    output_cost_USD = (output_tokens / 1000000) * output_USD_Mtok

    # Total cost of the API call
    total_API_call_cost_USD = base_input_cost_USD + cache_hit_input_cost_USD + output_cost_USD

    print(total_API_call_cost_USD) # debugging / TO BE DELETED

    return total_API_call_cost_USD


def log_API_call_cost(response, costs_path, run_id, input_USD_Mtok, cache_hit_input_USD_Mtok, output_USD_Mtok):
    """Appends a cost record for this API call to a JSON log file."""

    base_input_tokens = response.usage.input_tokens - response.usage.input_tokens_details.cached_tokens
    cache_hit_input_tokens = response.usage.input_tokens_details.cached_tokens
    output_tokens = response.usage.output_tokens

    base_input_cost_USD = (base_input_tokens / 1000000) * input_USD_Mtok
    cache_hit_input_cost_USD = (cache_hit_input_tokens / 1000000) * cache_hit_input_USD_Mtok
    output_cost_USD = (output_tokens / 1000000) * output_USD_Mtok
    total_cost_USD = base_input_cost_USD + cache_hit_input_cost_USD + output_cost_USD

    record = {
        "run_id": run_id,
        "tokens": {
            "base_input": base_input_tokens,
            "cache_hit_input": cache_hit_input_tokens,
            "output": output_tokens,
        },
        "cost_USD": {
            "base_input": base_input_cost_USD,
            "cache_hit_input": cache_hit_input_cost_USD,
            "output": output_cost_USD,
            "total": total_cost_USD,
        },
    }

    if os.path.exists(costs_path):
        with open(costs_path, "r") as f:
            records = json.load(f)
    else:
        records = []

    records.append(record)

    with open(costs_path, "w") as f:
        json.dump(records, f, indent=2)

    return total_cost_USD
