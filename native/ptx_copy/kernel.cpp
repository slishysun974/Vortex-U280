#include <vx_spawn2.h>

// PTX may declare unused registers and lower a same-register cvta to a no-op.
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wself-assign"
#pragma clang diagnostic ignored "-Wunused-variable"
#include "kernel_body.hpp"
#pragma clang diagnostic pop

struct DeviceMemory {
  uint32_t load32(uint64_t address) const {
    return *reinterpret_cast<const volatile uint32_t*>(address);
  }

  void store32(uint64_t address, uint32_t value) const {
    *reinterpret_cast<volatile uint32_t*>(address) = value;
  }
};

#ifndef PTX_ENTRY
#define PTX_ENTRY copy_u32
#endif

__kernel void PTX_ENTRY(const uint8_t* __UNIFORM__ payload) {
  const PtxThread thread{threadIdx.x, blockDim.x, blockIdx.x, gridDim.x};
  DeviceMemory memory;
  ptx_body(payload, thread, memory);
}
