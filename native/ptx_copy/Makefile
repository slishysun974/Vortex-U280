include $(ROOT_DIR)/config.mk

PROJECT := ptx_copy
VX_SRCS := kernel.cpp
VX_HDRS := kernel_body.hpp
KERNEL_LIB := vortex2

include $(ROOT_DIR)/tests/regression/common.mk

ifneq ($(PTX_ENTRY),)
VX_CFLAGS += -DPTX_ENTRY=$(PTX_ENTRY)
endif
