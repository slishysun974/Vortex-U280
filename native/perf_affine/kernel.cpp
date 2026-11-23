#include <cstddef>
#include <cstdint>
#include <vx_spawn2.h>

struct AffineArgs {
  uint64_t x;
  uint64_t y;
  uint64_t z;
  uint32_t n;
  uint32_t alpha;
};

static_assert(sizeof(uintptr_t) == 8, "The paired kernel uses RV64 device addresses");
static_assert(sizeof(AffineArgs) == 32 && offsetof(AffineArgs, x) == 0 &&
              offsetof(AffineArgs, y) == 8 && offsetof(AffineArgs, z) == 16 &&
              offsetof(AffineArgs, n) == 24 && offsetof(AffineArgs, alpha) == 28,
              "Match the affine_u32 PTX argument layout");

__kernel void kernel_main(const AffineArgs* __UNIFORM__ args) {
  const uint32_t index = uint32_t(blockIdx.x) * uint32_t(blockDim.x) + uint32_t(threadIdx.x);
  if (index < args->n) {
    const auto* x = reinterpret_cast<const uint32_t*>(args->x);
    const auto* y = reinterpret_cast<const uint32_t*>(args->y);
    auto* z = reinterpret_cast<uint32_t*>(args->z);
    z[index] = args->alpha * x[index] + y[index];
  }
}
