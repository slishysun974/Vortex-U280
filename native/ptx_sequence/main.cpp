#include <vortex2.h>
#include <algorithm>
#include <array>
#include <cstdint>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>
#include "sequence.hpp"

#define CHECK(expr) do { const auto rc = (expr); if (rc != VX_SUCCESS) { \
  std::cerr << #expr << " returned " << rc << std::endl; std::exit(2); } } while (false)

namespace {
constexpr uint64_t timeout_ns = 30000000000ULL;
using Bytes = std::vector<uint8_t>;
constexpr std::array<const char*, 3> names{{"x", "y", "z"}};

Bytes read(const std::string& path) {
  Bytes data(sequence::buffer_bytes);
  std::ifstream f(path, std::ios::binary);
  if (!f.read(reinterpret_cast<char*>(data.data()), data.size()) ||
      f.peek() != std::char_traits<char>::eof()) {
    std::cerr << "Invalid input " << path << std::endl; std::exit(3);
  }
  return data;
}
void write(const std::string& path, const uint8_t* data, size_t size) {
  std::ofstream f(path, std::ios::binary);
  f.write(reinterpret_cast<const char*>(data), size); f.close();
  if (!f) { std::cerr << "Cannot write " << path << std::endl; std::exit(3); }
}
template<typename T> void pack(uint8_t* dst, T value) {
  for (size_t i = 0; i < sizeof(T); ++i) dst[i] = static_cast<uint8_t>(value >> (i * 8));
}
}

