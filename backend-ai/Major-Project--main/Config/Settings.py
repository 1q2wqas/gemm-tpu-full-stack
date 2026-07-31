"""
Global configuration for AI-guided optimisation of an OpenLane ASIC flow
Contains:
- Primary OpenLane flow settings
- Target metrics and sign off criteria
- Editable config.json variables and their allowable fields
- API cost variables
"""

from pydantic import BaseModel, Field
from typing import Literal

# ================================================================
# Top level Openlane flow settings
# ================================================================
design_name_str = "s1488"
openlane_timeout_duration = 2700
reasoning_dict = {"effort": "medium"} # options are "low", "medium", "high", "xhigh"

# ================================================================
# API cost variables - 5.2 codex
# ================================================================
input_USD_Mtok = 1.75
cache_hit_input_USD_Mtok = 0.175
output_USD_Mtok = 14

# ================================================================
# Editable Openlane config.json parameters and their constraints
# ================================================================
class ConfigChanges(BaseModel):

    CLOCK_PERIOD: int = Field(default=25, ge=1) # range limited to stop unrealistic values that cause flow failure

    # Synthesis
    SYNTH_MAX_FANOUT: int = Field(default=5, ge=2)
    SYNTH_MAX_TRAN: float = Field(default=2.5, gt=0)
    SYNTH_BUFFERING: Literal[0, 1] = 1
    SYNTH_SIZING: Literal[0, 1] = 0
    SYNTH_SHARE_RESOURCES: Literal[0, 1] = 1

    # Floorplanning
    FP_CORE_UTIL: int = Field(default=40, ge=40, le=80) # range limited to stop antenna violations and DRC errors
    FP_ASPECT_RATIO: float = Field(default=1.0, gt=0)
    FP_PDN_CORE_RING: Literal[0, 1] = 0
    DESIGN_IS_CORE: Literal[0, 1] = 1
    FP_SIZING: Literal["relative"] = "relative" 
    FP_TAPCELL_DIST: int = Field(default=14, gt=0)
    FP_IO_MIN_DISTANCE: int = Field(default=3, gt=0)
    
    # Placement
    PL_TARGET_DENSITY: float = Field(default=0.55, ge=0.4, le=0.9) # range limited to stop antenna violations and DRC errors
    PL_TIME_DRIVEN: Literal[0, 1] = 1
    PL_RESIZER_DESIGN_OPTIMIZATIONS: Literal[0, 1] = 1

    # Clock Tree Synthesis
    CTS_TARGET_SKEW: int = Field(default=200, ge=0)
    CTS_SINK_CLUSTERING_SIZE: int = Field(default=25, ge=1)
    CTS_SINK_CLUSTERING_MAX_DIAMETER: int = Field(default=50, ge=0)
    CTS_DISTANCE_BETWEEN_BUFFERS: float = Field(default=0, ge=0) 

    # Routing
    GLB_RT_ADJUSTMENT: float = Field(default=0.3, ge=0, le=1)
    GLB_RT_ALLOW_CONGESTION: Literal[0, 1] = 0
    GLB_RT_OVERFLOW_ITERS: int = Field(default=50, ge=0)
    GLB_OPTIMIZE_MIRRORING: Literal[0, 1] = 1

    # =========================================================
    # ADDED: OpenLane 2 step-specific / routing / antenna vars
    # =========================================================

    # Antenna / repair
    GRT_ANTENNA_MARGIN: int = Field(default=50, ge=0, le=100)  # ADDED
    GRT_ANTENNA_ITERS: int = Field(default=5, ge=0)  # ADDED
    GRT_REPAIR_ANTENNAS: Literal[0, 1] = 1  # ADDED
    HEURISTIC_ANTENNA_THRESHOLD: float = Field(default=50.0, ge=0)  # ADDED

    # Diode / placement repair
    DIODE_ON_PORTS: Literal["none", "in", "out", "both"] = "none"  # ADDED
    DIODE_PADDING: int = Field(default=1, ge=0)  # ADDED

    GPL_CELL_PADDING: float = Field(default=1.0, ge=0)  # ADDED
    DPL_CELL_PADDING: float = Field(default=1.0, ge=0)  # ADDED

    # Placement tuning
    PL_WIRE_LENGTH_COEF: float = Field(default=0.2, ge=0)  # ADDED

    # Design repair limits
    DESIGN_REPAIR_MAX_WIRE_LENGTH: float = Field(default=100.0, ge=0)  # ADDED

    # Post-GRT repair (explicitly different knob)
    GRT_DESIGN_REPAIR_MAX_WIRE_LENGTH: float = Field(default=100.0, ge=0)  # ADDED

    # Enum flow controls
    RUN_HEURISTIC_DIODE_INSERTION: Literal[0, 1] = 1  # ADDED
    RUN_ANTENNA_REPAIR: Literal[0, 1] = 1  # ADDED
    RUN_POST_CTS_RESIZER_TIMING: Literal[0, 1] = 1  # ADDED
    RUN_POST_GRT_DESIGN_REPAIR: Literal[0, 1] = 1  # ADDED
    
# where ranges have been limited, the LLM was too frequently causing Openlane flow failure 
# within certain sensitive parameters by implementing unrealistic real world values

# ================================================================
# Target metrics and violations criteria
# ================================================================
desired_metrics = {
    'power__internal__total',
    'power__switching__total',
    'power__leakage__total',
    'power__total',
    
    'design__instance__area',
    'design__instance__count',
    'design__die__area',
    'design__core__area',
    'design__instance__area__stdcell',
    'design__instance__count__stdcell',
    'design__instance__utilization',
    'design__instance__utilization__stdcell',

    'timing__setup__wns',
    'timing__hold__wns',
    'timing__setup__tns',
    'timing__hold__tns',
    'timing__hold_vio__count',
    'timing__setup_vio__count',

    'design__max_slew_violation__count',
    'design__max_fanout_violation__count',
    'design__max_cap_violation__count',
    'clock__skew__worst_hold',
    'clock__skew__worst_setup',

    'route__wirelength',
    'route__vias',
    'route__drc_errors',
    'route__antenna_violation__count',
    'design__lvs_error__count',
    'design__instance__count__hold_buffer',
    'design__instance__count__setup_buffer'
}

# power, area, timing, and reliability metrics that the agent will optimize for, 
# as well as any additional custom metrics relevant to the specific design and optimisation goals.