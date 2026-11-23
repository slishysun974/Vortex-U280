#include <xrt/xrt_device.h>
#include <iostream>
#include <cstdlib>
int main(int argc, char** argv) {
  if (argc != 2) return 2;
  try {
    auto device = xrt::device(static_cast<unsigned>(std::stoul(argv[1])));
    std::cout << device.get_info<xrt::info::device::bdf>() << std::endl;
  } catch (const std::exception& error) { std::cerr << error.what() << std::endl; return 3; }
}
