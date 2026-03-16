# Build and run Verilator testbench for approx_adder.v
# Usage: make [ADDER_LENGTH=8] [NUM_SAMPLES=0]
#  NUM_SAMPLES=0 means exhaustive for 8-bit, else random sample count.

VERILATOR ?= verilator
VTOP ?= approx_adder
SRC_V ?= approx_adder.v
TB_CPP ?= tb_adder.cpp

VL_FLAGS = --cc --exe -o sim
OBJ_DIR = obj_dir

.PHONY: build run clean

build: $(SRC_V) $(TB_CPP)
	$(VERILATOR) $(VL_FLAGS) $(SRC_V) $(TB_CPP)
	$(MAKE) -C $(OBJ_DIR) -f V$(VTOP).mk

run: build
	./$(OBJ_DIR)/V$(VTOP) $(ADDER_LENGTH) $(NUM_SAMPLES)

clean:
	rm -rf $(OBJ_DIR)
