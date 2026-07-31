"""
Builds a strict JSON schema for the LLM to follow
Requirements:
- prompt.json file path as an input (so that the immutable parameters are selected from memory only)

Steps:
- Obtains immutable parameters directly from config.json (preventing the storage to memory of any LLM hallucinations)
- Calls on ConfigChanges, a class located in Settings.py which contains all editable parameters 
  that the LLM has access to (within each parameter's allowable bounds)

Output:
- JSON schema template (TemplateJSON), which is to then be embedded within the API call in Call_API.py
- Design name (allowing for automatic input into prompt.json for when we switch design)
"""

import json
from pydantic import BaseModel, Field
from typing import Literal

# Build output JSON schema
def build_schema(ConfigChanges, config_path):

    # Unpack immutable parameters from config.json
    DESIGN_NAME_verified, VERILOG_FILES_verified, VERILOG_INCLUDE_DIRS_verified, CLOCK_PORT_verified, CLOCK_NET_verified, CLOCK_PERIOD_verified, pdk_verified, scl_verified = obtain_immutable_LLM_parameters(config_path)

    # Manually enforcing strict JSON structure on PDK and SCL configurations
    class SCLConfig(BaseModel):
        CLOCK_PERIOD: int = Field(default=25, ge=1) # range limited to stop unrealistic values that cause flow failure

    class PDKConfig(BaseModel):
        scl_sky130_fd_sc_hd: SCLConfig = Field(alias=scl_verified)

    # Fill in the input parameters and include ConfigChanges as a nested object
    class InputConfigJSON(BaseModel):
        # Immutable parameters (LLM must ouput exactly what it previously)
        DESIGN_NAME: Literal[DESIGN_NAME_verified]
        VERILOG_FILES: Literal[VERILOG_FILES_verified]
        VERILOG_INCLUDE_DIRS: Literal[VERILOG_INCLUDE_DIRS_verified]
        CLOCK_PORT: Literal[CLOCK_PORT_verified]
        CLOCK_NET: Literal[CLOCK_NET_verified]
        # CLOCK_PERIOD: Literal[CLOCK_PERIOD_verified]
        pdk_sky130A: PDKConfig = Field(alias=pdk_verified)
        #BASE_SDC_FILE: Literal[BASE_SDC_FILE_verified]
        # PNR_SDC_FILE: Literal[PNR_SDC_FILE_verified]
        # SIGNOFF_SDC_FILE: Literal[SIGNOFF_SDC_FILE_verified]
        # DIODE_INSERTION_STRATEGY: Literal[DIODE_INSERTION_STRATEGY_verified]

        # Input parameters
        inputted_parameters: ConfigChanges = Field(default_factory=ConfigChanges)

    # Fill in the suggested parameter changes and include ConfigChanges as a nested object
    class EditableConfigJSON(BaseModel):
        # Immutable parameters (LLM must ouput exactly what it previously)
        DESIGN_NAME: Literal[DESIGN_NAME_verified]
        VERILOG_FILES: Literal[VERILOG_FILES_verified]
        VERILOG_INCLUDE_DIRS: Literal[VERILOG_INCLUDE_DIRS_verified]
        CLOCK_PORT: Literal[CLOCK_PORT_verified]
        CLOCK_NET: Literal[CLOCK_NET_verified]
        # CLOCK_PERIOD: Literal[CLOCK_PERIOD_verified]
        pdk_sky130A: PDKConfig = Field(alias=pdk_verified)
        # BASE_SDC_FILE: Literal[BASE_SDC_FILE_verified]
        # PNR_SDC_FILE: Literal[PNR_SDC_FILE_verified]
        # SIGNOFF_SDC_FILE: Literal[SIGNOFF_SDC_FILE_verified]
        # DIODE_INSERTION_STRATEGY: Literal[DIODE_INSERTION_STRATEGY_verified]

        # Editable parameters
        updated_parameters: ConfigChanges = Field(default_factory=ConfigChanges)

        # Reasoning and Anlaysis
        reasoning: str | None = None
        is_best_run: bool
        terminate_flow: bool

    class TemplateJSON(BaseModel):
        current_settings: InputConfigJSON
        updated_settings: EditableConfigJSON

    return TemplateJSON, DESIGN_NAME_verified

# ====================================================
# Obtain parameters LLM can choose from
def obtain_immutable_LLM_parameters(config_path):

    # Read immutable parameters directly from config.json
    with open(config_path, "r") as f:
        current_config = json.load(f)

    DESIGN_NAME_verified = current_config["DESIGN_NAME"]
    VERILOG_FILES_verified = current_config["VERILOG_FILES"]
    VERILOG_INCLUDE_DIRS_verified = current_config["VERILOG_INCLUDE_DIRS"]
    CLOCK_PORT_verified = current_config["CLOCK_PORT"]
    CLOCK_NET_verified = current_config["CLOCK_NET"]
    CLOCK_PERIOD_verified = "<CLOCK_PERIOD_VALUE>" # placeholder value to be used in JSON schema, as CLOCK_PERIOD is now nested within the PDK and SCL configurations
    pdk_verified = "pdk::sky130A"
    scl_verified = "scl::sky130_fd_sc_hd"
    # BASE_SDC_FILE_verified = current_config["BASE_SDC_FILE"]
    # PNR_SDC_FILE_verified = current_config["PNR_SDC_FILE"]
    # SIGNOFF_SDC_FILE_verified = current_config["SIGNOFF_SDC_FILE"]
    # DIODE_INSERTION_STRATEGY_verified = current_config["DIODE_INSERTION_STRATEGY"]
    # DIODE_INSERTION_STRATEGY_verified = 1

    return DESIGN_NAME_verified, VERILOG_FILES_verified, VERILOG_INCLUDE_DIRS_verified, CLOCK_PORT_verified, CLOCK_NET_verified, CLOCK_PERIOD_verified, pdk_verified, scl_verified
# ====================================================

