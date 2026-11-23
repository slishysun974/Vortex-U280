#include <cstddef>
#include <cstdint>
#include <vx_spawn2.h>

struct IrisArgs {
    uint64_t x;
    uint64_t sums;
    uint64_t out;
    uint32_t n;
};

static_assert(sizeof(uintptr_t) == 8, "Iris requires RV64 device addresses");
static_assert(sizeof(IrisArgs) == 32 && offsetof(IrisArgs, x) == 0 &&
              offsetof(IrisArgs, sums) == 8 && offsetof(IrisArgs, out) == 16 &&
              offsetof(IrisArgs, n) == 24, "Match the frozen Iris parameter layout");

__kernel void kernel_main(const IrisArgs* __UNIFORM__ args) {
    const uint32_t row = uint32_t(blockIdx.x) * uint32_t(blockDim.x) + uint32_t(threadIdx.x);
    if (row < args->n) {
        const auto* x = reinterpret_cast<const uint32_t*>(args->x) + uint64_t(row) * 4;
        const auto* sums = reinterpret_cast<const uint32_t*>(args->sums);
        auto* out = reinterpret_cast<uint32_t*>(args->out) + uint64_t(row) * 4;
        uint32_t scaled[4];
        uint32_t distances[3];
#pragma unroll
        for (unsigned j = 0; j < 4; ++j) {
            scaled[j] = 35u * x[j];
        }
#pragma unroll
        for (unsigned c = 0; c < 3; ++c) {
            uint32_t distance = 0;
#pragma unroll
            for (unsigned j = 0; j < 4; ++j) {
                // In u32 arithmetic, either subtraction order gives the same low square.
                const uint32_t delta = scaled[j] - sums[4 * c + j];
                distance += delta * delta;
            }
            distances[c] = distance;
        }
        const bool better1 = distances[1] < distances[0];
        const uint32_t best = better1 ? distances[1] : distances[0];
        out[0] = distances[0];
        out[1] = distances[1];
        out[2] = distances[2];
        out[3] = distances[2] < best ? 2u : uint32_t(better1);
    }
}
