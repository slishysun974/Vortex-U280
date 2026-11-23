// Read-only diagnostic for a later authorized U280 session. Requires the D10
// image to be loaded already and exclusive D12 Context access to be released.
#include <experimental/xrt_device.h>
#include <experimental/xrt_ip.h>
#include <cstdint>
#include <exception>
#include <iomanip>
#include <iostream>
#include <limits>
#include <string>

int main(int argc, char** argv) {
    if (argc != 3) {
        std::cerr << "usage: read_cp_caps XRT_INDEX EXPECTED_BDF\n";
        return 2;
    }
    try {
        constexpr const char* expected_uuid = "b60ca9fb-1506-3033-c156-e03ff687f492";
        const std::string number = argv[1];
        std::size_t consumed = 0;
        auto index = std::stoul(number, &consumed);
        if (number.empty() || number.find_first_not_of("0123456789") != std::string::npos ||
            consumed != number.size() || index > std::numeric_limits<unsigned>::max())
            return 2;
        auto device = xrt::device(static_cast<unsigned>(index));
        const auto bdf = device.get_info<xrt::info::device::bdf>();
        auto loaded = device.get_xclbin_uuid();
        if (bdf != argv[2] || loaded.to_string() != expected_uuid) {
            std::cerr << "BDF or loaded D10 UUID differs\n";
            return 3;
        }
        auto afu = xrt::ip(device, loaded, "vortex_afu");
        const std::uint32_t caps = afu.read_register(0x1008);
        std::cout << "bdf=" << bdf << " uuid=" << loaded.to_string() << " cp_dev_caps=0x"
                  << std::hex << std::setw(8) << std::setfill('0') << caps << '\n';
        // The fixed D10 decoder reserves the top byte and publishes nonempty
        // queue geometry in the low bytes. Error/sentinel/fallback values
        // cannot be accepted as a successful VM-off register read.
        if ((caps & 0xff000000u) != 0 || (caps & 0xffu) == 0 || (caps & 0xff00u) == 0 ||
            (caps & 0xff0000u) == 0)
            return 4;
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 5;
    }
}
