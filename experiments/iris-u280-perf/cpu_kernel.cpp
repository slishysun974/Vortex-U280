#include <cstddef>
#include <cstdint>

// Unsigned products are exact on the admitted 0..100 mm feature domain.
extern "C" void iris_cpu(const std::uint32_t* __restrict x, const std::uint32_t* __restrict sums,
                         std::uint32_t* __restrict output, std::size_t n) {
    for (std::size_t i = 0; i < n; ++i) {
        std::uint32_t distances[3] = {};
        for (unsigned c = 0; c < 3; ++c) {
            for (unsigned j = 0; j < 4; ++j) {
                const int delta = static_cast<int>(35 * x[4*i+j]) - static_cast<int>(sums[4*c+j]);
                distances[c] += static_cast<std::uint32_t>(delta * delta);
            }
            output[4*i+c] = distances[c];
        }
        unsigned winner = distances[1] < distances[0] ? 1 : 0;
        output[4*i+3] = distances[2] < distances[winner] ? 2 : winner;
    }
}
