TOPLEVEL_LANG ?= verilog
SIM ?= icarus

ifeq ($(origin ACCEL_P), undefined)
  ifneq ($(origin P), undefined)
    ACCEL_P := $(P)
  endif
  ifneq ($(origin p), undefined)
    ACCEL_P := $(p)
  endif
endif

# The same testbench is reused for every supported physical array size.
ACCEL_P ?= 4
export ACCEL_P

COMPILE_ARGS += -DACCEL_P=$(ACCEL_P)

TOPLEVEL ?= gemm_core

COCOTB_TEST_MODULES ?= tb_owner1

export REPO_ROOT := $(abspath ../..)

export PYTHONPATH := $(REPO_ROOT)/tests/owner1:$(PYTHONPATH)

VERILOG_SOURCES += $(REPO_ROOT)/rtl/owner1_flow_v2/pe_mac.v
VERILOG_SOURCES += $(REPO_ROOT)/rtl/owner1_flow_v2/mac_array_pxp.v
VERILOG_SOURCES += $(REPO_ROOT)/rtl/owner1_flow_v2/gemm_core.v

VERILOG_INCLUDE_DIRS += $(REPO_ROOT)/rtl/include
COCOTB_RESULTS_FILE ?= results.xml

include $(shell cocotb-config --makefiles)/Makefile.sim

# Give each sweep point its own build and result file for CI artifacts.
ACCEL_P_LIST ?= 1 2 4 8

.PHONY: sweep_p
sweep_p:
	@set -e; \
	for p in $(ACCEL_P_LIST); do \
		echo "==================== ACCEL_P=$$p ===================="; \
		$(MAKE) --no-print-directory ACCEL_P=$$p \
			SIM_BUILD=sim_build_p$$p \
			COCOTB_RESULTS_FILE=results_p$$p.xml \
			results_p$$p.xml; \
	done
