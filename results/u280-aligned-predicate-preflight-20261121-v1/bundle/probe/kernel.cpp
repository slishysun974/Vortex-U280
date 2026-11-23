#include <stdint.h>
#include <vx_spawn2.h>
#include <vx_intrinsics.h>

__kernel void kernel_main(const uint8_t* __UNIFORM__ payload) {
  if (threadIdx.x == 0 && blockIdx.x == 0) {
    uintptr_t output = 0;
    for (unsigned i = 0; i != 8; ++i)
      output |= uintptr_t(payload[i]) << (8 * i);
    auto* words = reinterpret_cast<volatile uint32_t*>(output);
    const uint64_t a0 = uintptr_t(payload);
    const uint64_t mscratch = csr_read(VX_CSR_MSCRATCH);
    words[0] = uint32_t(a0);
    words[1] = uint32_t(a0 >> 32);
    words[2] = uint32_t(mscratch);
    words[3] = uint32_t(mscratch >> 32);
  }
}
