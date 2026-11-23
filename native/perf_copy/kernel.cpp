#include <cstddef>
#include <cstdint>
#include <vx_spawn2.h>

struct CopyArgs {
  uint64_t x;
  uint64_t z;
  uint32_t n;
};

static_assert(sizeof(uintptr_t) == 8, "The paired kernel uses RV64 device addresses");
static_assert(sizeof(CopyArgs) == 24 && offsetof(CopyArgs, x) == 0 &&
              offsetof(CopyArgs, z) == 8 && offsetof(CopyArgs, n) == 16,
              "Match the copy_u32 PTX argument layout");

__kernel void kernel_main(const CopyArgs* __UNIFORM__ args) {
  const uint32_t index = uint32_t(blockIdx.x) * uint32_t(blockDim.x) + uint32_t(threadIdx.x);
  if (index < args->n) {
    const auto* x = reinterpret_cast<const uint32_t*>(args->x);
    auto* z = reinterpret_cast<uint32_t*>(args->z);
    z[index] = x[index];
  }
}
