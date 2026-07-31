from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple
import math

# =========== Validation Result/ Message Models ===========

@dataclass
class ValidationMessage:
    level: str  # "error", "warning", "info"
    code: str  # unique code for the type of message, e.g. "missing_parameter", "invalid_value", etc.
    message: str  # human-readable message describing the issue
    field: Optional[str] = None  # the specific parameter/field the message pertains to, if applicable

@dataclass
class ValidationResult:
    
    valid: bool = False
    errors: List[ValidationMessage] = field(default_factory=list)
    warnings: List[ValidationMessage] = field(default_factory=list)
    infos: List[ValidationMessage] = field(default_factory=list)

    normalised_patch: Dict[str, Any] = field(default_factory=dict)  # the cleaned/normalised version of the proposed changes, to be used for applying changes if valid
    normalised_full_config: Dict[str, Any] = field(default_factory=dict)  # the cleaned/normalised version of the current config, for comparison/logging purposes

    parsed_reasoning: str = ""  
    parsed_is_best_run: Optional[bool] = None # ADDED BY MAXIMO
    parsed_terminate_flow: Optional[bool] = None
    changed_keys: List[str] = field(default_factory=list)  # list of parameter names that were approved for change
    #termination_requested: bool = False  # flag to indicate if the LLM is requesting termination

    def add_error(self, code: str, message: str, field: Optional[str] = None) -> None:
        self.errors.append(ValidationMessage(level="error", code=code, message=message, field=field))

    def add_warning(self, code: str, message: str, field: Optional[str] = None) -> None:
        self.warnings.append(ValidationMessage(level="warning", code=code, message=message, field=field))

    def add_info(self, code: str, message: str, field: Optional[str] = None) -> None:
        self.infos.append(ValidationMessage(level="info", code=code, message=message, field=field))

    def merge(self, other: "ValidationResult") -> None:
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)
        self.infos.extend(other.infos)

    def finalise(self) -> "ValidationResult":
        self.valid = len(self.errors) == 0 # True: when no errors/ False when errors exists.
        return self

