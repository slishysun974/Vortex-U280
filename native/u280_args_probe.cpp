#include <stdint.h>
#include <vx_intrinsics.h>
#include <vx_spawn2.h>

static uint64_t read_bytes(const volatile uint8_t* field, unsigned size) {
    uint64_t value = 0;
    for (unsigned i = 0; i < size; ++i)
        value |= uint64_t(field[i]) << (8 * i);
    return value;
}

static void write_word(volatile uint32_t*& out, uint64_t value) {
    *out++ = uint32_t(value);
    *out++ = uint32_t(value >> 32);
}

static void report_field(volatile uint32_t*& out, const uint8_t* field, unsigned size) {
    write_word(out, uintptr_t(field));
    write_word(out, read_bytes(field, size));
}

// block.x chooses the original ABI while leaving the queue payload untouched.
// Only lane zero reports. All parameter bytes are read individually.
__kernel void kernel_main(const uint8_t* __UNIFORM__ payload) {
    if (threadIdx.x != 0 || blockIdx.x != 0)
        return;
    const unsigned layout = blockDim.x;
    auto* out = reinterpret_cast<volatile uint32_t*>(uintptr_t(read_bytes(payload, 8)));
    write_word(out, uintptr_t(payload));
    write_word(out, csr_read(VX_CSR_MSCRATCH));
    report_field(out, payload, 8);
    report_field(out, payload + 8, 8);
    if (layout == 1) {
        report_field(out, payload + 16, 4);
    } else {
        report_field(out, payload + 16, 8);
        report_field(out, payload + 24, 4);
        if (layout == 3)
            report_field(out, payload + 28, 4);
    }
}
