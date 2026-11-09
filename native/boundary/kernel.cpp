#include <vx_spawn2.h>
#include "common.h"

__kernel void kernel_main(boundary_args* __UNIFORM__ arg) {
  uint32_t bid = blockIdx.x;
  uint32_t tid = threadIdx.x;
  uint32_t b = blockDim.x;
  uint32_t g = gridDim.x;
  uint32_t i = bid * b + tid;
  auto audit = reinterpret_cast<uint32_t*>(arg->audit_addr);
  audit[4 * i] = bid;
  audit[4 * i + 1] = tid;
  audit[4 * i + 2] = b;
  audit[4 * i + 3] = g;

  bool active = i < arg->n && arg->predicate != 1;
  if (arg->predicate == 2)
    active = active && ((i & 1) == 0);
  if (active) {
    auto x = reinterpret_cast<const uint32_t*>(arg->x_addr);
    auto y = reinterpret_cast<const uint32_t*>(arg->y_addr);
    auto z = reinterpret_cast<uint32_t*>(arg->z_addr);
    uint32_t value = x[i];
    if (arg->operation == 1)
      value = value + y[i];
    if (arg->operation == 2)
      value = arg->alpha * value + y[i];
    z[i] = value;
  }
}