int main(int argc, char** argv) {
  if (argc != 3) return 3;
  vx_device_h device = nullptr;
  vx_queue_h queue = nullptr;
  vx_module_h module = nullptr;
  vx_kernel_h kernel = nullptr;
  std::array<vx_buffer_h, 3> buffers{};
  std::array<uint64_t, 3> pointers{};
  std::array<Bytes, 3> data;
  CHECK(vx_device_open(0, &device));
  std::cout << "SEQUENCE_DEVICE_OPEN 1" << std::endl;
  uint64_t threads = 0, warps = 0, cores = 0;
  CHECK(vx_device_query(device, VX_CAPS_NUM_THREADS, &threads));
  CHECK(vx_device_query(device, VX_CAPS_NUM_WARPS, &warps));
  CHECK(vx_device_query(device, VX_CAPS_NUM_CORES, &cores));
  if (threads != 4 || warps != 8 || cores != 1) return 4;
  vx_queue_info_t qi{sizeof(qi), nullptr, VX_QUEUE_PRIORITY_NORMAL, 0};
  CHECK(vx_queue_create(device, &qi, &queue));
  std::string loaded;
  uint32_t generation = 0;
  auto release_module = [&]() {
    if (kernel) { CHECK(vx_kernel_release(kernel)); kernel = nullptr; }
    if (module) { CHECK(vx_module_release(module)); module = nullptr; }
  };
  for (const auto& c : sequence::cases) {
    if (c.generation != generation) {
      CHECK(vx_queue_finish(queue, timeout_ns));
      for (auto& buffer : buffers) {
        if (buffer) CHECK(vx_buffer_release(buffer));
        buffer = nullptr;
        CHECK(vx_buffer_create(device, sequence::buffer_bytes, VX_MEM_READ_WRITE, &buffer));
      }
      generation = c.generation;
      for (size_t i = 0; i < buffers.size(); ++i) {
        uint64_t base = 0;
        CHECK(vx_buffer_address(buffers[i], &base));
        if (base % 4 || base > UINT64_MAX - sequence::buffer_bytes) return 4;
        pointers[i] = base + 32;
      }
      std::cout << "SEQUENCE_BUFFERS generation=" << generation << " x=" << pointers[0]
                << " y=" << pointers[1] << " z=" << pointers[2] << std::endl;
    }
    std::cout << "SEQUENCE_BEGIN " << c.id << std::endl;
    if (loaded != c.entry) {
      release_module();
      const std::string image = std::string(c.entry) + ".vxbin";
      CHECK(vx_module_load_file(device, image.c_str(), &module));
      CHECK(vx_module_get_kernel(module, c.entry, &kernel));
      loaded = c.entry;
      std::cout << "SEQUENCE_MODULE " << c.id << " entry=" << c.entry << std::endl;
    }
    uint64_t pc = 0;
    CHECK(vx_kernel_address(kernel, &pc));
    const std::string input = std::string(argv[1]) + "/" + c.id;
    const std::string output = std::string(argv[2]) + "/" + c.id;
    for (size_t i = 0; i < buffers.size(); ++i) {
      data[i] = read(input + "_" + names[i] + ".bin");
      CHECK(vx_enqueue_write(queue, buffers[i], 0, data[i].data(), data[i].size(), 0, nullptr, nullptr));
    }
    CHECK(vx_queue_finish(queue, timeout_ns));
    std::array<uint8_t, 32> payload{};
    const bool copy = loaded == "copy_u32";
    pack(payload.data(), pointers[0]);
    pack(payload.data() + 8, copy ? pointers[2] : pointers[1]);
    if (!copy) pack(payload.data() + 16, pointers[2]);
    pack(payload.data() + (copy ? 16 : 24), c.n);
    if (loaded == "affine_u32") pack(payload.data() + 28, c.alpha);
    const size_t payload_size = copy ? 24 : 32;
    write(output + "_params.bin", payload.data(), payload_size);
    vx_launch_info_t launch{};
    launch.struct_size = sizeof(launch); launch.kernel = kernel;
    launch.args_host = payload.data(); launch.args_size = payload_size;
    launch.ndim = 1; launch.grid_dim[0] = c.grid; launch.block_dim[0] = c.block;
    if (c.reject) {
      for (const uint32_t block : {33u, 64u}) {
        auto bad = launch; bad.block_dim[0] = block;
        vx_event_h rejected = nullptr;
        auto rc = vx_enqueue_launch(queue, &bad, 0, nullptr, &rejected);
        std::cout << "SEQUENCE_REJECT " << c.id << " block=" << block << " rc=" << rc
                  << " event_null=" << (rejected == nullptr) << std::endl;
        if (rc != VX_ERR_INVALID_VALUE || rejected != nullptr) return 5;
      }
      for (size_t i = 0; i < buffers.size(); ++i)
        CHECK(vx_enqueue_read(queue, data[i].data(), buffers[i], 0, data[i].size(), 0, nullptr, nullptr));
      CHECK(vx_queue_finish(queue, timeout_ns));
      for (size_t i = 0; i < buffers.size(); ++i)
        write(output + "_reject_" + names[i] + ".bin", data[i].data(), data[i].size());
    }
    std::cout << "SEQUENCE_LAUNCH " << c.id << " entry=" << c.entry << " pc=" << pc
              << " n=" << c.n << " block=" << c.block << " grid=" << c.grid
              << " generation=" << generation << std::endl;
    vx_event_h event = nullptr;
    CHECK(vx_enqueue_launch(queue, &launch, 0, nullptr, &event));
    // The fixed API promises capture on enqueue. Deliberately reuse both host objects.
    std::fill(payload.begin(), payload.end(), 0xa5);
    launch = {};
    CHECK(vx_event_wait_value(event, 1, timeout_ns));
    CHECK(vx_event_release(event));
    for (size_t i = 0; i < buffers.size(); ++i)
      CHECK(vx_enqueue_read(queue, data[i].data(), buffers[i], 0, data[i].size(), 0, nullptr, nullptr));
    CHECK(vx_queue_finish(queue, timeout_ns));
    for (size_t i = 0; i < buffers.size(); ++i)
      write(output + "_" + names[i] + ".bin", data[i].data(), data[i].size());
    std::cout << "CAPTURED " << c.id << " n=" << c.n << " block=" << c.block
              << " grid=" << c.grid << '\n' << "SEQUENCE_END " << c.id << std::endl;
  }
  release_module();
  for (auto buffer : buffers) CHECK(vx_buffer_release(buffer));
  CHECK(vx_queue_release(queue)); CHECK(vx_device_release(device));
  std::cout << "SEQUENCE_DEVICE_CLOSE 1\nCAPTURE_COMPLETE " << sequence::cases.size() << std::endl;
}
