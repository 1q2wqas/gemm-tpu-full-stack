TOPLEVEL_LANG ?= verilog
SIM ?= icarus

# TOP selects one owner2 block without compiling unrelated modules.
TOP ?= a_buf
COCOTB_TEST_MODULES ?= tb_owner2

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
RTL_DIR   := $(REPO_ROOT)/rtl/owner2
INC_DIR   := $(REPO_ROOT)/rtl/include
TEST_DIR  := $(REPO_ROOT)/tests/owner2

export PYTHONPATH := $(TEST_DIR):$(SIM_DIR):$(PYTHONPATH)

SIM_BUILD := sim_build/$(TOP)
COCOTB_RESULTS_FILE ?= results_$(TOP).xml

COMPILE_ARGS += -I$(RTL_DIR) -I$(INC_DIR)
COMPILE_ARGS += -DACCEL_P=$(ACCEL_P)

ifeq ($(TOP),a_buf)
VERILOG_SOURCES = \
	$(RTL_DIR)/a_buf.v
endif

ifeq ($(TOP),b_buf)
VERILOG_SOURCES = \
	$(RTL_DIR)/b_buf.v
endif

ifeq ($(TOP),requant_relu_b)
VERILOG_SOURCES = \
    $(RTL_DIR)/rv_pipe_slice.v \
	$(RTL_DIR)/requant_relu_b.v
endif

ifeq ($(TOP),maxpool2x2_b)
VERILOG_SOURCES = \
	$(RTL_DIR)/maxpool2x2_b.v
endif

ifeq ($(TOP),stream_loader_A)
VERILOG_SOURCES = \
	$(RTL_DIR)/stream_loader_A.v
endif

ifeq ($(TOP),stream_loader_B)
VERILOG_SOURCES = \
	$(RTL_DIR)/stream_loader_B.v
endif

ifeq ($(TOP),stream_unloader_C_b)
VERILOG_SOURCES = \
	$(RTL_DIR)/stream_unloader_C_b.v
endif

TOPLEVEL = $(TOP)

ifeq ($(strip $(VERILOG_SOURCES)),)
$(error Unsupported TOP='$(TOP)'. Use a_buf, b_buf, requant_relu_b, maxpool2x2_b, stream_loader_A, stream_loader_B, or stream_unloader_C_b)
endif

include $(shell cocotb-config --makefiles)/Makefile.sim

# Only array-width-dependent blocks need the P sweep.
ACCEL_P_LIST ?= 1 2 4 8
P_SWEEP_TOP ?= stream_unloader_C_b

.PHONY: sweep_p
sweep_p:
	@set -e; \
	top="$(P_SWEEP_TOP)"; \
	for p in $(ACCEL_P_LIST); do \
		echo "==================== TOP=$$top ACCEL_P=$$p ===================="; \
		$(MAKE) --no-print-directory TOP=$$top ACCEL_P=$$p \
			SIM_BUILD=sim_build/$${top}_p$$p \
			COCOTB_RESULTS_FILE=results_$${top}_p$$p.xml \
			results_$${top}_p$$p.xml; \
	done
