// Observe the fixed D12 C++ XRT call during vx_device_open. Forward the
// unchanged return value and preserve driver exceptions. No additional MMIO.
#include <cstdint>
#include <dlfcn.h>
#include <stdexcept>

namespace {
constexpr unsigned device_caps = 0x1008;
constexpr char read_symbol[] = "_ZNK3xrt2ip13read_registerEj";
using ReadRegister = std::uint32_t (*)(const void*, unsigned);

ReadRegister original_read() {
    // D12 has already loaded this dependency when it calls xrt::ip. Looking
    // up the symbol on that handle also works with the stub's local dlopen.
    auto* provider = dlopen("libxrt_coreutil.so.2", RTLD_LAZY | RTLD_NOLOAD);
    if (!provider)
        throw std::runtime_error("D12 XRT register provider is unavailable");
    auto read = reinterpret_cast<ReadRegister>(dlsym(provider, read_symbol));
    if (!read)
        throw std::runtime_error("D12 XRT register symbol is unavailable");
    return read;  // Keep the provider referenced for the life of the worker.
}

thread_local bool observing = false;
thread_local unsigned reads = 0;
thread_local std::uint32_t raw = 0;
}

extern "C" void u280_cp_caps_begin() {
    reads = 0;
    raw = 0;
    observing = true;
}

extern "C" unsigned u280_cp_caps_end(std::uint32_t* value) {
    observing = false;
    *value = raw;
    return reads;
}

extern "C" std::uint32_t observed_read(const void*, unsigned)
    asm("_ZNK3xrt2ip13read_registerEj");

extern "C" std::uint32_t observed_read(const void* ip, unsigned offset) {
    static const auto read = original_read();
    const auto value = read(ip, offset);
    if (observing && offset == device_caps) {
        ++reads;
        raw = value;
    }
    return value;
}
