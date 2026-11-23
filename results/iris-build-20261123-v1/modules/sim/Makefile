# ROOT_DIR must be the isolated, configured Vortex build root.
ifndef ROOT_DIR
$(error supply ROOT_DIR pointing to an isolated configured Vortex build)
endif
include $(ROOT_DIR)/config.mk
PROJECT := ptx_module
SRC_DIR := .
SRCS :=
VX_SRCS := kernel.cpp
VX_HDRS := kernel_body.hpp
KERNEL_LIB := vortex2
VX_CFLAGS += -std=c++17
include $(VORTEX_HOME)/tests/regression/common.mk