# =========== Helper Functions ===========
def flatten_schema_config(schema_config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generic flattening of schema config:
    - extracts immutable fields
    - dynamically finds PDK and SCL blocks
    - extracts CLOCK_PERIOD
    - merges inputted_parameters
    """
    flat: Dict[str, Any] = {}

    if not isinstance(schema_config, dict):
        return flat

    # Copy immutable keys
    immutable_keys = [
        "DESIGN_NAME",
        "VERILOG_FILES",
        "VERILOG_INCLUDE_DIRS",
        "CLOCK_PORT",
        "CLOCK_NET",
        # "BASE_SDC_FILE", # ADDED BY MAXIMO
        # "PNR_SDC_FILE", # ADDED BY MAXIMO
        # "SIGNOFF_SDC_FILE", # ADDED BY MAXIMO
        # "DIODE_INSERTION_STRATEGY", # ADDED BY MAXIMO
    ]

    for key in immutable_keys:
        if key in schema_config:
            flat[key] = schema_config[key]
    
    if "CLOCK_PERIOD" in schema_config:
        flat["CLOCK_PERIOD"] = schema_config["CLOCK_PERIOD"]

    # Detect PDK dynamically
    pdk_key = None
    for key, value in schema_config.items():
        if isinstance(key, str) and key.startswith("pdk::") and isinstance(value, dict):
            pdk_key = value
            break

    # Detect SCL dynamically
    if isinstance(pdk_key, dict):
        for key, value in pdk_key.items():
            if isinstance(key, str) and key.startswith("scl::") and isinstance(value, dict):

                # extract scl specific CLOCK_PERIOD if present
                if "CLOCK_PERIOD" in value:
                    flat["SCL_CLOCK_PERIOD"] = value["CLOCK_PERIOD"]

                break # assumed only one scl
    
    # Merge editable parameteers
    inputs = schema_config.get("inputted_parameters")

    if isinstance(inputs, dict):
        flat.update(inputs)

    return flat


# =========== LLM Response Parser ===========

@dataclass
class ParsedLLMResponse:
    proposed_changes: Dict[str, Any] = field(default_factory=dict)
    reasoning: str = ""
    is_best_run: bool = False
    terminate_flow: bool = False
    current_settings: Dict[str, Any] = field(default_factory=dict)
    updated_settings: Dict[str, Any] = field(default_factory=dict)
    raw_payload: Dict[str, Any] = field(default_factory=dict)

class LLMResponseParser:
    """
    Parse LLM response and performs basic schema validation.
    """

    def parse(self, llm_response: Dict[str, Any]) -> ParsedLLMResponse:
        
        if not isinstance(llm_response, dict):
            raise ValueError("LLM response must be a parsed JSON object (Python dict).")
        
        current_settings = llm_response.get("current_settings")
        updated_settings = llm_response.get("updated_settings")

        if not isinstance(current_settings, dict):
            raise ValueError("LLM response 'current_settings' must be a dict")
        if not isinstance(updated_settings, dict):
            raise ValueError("LLM response 'updated_settings' must be a dict")

        proposed_changes = updated_settings.get("updated_parameters", {})
        if proposed_changes is None:
            proposed_changes = {}
        if not isinstance(proposed_changes, dict):
            raise ValueError("LLM response 'updated_settings.updated_parameters' must be a dict or null.")

        reasoning = updated_settings.get("reasoning", "")
        if reasoning is None:
            reasoning = ""
        elif not isinstance(reasoning, str):
            raise ValueError("LLM response 'updated_settings.reasoning' must be a string or null.")
        reasoning = reasoning.strip() 

        is_best_run = updated_settings.get("is_best_run", None)
        if is_best_run is not None and not isinstance(is_best_run, bool):
            raise ValueError("LLM response 'updated_settings.is_best_run' must be a boolean if provided.")
        
        # ADDED BY MAXIMO =======================
        terminate_flow = updated_settings.get("terminate_flow", None)
        if terminate_flow is not None and not isinstance(terminate_flow, bool):
            raise ValueError("LLM response 'updated_settings.terminate_flow' must be a boolean if provided.")
        # =======================================

        return ParsedLLMResponse(
            proposed_changes=proposed_changes,
            reasoning=reasoning,
            is_best_run=is_best_run,
            terminate_flow=terminate_flow, # ADDED BY MAXIMO
            current_settings=current_settings,
            updated_settings=updated_settings,
            raw_payload=llm_response,
        )

# =========== Knob Rule Table ===========

CustomValidator = Callable[
    [str, Any, Dict[str, Any], Dict[str, Any], ValidationResult],
    Any,
]

@dataclass
class ParameterRule:
    name: str
    expected_type: Tuple[type, ...]  # expected data type(s) for the parameter value
    required: bool = False  # whether this parameter is required to be in config
    mutable: bool = True  # whether this parameter is allowed to be changed

    # Hard legality constriants according to OpenLane docs # errors 
    min_value: Optional[float] = None  # minimum value if the parameter is numeric
    max_value: Optional[float] = None  # maximum value if the parameter is numeric
    allowed_values: Optional[set] = None  
    
    custom_validator: Optional[CustomValidator] = None # function for any custom validation logic that can't be captured by the other fields


# =========== Main Validator Class for config variables ===========

class ConfigValidator:
    """
    Validates extracted patch (propsed changes) against
    - type/ range
    - unit sanity
    - cross-field consistency
    - change budget
    """

    def __init__(self) -> None:
        self.rules = self._build_rule_table()

    def validate(
        self,
        baseline_config: Dict[str, Any],
        proposed_patch: Dict[str, Any],
    ) -> ValidationResult:

        result = ValidationResult()

        if not isinstance(baseline_config, dict):
            result.add_error(code="invalid_baseline_config", message="Baseline config must be a dictionary.")
            return result.finalise()

        if not isinstance(proposed_patch, dict):
            result.add_error(code="invalid_proposed_patch (changes)", message="Proposed patch must be a dictionary.")
            return result.finalise()

        merged = dict(baseline_config)  # start with current config
        merged.update(proposed_patch)  # apply proposed changes on top for validation context

        changed_keys = self._diff_keys(baseline_config, proposed_patch)
        result.changed_keys = changed_keys[:]

        for key in proposed_patch.keys():
            if key not in self.rules and key not in baseline_config:
                result.add_error(code="unknown_parameter", message=f"Parameter '{key}' is not recognized.", field=key)
            
        for key, rule in self.rules.items():
            if rule.required and key not in merged:
                result.add_error(code="missing_required_parameter", message=f"Required parameter '{key}' is missing from proposed changes.", field=key)

        normalised = dict(merged) # {current_config + proposed changes}

        for key, value in list(normalised.items()):
            if key not in self.rules and key not in baseline_config:
                result.add_error(code="unknown_parameter", message=f"Parameter '{key}' is not recognized.", field=key)
                continue

            rule = self.rules[key]

            if key in changed_keys and not rule.mutable:
                result.add_error(code="immutable_parameter", message=f"Parameter '{key}' is not allowed to be changed.", field=key)
                continue
            
            if not isinstance(value, rule.expected_type):
                if float in rule.expected_type and isinstance(value, int):
                    value = float(value)  # allow ints for float fields
                else:
                    expected = ", ".join(t.__name__ for t in rule.expected_type)
                    result.add_error(code="type_mismatch", message=f"Parameter '{key}' has invalid type. Expected {expected}, got {type(value).__name__}.", field=key)

                    continue

            if isinstance(value, (int, float)) and not math.isfinite(float(value)):
                result.add_error(code="non_finite_value", message=f"Parameter '{key}' must be finite.", field=key)
                continue

            if rule.allowed_values is not None and value not in rule.allowed_values:
                result.add_error(
                    "VALUE_NOT_ALLOWED",
                    f"Parameter '{key}' must be one of {sorted(rule.allowed_values)}, got {value!r}.",
                    field=key,
                )
                continue

            if isinstance(value, (int, float)):

                if rule.min_value is not None and value < rule.min_value:
                    result.add_error(code="value_below_min", message=f"Parameter '{key}' must be >= {rule.min_value}, got {value}.", field=key)
                    continue
                if rule.max_value is not None and value > rule.max_value:
                    result.add_error(code="value_above_max", message=f"Parameter '{key}' must be <= {rule.max_value}, got {value}.", field=key)
                    continue

            if rule.custom_validator is not None:
                try:
                    rule.custom_validator(key, value, normalised, baseline_config, result)
                except Exception as e:
                    result.add_error(code="custom_validator_exception", message=f"Custom validator for parameter '{key}' raised an exception: {str(e)}", 
                        field=key)
                    continue

            normalised[key] = value

        self.validate_cross_field_rules(
            baseline_config=baseline_config,
            config=normalised,
            changed_keys=changed_keys,
            result=result   
        )

        normalised_patch = {} # include only the parameters that LLM actually changed

        for key in changed_keys:
            if key in normalised:
                normalised_patch[key] = normalised[key]

        result.normalised_patch = normalised_patch
        result.normalised_full_config = normalised  
        return result.finalise()
    
    # rule table #

    def _build_rule_table(self) -> Dict[str, ParameterRule]:
        return {
            # Base
            "DESIGN_NAME": ParameterRule(
                name="DESIGN_NAME",
                expected_type=(str,),
                required=True,
                mutable=False
            ),
            "VERILOG_FILES": ParameterRule(
                name="VERILOG_FILES",
                expected_type=(str,), #Maximo changed from (list,) to (str,) to accommodate new config.json format
                mutable=False
            ),
            "VERILOG_INCLUDE_DIRS": ParameterRule(
                name="VERILOG_INCLUDE_DIRS",
                expected_type=(str,),
                mutable=False
            ),
            "CLOCK_PERIOD": ParameterRule(
                name="CLOCK_PERIOD",
                expected_type=(int, float),
                required=True,
                mutable=False, # ADDED BY MAXIMO
                min_value=1.0,  #ns
                max_value=100.0,  
                custom_validator=self._validate_clock_period
            ),
            "CLOCK_PORT": ParameterRule(
                name="CLOCK_PORT",
                expected_type=(str,),
                required=True,
                mutable=False
            ),
            "CLOCK_NET": ParameterRule(
                name="CLOCK_NET",
                expected_type=(str,),
                required=True,
                mutable=False
            ),
            "SCL_CLOCK_PERIOD": ParameterRule(
                name="SCL_CLOCK_PERIOD",
                expected_type=(int, float),
                required=True,
                mutable=False,
                min_value=1.0,
                max_value=100.0,
                custom_validator=self._validate_clock_period
            ),

            # # ADDED BY MAXIMO ===================================
            # "BASE_SDC_FILE": ParameterRule(
            #     name="BASE_SDC_FILE",
            #     expected_type=(str,),
            #     required=True,
            #     mutable=False
            # ),

            # "PNR_SDC_FILE": ParameterRule(
            #     name="PNR_SDC_FILE",
            #     expected_type=(str,),
            #     required=True,
            #     mutable=False
            # ),

            # "SIGNOFF_SDC_FILE": ParameterRule(
            #     name="SIGNOFF_SDC_FILE",
            #     expected_type=(str,),
            #     required=True,
            #     mutable=False
            # ),

            # ===================================================
            # Synthesis
            "SYNTH_MAX_FANOUT": ParameterRule(
                name="SYNTH_MAX_FANOUT",
                expected_type=(int,),
                min_value=2, 
                custom_validator=self._validate_synth_max_fanout
            ),
            "SYNTH_MAX_TRAN": ParameterRule(
                name="SYNTH_MAX_TRAN", 
                expected_type=(float,),
                custom_validator=self._validate_synth_max_tran
            ), 
            "SYNTH_BUFFERING": ParameterRule(
                name="SYNTH_BUFFERING",
                expected_type=(int,),
                allowed_values={0, 1}
            ),
            "SYNTH_SIZING": ParameterRule(
                name="SYNTH_SIZING",
                expected_type=(int,),
                allowed_values={0, 1}
            ),
            "SYNTH_SHARE_RESOURCES": ParameterRule(
                name="SYNTH_SHARE_RESOURCES",
                expected_type=(int,),
                allowed_values={0, 1}
            ),

            # Floorplanning
            "FP_CORE_UTIL": ParameterRule(
                name="FP_CORE_UTIL",
                expected_type=(int,),
                min_value=40,
                max_value=80
            ),

            "FP_ASPECT_RATIO": ParameterRule(
                name="FP_ASPECT_RATIO",     
                expected_type=(float,),
                min_value=0.5,
                max_value=2.0
            ),

            "FP_PDN_CORE_RING": ParameterRule("FP_PDN_CORE_RING", (int,), allowed_values={0, 1}),
            "DESIGN_IS_CORE": ParameterRule("DESIGN_IS_CORE", (int,), allowed_values={0, 1}),
            
            "FP_SIZING": ParameterRule("FP_SIZING", (str,), allowed_values={"absolute", "relative"}),

            "FP_TAPCELL_DIST": ParameterRule("FP_TAPCELL_DIST", (int,float,), min_value=1, custom_validator=self._validate_fp_tapcell_dist), 
            
            "FP_IO_MIN_DISTANCE": ParameterRule("FP_IO_MIN_DISTANCE", (float,), min_value=0),

            # Placement
            "PL_TARGET_DENSITY": ParameterRule("PL_TARGET_DENSITY", (int, float), min_value=0.45, max_value=0.85), # (1-5% higher than FP_CORE_UTIL.)
            "PL_TIME_DRIVEN": ParameterRule("PL_TIME_DRIVEN", (int,), allowed_values={0, 1}),
            "PL_RESIZER_DESIGN_OPTIMIZATIONS": ParameterRule("PL_RESIZER_DESIGN_OPTIMIZATIONS", (int,), allowed_values={0, 1}),

            # Clock Tree Synthesis
            "CTS_TARGET_SKEW": ParameterRule("CTS_TARGET_SKEW", (int, float), min_value=0),
            "CTS_SINK_CLUSTERING_SIZE": ParameterRule("CTS_SINK_CLUSTERING_SIZE", (int,), min_value=1),
            "CTS_SINK_CLUSTERING_MAX_DIAMETER": ParameterRule("CTS_SINK_CLUSTERING_MAX_DIAMETER", (int, float), min_value=0),
            "CTS_DISTANCE_BETWEEN_BUFFERS": ParameterRule("CTS_DISTANCE_BETWEEN_BUFFERS", (int, float), min_value=0),

            # Routing
            "GLB_RT_ADJUSTMENT": ParameterRule("GLB_RT_ADJUSTMENT", (int, float), min_value=0.0, max_value=1.0),
            "GLB_RT_ALLOW_CONGESTION": ParameterRule("GLB_RT_ALLOW_CONGESTION", (int,), allowed_values={0, 1}),
            "GLB_RT_OVERFLOW_ITERS": ParameterRule("GLB_RT_OVERFLOW_ITERS", (int,), min_value=0),
            "GLB_OPTIMIZE_MIRRORING": ParameterRule("GLB_OPTIMIZE_MIRRORING", (int,), allowed_values={0, 1}),

            # ======================================================
            # 🆕 ADDED: OpenLane 2 antenna / repair / diode controls
            # ======================================================

            "GRT_ANTENNA_MARGIN": ParameterRule(  # ADDED
                name="GRT_ANTENNA_MARGIN",
                expected_type=(int,),
                min_value=0,
                max_value=100
            ),

            "GRT_ANTENNA_ITERS": ParameterRule(  # ADDED
                name="GRT_ANTENNA_ITERS",
                expected_type=(int,),
                min_value=0,
                max_value=100
            ),

            "GRT_REPAIR_ANTENNAS": ParameterRule(  # ADDED
                name="GRT_REPAIR_ANTENNAS",
                expected_type=(int,),
                allowed_values={0, 1}
            ),

            "HEURISTIC_ANTENNA_THRESHOLD": ParameterRule(  # ADDED
                name="HEURISTIC_ANTENNA_THRESHOLD",
                expected_type=(float,),
                min_value=0.0
            ),


            "DIODE_ON_PORTS": ParameterRule(  # ADDED
                name="DIODE_ON_PORTS",
                expected_type=(str,),
                allowed_values={"none", "in", "out", "both"}
            ),

            "DIODE_PADDING": ParameterRule(  # ADDED
                name="DIODE_PADDING",
                expected_type=(int,),
                min_value=0
            ),

            "GPL_CELL_PADDING": ParameterRule(  # ADDED
                name="GPL_CELL_PADDING",
                expected_type=(float,),
                min_value=0.0
            ),

            "DPL_CELL_PADDING": ParameterRule(  # ADDED
                name="DPL_CELL_PADDING",
                expected_type=(float,),
                min_value=0.0
            ),

            "PL_WIRE_LENGTH_COEF": ParameterRule(  # ADDED
                name="PL_WIRE_LENGTH_COEF",
                expected_type=(float,),
                min_value=0.0
            ),

            "DESIGN_REPAIR_MAX_WIRE_LENGTH": ParameterRule(  # ADDED
                name="DESIGN_REPAIR_MAX_WIRE_LENGTH",
                expected_type=(float,),
                min_value=0
            ),

            "GRT_DESIGN_REPAIR_MAX_WIRE_LENGTH": ParameterRule(  # ADDED
                name="GRT_DESIGN_REPAIR_MAX_WIRE_LENGTH",
                expected_type=(float,),
                min_value=0
            ),

            "RUN_HEURISTIC_DIODE_INSERTION": ParameterRule(  # ADDED
                name="RUN_HEURISTIC_DIODE_INSERTION",
                expected_type=(int,),
                allowed_values={0, 1}
            ),

            "RUN_ANTENNA_REPAIR": ParameterRule(  # ADDED
                name="RUN_ANTENNA_REPAIR",
                expected_type=(int,),
                allowed_values={0, 1}
            ),

            "RUN_POST_CTS_RESIZER_TIMING": ParameterRule(  # ADDED
                name="RUN_POST_CTS_RESIZER_TIMING",
                expected_type=(int,),
                allowed_values={0, 1}
            ),

            "RUN_POST_GRT_DESIGN_REPAIR": ParameterRule(  # ADDED
                name="RUN_POST_GRT_DESIGN_REPAIR",
                expected_type=(int,),
                allowed_values={0, 1}
            ),
        }

# =========== Some Variables' Validation Functions ===========

    def _validate_clock_period(
        self,
        field: str,
        value: Any,
        full_config: Dict[str, Any],
        baseline_config: Dict[str, Any],
        result: ValidationResult
    ) -> float:
        value = float(value)
        if value < 1.0:
            result.add_warning(
                code="very_low_clock_period", 
                message=f"Clock period '{value}' ns is very aggressive and may destabilize exploration.",
                field=field
            )
        return value

    def _validate_synth_max_fanout(
        self,
        field: str,
        value: Any,
        full_config: Dict[str, Any],
        baseline_config: Dict[str, Any],
        result: ValidationResult
    ) -> float:
        value = int(value)
        if value > 32:
            result.add_warning(
                code="high_synth_max_fanout", 
                message=f"SYNTH_MAX_FANOUT='{value}' is quite high and may lead to large buffers that increase delay and power.",
                field=field
            )
        return value
    
    def _validate_synth_max_tran(
        self,
        field: str,
        value: Any,
        full_config: Dict[str, Any],
        baseline_config: Dict[str, Any],
        result: ValidationResult
    ) -> float:
        value = float(value)
        
        # get effective clock period
        clk = full_config.get("SCL_CLOCK_PERIOD", full_config.get("CLOCK_PERIOD"))

        if clk is None:
            result.add_error(                
                "MISSING_CLOCK_PERIOD",
                "CLOCK_PERIOD is required to validate SYNTH_MAX_TRAN safely.",
                field=field
            )
            return value

        clk = float(clk)

        expected = 0.10 * clk  # 10% of clock period is default-like scale for max transition time according to OpenLane docs and general synthesis practices

        if value <= 0:
            result.add_error(
                "INVALID_VALUE",
                f"{field} must be > 0 ns",
                field=field
            )

        elif value < 0.25 * expected:
            result.add_warning(
                "VERY_TIGHT_MAX_TRAN",
                f"{field}={value} ns is much tighter than typical default "
                f"(~{expected:.3f} ns).",
                field=field
            )

        elif value > 2.0 * expected:
            result.add_warning(
                "LOOSE_MAX_TRAN",
                f"{field}={value} ns is much looser than typical default "
                f"(~{expected:.3f} ns).",
                field=field
            )

        if value > 0.5 * clk:
            result.add_error(
                "TOO_LARGE_FOR_CLOCK",
                f"{field}={value} ns exceeds 50% of CLOCK_PERIOD={clk} ns.",
                field=field
            )

        return value
    
    def _validate_fp_tapcell_dist(
        self,
        field: str,
        value: Any,
        full_config: Dict[str, Any],
        baseline_config: Dict[str, Any],
        result: ValidationResult
    ) -> int:
        value = int(value)

        if value < 8:
            result.add_warning(
                "TIGHT_TAPCELL_DIST",
                f"{field}={value} is quite tight",
                field=field
            )
        elif value > 30:
            result.add_warning(
                "LOOSE_TAPCELL_DIST",
                f"{field}={value} is quite loose",
                field=field
            )

        return value

# =========== Cross-field validation checks ===========

    # need to research more 
    def validate_cross_field_rules(
        self,
        baseline_config: Dict[str, Any],
        config: Dict[str, Any],
        changed_keys: List[str],
        result: ValidationResult
    ) -> None:
        
        # PL_TARGET_DENSITY vs FP_CORE_UTIL
        if "FP_CORE_UTIL" in config and "PL_TARGET_DENSITY" in config:
            util = float(config["FP_CORE_UTIL"]) / 100.0
            density = float(config["PL_TARGET_DENSITY"])

            if density < util:
                result.add_error(
                    "DENSITY_BELOW_UTILIZATION",
                    f"PL_TARGET_DENSITY={density:.3f} is below FP_CORE_UTIL={config['FP_CORE_UTIL']}% ({util:.3f}).",
                    field="PL_TARGET_DENSITY",
                )
            elif density > util + 0.10:
                result.add_warning(
                    "DENSITY_FAR_ABOVE_UTILIZATION",
                    f"PL_TARGET_DENSITY={density:.3f} is much higher than FP_CORE_UTIL={config['FP_CORE_UTIL']}% ({util:.3f}).",
                    field="PL_TARGET_DENSITY",
                )

        # FP_PDN_CORE_RING vs DESIGN_IS_CORE (for macro_level)
        if config.get("FP_PDN_CORE_RING") == 1 and config.get("DESIGN_IS_CORE") == 0:
            result.add_warning(
                "CORE_RING_ENABLED_FOR_MACRO",
                "FP_PDN_CORE_RING=1 while DESIGN_IS_CORE=0. This can be valid in some contexts (for macro_level), "
                "but should be reviewed explicitly.",
                field="FP_PDN_CORE_RING",
            )

        # FP_SIZING consistency for floorplan
        if "FP_SIZING" in config:
            fp_sizing = config["FP_SIZING"]

            if fp_sizing == "absolute":
                if "DIE_AREA" not in config or not config.get("DIE_AREA"):
                    result.add_error(
                        "missing_die_area_for_absolute_sizing",
                        "DIE_AREA is required when FP_SIZING='absolute'.",
                        field="DIE_AREA",
                    )
            
            elif fp_sizing == "relative":
                if "DIE_AREA" in changed_keys:
                    result.add_error(
                        "die_area_changed_with_relative_sizing",
                        "DIE_AREA was changed while FP_SIZING='relative'.",
                        field="DIE_AREA",
                    )
                
                if "FP_CORE_UTIL" not in config:
                    result.add_error(
                        "missing_fp_core_util_for_relative_sizing",
                        "FP_CORE_UTIL is required when FP_SIZING='relative'.",
                        field="FP_CORE_UTIL",
                    )

                if "FP_ASPECT_RATIO" not in config:
                    result.add_error(
                        "missing_fp_aspect_ratio_for_relative_sizing",
                        "FP_ASPECT_RATIO is required when FP_SIZING='relative'.",
                        field="FP_ASPECT_RATIO",
                    )            

        # Basic delta checks from baseline
        self._validate_delta_policy(
            baseline_config=baseline_config, 
            config=config, 
            changed_keys=changed_keys, 
            result=result)

    def _validate_delta_policy(
        self,
        baseline_config: Dict[str, Any],
        config: Dict[str, Any],
        changed_keys: List[str],
        result: ValidationResult
    ) -> None:

        for key in changed_keys:
            if key not in baseline_config:
                continue

            old = baseline_config[key]
            new = config[key]

            if isinstance(old, (int, float)) and isinstance(new, (int, float)):
                if old == 0:
                    continue
                
                ratio = abs(float(new) / float(old))

                if key == "FP_CORE_UTIL" and abs(float(new) - float(old)) > 10:
                    result.add_warning(
                        "LARGE_DELTA_",
                        f"{key} changed from {old} to {new}; consider limiting to ±10 per run.",
                        field=key,
                    )
                
                if key in {"PL_TARGET_DENSITY"} and abs(float(new) - float(old)) > 0.08:
                    result.add_warning(
                        "LARGE_DELTA",
                        f"{key} changed from {old} to {new}; consider limiting to ±0.08 per run.",
                        field=key,
                    )
                
                if key in {"SYNTH_MAX_FANOUT"} and ratio > 2.0:
                    result.add_warning(
                        "LARGE_MULTIPLICATIVE_DELTA",
                        f"{key} changed from {old} to {new}; more than 2x in one step.",
                        field=key,
                    )

    # Utils

    def _diff_keys(
        self,
        baseline_config: Dict[str, Any],
        proposed_patch: Dict[str, Any],
    ) -> List[str]:
        changed = []
        for k, v in proposed_patch.items():
            if k not in baseline_config or baseline_config[k] != v:
                changed.append(k)
        return changed
    

# ============================================================
# High-level entrypoint
# ============================================================

class Validator:
    """
    Combined validator:
    1) parse LLM response
    2) extract patch
    3) validate patch against OpenLane policy
    4) validate reasoning/patch coherence
    """

    def __init__(self) -> None:
        self.parser = LLMResponseParser()
        self.config_validator = ConfigValidator()

    def validate_llm_response(
        self,
        llm_payload: Dict[str, Any],
        baseline_config: Dict[str, Any] | None = None,
    ) -> ValidationResult:

        result = ValidationResult()

        try:
            parsed = self.parser.parse(llm_payload)
        except Exception as exc:
            result.add_error("LLM_SCHEMA_INVALID", str(exc))
            return result.finalise()

        result.parsed_reasoning = parsed.reasoning
        result.parsed_is_best_run = parsed.is_best_run
        result.parsed_terminate_flow = parsed.terminate_flow # ADDED BY MAXIMO

        self._check_echo_consistency(parsed, result)

        baseline_flat = flatten_schema_config(parsed.current_settings)

        config_result = self.config_validator.validate(
            baseline_config=baseline_flat,
            proposed_patch=parsed.proposed_changes,
        )
        result.merge(config_result)
        result.normalised_patch = config_result.normalised_patch
        result.normalised_full_config = config_result.normalised_full_config
        result.changed_keys = config_result.changed_keys

        return result.finalise()

    def _check_echo_consistency(self, parsed: ParsedLLMResponse, result: ValidationResult) -> None:
        
        source_patch = parsed.proposed_changes
        current_inputs = parsed.current_settings.get("inputted_parameters")

        if isinstance(current_inputs, dict) and current_inputs == source_patch and parsed.reasoning:
            result.add_info(
                "CURRENT_SETTINGS_EQUALS_UPDATED_SETTINGS",
                "'current_settings.inputted_parameters' matches the proposed changes. "
                "This may mean the LLM echoed already-applied values."
            )









