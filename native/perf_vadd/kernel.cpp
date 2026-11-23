#include <cstddef>
#include <cstdint>
#include <vx_spawn2.h>

struct VaddArgs {
  uint64_t x;
  uint64_t y;
  uint64_t z;
  uint32_t n;
};

static_assert(sizeof(uintptr_t) == 8, "The paired kernel uses RV64 device addresses");
static_assert(sizeof(VaddArgs) == 32 && offsetof(VaddArgs, x) == 0 &&
              offsetof(VaddArgs, y) == 8 && offsetof(VaddArgs, z) == 16 &&
              offsetof(VaddArgs, n) == 24, "Match the vadd_u32 PTX argument layout");

__kernel void kernel_main(const VaddArgs* __UNIFORM__ args) {
  const uint32_t index = uint32_t(blockIdx.x) * uint32_t(blockDim.x) + uint32_t(threadIdx.x);
  if (index < args->n) {
    const auto* x = reinterpret_cast<const uint32_t*>(args->x);
    const auto* y = reinterpret_cast<const uint32_t*>(args->y);
    auto* z = reinterpret_cast<uint32_t*>(args->z);
    z[index] = x[index] + y[index];
  }
}
