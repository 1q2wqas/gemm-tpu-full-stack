"""
Executes API call to LLM
Requirements:
- prompt.json file path
- JSON output schema

Steps:
- Converts prompt.json into string format to be inputted into API call
- Makes API call

Output:
- API call response
"""

import os, json
from openai import OpenAI

# TO BE CALLED IN Main.py
def execute_API_call(prompt_path, output_schema, reasoning_dict):

    prompt_string = create_API_string_input(prompt_path)
    response = call_API(prompt_string, output_schema, reasoning_dict)
    response_dict = convert_response_to_JSON(response)

    return response, response_dict


# =================================================================================
#   Sub-functions called in wrapper function:
# =================================================================================
def create_API_string_input(prompt_path):
    # Convert JSON file into dictionary
    with open(prompt_path, "r") as f:
        data = json.load(f)

    # Convert dictionary into string as input into API
    prompt_string = json.dumps(data, indent=4)

    print("\n" + "=" * 60) # debugging / TO BE DELETED
    print("INPUT PROMPT") # debugging / TO BE DELETED
    print("=" * 60) # debugging / TO BE DELETED
    print(prompt_string) # debugging / TO BE DELETED

    return prompt_string


def call_API(prompt_string, output_schema, reasoning_dict):

    # Initiate API call
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    response = client.responses.parse(

        # Necessary inputs
        model="gpt-5.2-codex",
        input=prompt_string,
        text_format=output_schema,

        # Performance-enhancing inputs
        prompt_cache_retention="in_memory",
        reasoning=reasoning_dict
    )

    print(response.usage) # debugging / TO BE DELETED

    return response


def convert_response_to_JSON(response):

    # Converts LLM output string into dictionary (follows JSON format)
    response_dict = json.loads(response.output_text)

    response_string = json.dumps(response_dict, indent=4) # debugging / TO BE DELETED
    
    print("\n" + "=" * 60) # debugging / TO BE DELETED
    print("LLM OUTPUT") # debugging / TO BE DELETED
    print("=" * 60) # debugging / TO BE DELETED
    print(response_string) # debugging / TO BE DELETED

    return response_dict