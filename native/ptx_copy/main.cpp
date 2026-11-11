#include <vortex2.h>

#include <array>
#include <cstdint>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <string>

#include "copy_case.hpp"

#define CHECK(expr) do { \
  const auto rc = (expr); \
  if (rc != VX_SUCCESS) { \
    std::cerr << #expr << " returned " << rc << '\n'; \
    std::exit(2); \
  } \
} while (false)

namespace {

using BufferBytes = std::array<uint8_t, copy_case::buffer_bytes>;
constexpr uint64_t timeout_ns = 30000000000ULL;

static_assert(copy_case::guard_bytes + copy_case::n * sizeof(uint32_t) <= copy_case::buffer_bytes);
static_assert(uint64_t{copy_case::grid} * copy_case::block >= copy_case::n);

BufferBytes read_input(const std::string& path) {
  BufferBytes bytes{};
  std::ifstream file(path, std::ios::binary);
  if (!file.read(reinterpret_cast<char*>(bytes.data()), bytes.size()) ||
      file.peek() != std::char_traits<char>::eof()) {
    std::cerr << "Invalid input size for " << path << '\n';
    std::exit(3);
  }
  return bytes;
}

template <size_t Size>
void write_output(const std::string& path, const std::array<uint8_t, Size>& bytes) {
  std::ofstream file(path, std::ios::binary);
  file.write(reinterpret_cast<const char*>(bytes.data()), bytes.size());
  file.close();
  if (!file) {
    std::cerr << "Cannot write " << path << '\n';
    std::exit(3);
  }
}

template <typename UInt>
void pack_le(uint8_t* dst, UInt value) {
  for (size_t i = 0; i < sizeof(value); ++i)
    dst[i] = static_cast<uint8_t>(value >> (8 * i));
}

uint64_t device_pointer(vx_buffer_h buffer) {
  uint64_t base = 0;
  CHECK(vx_buffer_address(buffer, &base));
  if (base % alignof(uint32_t) || base > UINT64_MAX - copy_case::buffer_bytes) {
    std::cerr << "Invalid device buffer address\n";
    std::exit(3);
  }
  return base + copy_case::guard_bytes;
}

}  // namespace

int main(int argc, char** argv) {
  if (argc != 3)
    return 3;
  const std::string inputs = std::string(argv[1]) + "/" + copy_case::id;
  const std::string outputs = std::string(argv[2]) + "/" + copy_case::id;
  std::array<BufferBytes, copy_case::buffers.size()> data{};
  std::array<vx_buffer_h, copy_case::buffers.size()> buffers{};
  for (size_t i = 0; i < buffers.size(); ++i)
    data[i] = read_input(inputs + "_" + copy_case::buffers[i].name + ".bin");

  vx_device_h device = nullptr;
  vx_queue_h queue = nullptr;
  vx_module_h module = nullptr;
  vx_kernel_h kernel = nullptr;
  CHECK(vx_device_open(0, &device));
  uint64_t threads = 0, warps = 0, cores = 0;
  CHECK(vx_device_query(device, VX_CAPS_NUM_THREADS, &threads));
  CHECK(vx_device_query(device, VX_CAPS_NUM_WARPS, &warps));
  CHECK(vx_device_query(device, VX_CAPS_NUM_CORES, &cores));
  std::cout << "CAPS threads=" << threads << " warps=" << warps << " cores=" << cores << '\n';
  if (threads != 4 || warps != 8 || cores != 1 || copy_case::block > threads * warps)
    return 4;

  vx_queue_info_t queue_info{sizeof(queue_info), nullptr, VX_QUEUE_PRIORITY_NORMAL, 0};
  CHECK(vx_queue_create(device, &queue_info, &queue));
  CHECK(vx_module_load_file(device, "kernel.vxbin", &module));
  CHECK(vx_module_get_kernel(module, copy_case::entry, &kernel));
  uint64_t entry = 0;
  CHECK(vx_kernel_address(kernel, &entry));
  std::cout << "PTX_COPY_ENTRY " << entry << '\n';

  std::array<uint8_t, copy_case::params_size> payload{};
  std::string args = "PTX_COPY_ARGS";
  for (size_t i = 0; i < buffers.size(); ++i) {
    const auto& spec = copy_case::buffers[i];
    CHECK(vx_buffer_create(device, data[i].size(), VX_MEM_READ_WRITE, &buffers[i]));
    const auto pointer = device_pointer(buffers[i]);
    pack_le(payload.data() + spec.offset, pointer);
    args += std::string(" ") + spec.name + "=" + std::to_string(pointer);
  }
  for (const auto& spec : copy_case::scalars) {
    pack_le(payload.data() + spec.offset, spec.value);
    args += std::string(" ") + spec.name + "=" + std::to_string(spec.value);
  }
  std::cout << args << '\n';
  for (size_t i = 0; i < buffers.size(); ++i)
    CHECK(vx_enqueue_write(queue, buffers[i], 0, data[i].data(), data[i].size(), 0, nullptr, nullptr));

  vx_launch_info_t launch{};
  launch.struct_size = sizeof(launch);
  launch.kernel = kernel;
  launch.args_host = payload.data();
  launch.args_size = payload.size();
  launch.ndim = 1;
  launch.grid_dim[0] = copy_case::grid;
  launch.block_dim[0] = copy_case::block;
  vx_event_h event = nullptr;
  CHECK(vx_enqueue_launch(queue, &launch, 0, nullptr, &event));
  CHECK(vx_event_wait_value(event, 1, timeout_ns));
  CHECK(vx_event_release(event));
  for (size_t i = 0; i < buffers.size(); ++i)
    CHECK(vx_enqueue_read(queue, data[i].data(), buffers[i], 0, data[i].size(), 0, nullptr, nullptr));
  CHECK(vx_queue_finish(queue, timeout_ns));
  for (size_t i = 0; i < buffers.size(); ++i)
    write_output(outputs + "_" + copy_case::buffers[i].name + ".bin", data[i]);
  write_output(outputs + "_params.bin", payload);

  for (auto buffer : buffers)
    CHECK(vx_buffer_release(buffer));
  CHECK(vx_kernel_release(kernel));
  CHECK(vx_module_release(module));
  CHECK(vx_queue_release(queue));
  CHECK(vx_device_release(device));
  std::cout << "CAPTURED " << copy_case::id << " n=" << copy_case::n
            << " block=" << copy_case::block << " grid=" << copy_case::grid << '\n'
            << "CAPTURE_COMPLETE 1" << std::endl;
}
