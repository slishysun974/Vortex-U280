// Generated Vortex2 adapter; compile with the pinned +xvortex toolchain.
#include <vx_spawn2.h>
#include "kernel_body.hpp"
static_assert(sizeof(uintptr_t) == 8, "PTX64 requires RV64");
struct PtxGlobalMemory {
  uint32_t load32(uint64_t address) {
    return *reinterpret_cast<const volatile uint32_t*>(uintptr_t(address));
  }
  void store32(uint64_t address, uint32_t value) {
    *reinterpret_cast<volatile uint32_t*>(uintptr_t(address)) = value;
  }
};
__kernel void kernel_main(const uint8_t* __UNIFORM__ payload) {
  PtxThread thread{uint32_t(threadIdx.x), uint32_t(blockDim.x),
                   uint32_t(blockIdx.x), uint32_t(gridDim.x)};
  PtxGlobalMemory memory;
  ptx_body(payload, thread, memory);
}
