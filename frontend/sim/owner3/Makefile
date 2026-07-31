TOPLEVEL_LANG ?= verilog
SIM    ?= icarus
TOP    ?= tpu_wb_periph_b
COCOTB_TEST_MODULES ?= tb_owner3

ifeq ($(origin ACCEL_P), undefined)
  ifneq ($(origin P), undefined)
    ACCEL_P := $(P)
  endif
  ifneq ($(origin p), undefined)
    ACCEL_P := $(p)
  endif
endif

ACCEL_P ?= 4
export ACCEL_P

SIM_DIR   := $(CURDIR)
REPO_ROOT := $(abspath $(CURDIR)/../..)
RTL_DIR   := $(REPO_ROOT)/rtl/owner3
INC_DIR   := $(REPO_ROOT)/rtl/include
TEST_DIR  := $(REPO_ROOT)/tests/owner3

export PYTHONPATH := $(TEST_DIR):$(SIM_DIR):$(PYTHONPATH)

SIM_BUILD ?= sim_build/$(TOP)
COCOTB_RESULTS_FILE ?= results_$(TOP).xml

COMPILE_ARGS += -I$(RTL_DIR) -I$(INC_DIR)
COMPILE_ARGS += -DACCEL_P=$(ACCEL_P)

ifeq ($(TOP),cfg_status_regs)
VERILOG_SOURCES = \
	$(RTL_DIR)/cfg_status_regs.v
endif

ifeq ($(TOP),gemm_accel_top_b)
VERILOG_SOURCES = \
	$(RTL_DIR)/gemm_accel_top_b.v \
	$(RTL_DIR)/stubs_gemm.v
endif

ifeq ($(TOP),tpu_wb_periph_b)
VERILOG_SOURCES = \
	$(RTL_DIR)/cfg_status_regs.v \
	$(RTL_DIR)/tpu_wb_periph_b.v \
	$(RTL_DIR)/stubs_periph.v
endif

ifeq ($(TOP),user_project_wrapper)
VERILOG_SOURCES = \
	$(RTL_DIR)/cfg_status_regs.v \
	$(RTL_DIR)/tpu_wb_periph_b.v \
	$(RTL_DIR)/user_project_wrapper.v \
	$(RTL_DIR)/stubs_periph.v
COMPILE_ARGS += -DMPRJ_IO_PADS=38
endif

TOPLEVEL = $(TOP)

ifeq ($(strip $(VERILOG_SOURCES)),)
$(error Unsupported TOP='$(TOP)'. Use cfg_status_regs, gemm_accel_top_b, tpu_wb_periph_b, or user_project_wrapper)
endif

include $(shell cocotb-config --makefiles)/Makefile.sim

ACCEL_P_LIST ?= 1 2 4 8
P_SWEEP_TOPS ?= gemm_accel_top_b tpu_wb_periph_b user_project_wrapper

.PHONY: sweep_p
sweep_p:
	@set -e; \
	for top in $(P_SWEEP_TOPS); do \
		for p in $(ACCEL_P_LIST); do \
			echo "==================== TOP=$$top ACCEL_P=$$p ===================="; \
			$(MAKE) --no-print-directory TOP=$$top ACCEL_P=$$p \
				SIM_BUILD=sim_build/$${top}_p$$p \
				COCOTB_RESULTS_FILE=results_$${top}_p$$p.xml \
				results_$${top}_p$$p.xml; \
		done; \
	done
