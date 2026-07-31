TOPLEVEL_LANG ?= verilog
SIM    ?= icarus
TOP    ?= user_project_wrapper
COCOTB_TEST_MODULES ?= tb_golden

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
OWNER3_RTL_DIR := $(REPO_ROOT)/rtl/owner3
OWNER1_RTL_DIR := $(REPO_ROOT)/rtl/owner1_flow_v2
OWNER2_RTL_DIR := $(REPO_ROOT)/rtl/owner2
INC_DIR   := $(REPO_ROOT)/rtl/include
TEST_DIR  := $(REPO_ROOT)/tests/golden

export PYTHONPATH := $(TEST_DIR):$(SIM_DIR):$(PYTHONPATH)

SIM_BUILD ?= sim_build/$(TOP)_golden_p$(ACCEL_P)
COCOTB_RESULTS_FILE ?= results_$(TOP)_golden_p$(ACCEL_P).xml

COMPILE_ARGS += -I$(OWNER3_RTL_DIR) -I$(OWNER1_RTL_DIR) -I$(OWNER2_RTL_DIR) -I$(INC_DIR)
COMPILE_ARGS += -DACCEL_P=$(ACCEL_P)

WHOLE_GEMM_SOURCES = \
	$(OWNER3_RTL_DIR)/gemm_accel_top_b.v \
	$(OWNER1_RTL_DIR)/pe_mac.v \
	$(OWNER1_RTL_DIR)/mac_array_pxp.v \
	$(OWNER1_RTL_DIR)/gemm_core.v \
	$(OWNER2_RTL_DIR)/a_buf.v \
	$(OWNER2_RTL_DIR)/b_buf.v \
	$(OWNER2_RTL_DIR)/stream_loader_A.v \
	$(OWNER2_RTL_DIR)/stream_loader_B.v \
	$(OWNER2_RTL_DIR)/stream_unloader_C_b.v

WHOLE_PP_SOURCES = \
	$(OWNER2_RTL_DIR)/rv_pipe_slice.v \
	$(OWNER2_RTL_DIR)/requant_relu_b.v \
	$(OWNER2_RTL_DIR)/maxpool2x2_b.v

ifeq ($(TOP),gemm_accel_top_b)
VERILOG_SOURCES = $(WHOLE_GEMM_SOURCES)
endif

ifeq ($(TOP),tpu_wb_periph_b)
VERILOG_SOURCES = \
	$(OWNER3_RTL_DIR)/cfg_status_regs.v \
	$(OWNER3_RTL_DIR)/tpu_wb_periph_b.v \
	$(WHOLE_GEMM_SOURCES) \
	$(WHOLE_PP_SOURCES)
endif

ifeq ($(TOP),user_project_wrapper)
VERILOG_SOURCES = \
	$(OWNER3_RTL_DIR)/cfg_status_regs.v \
	$(OWNER3_RTL_DIR)/tpu_wb_periph_b.v \
	$(OWNER3_RTL_DIR)/user_project_wrapper.v \
	$(WHOLE_GEMM_SOURCES) \
	$(WHOLE_PP_SOURCES)
COMPILE_ARGS += -DMPRJ_IO_PADS=38
endif

TOPLEVEL = $(TOP)

ifeq ($(strip $(VERILOG_SOURCES)),)
$(error Unsupported TOP='$(TOP)'. Use gemm_accel_top_b, tpu_wb_periph_b, or user_project_wrapper)
endif

include $(shell cocotb-config --makefiles)/Makefile.sim

ACCEL_P_LIST ?= 1 2 4 8
P_SWEEP_TOPS ?= tpu_wb_periph_b user_project_wrapper

.PHONY: sweep_p
sweep_p:
	@set -e; \
	for top in $(P_SWEEP_TOPS); do \
		for p in $(ACCEL_P_LIST); do \
			echo "==================== GOLDEN TOP=$$top ACCEL_P=$$p ===================="; \
			$(MAKE) --no-print-directory TOP=$$top ACCEL_P=$$p \
				SIM_BUILD=sim_build/$${top}_golden_p$$p \
				COCOTB_RESULTS_FILE=results_$${top}_golden_p$$p.xml \
				results_$${top}_golden_p$$p.xml; \
		done; \
	done
