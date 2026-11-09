#include <vortex2.h>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>
#include <cstdlib>
#include "common.h"

#define CHECK(expr) do { auto rc = (expr); if (rc != VX_SUCCESS) { \
  std::cerr << #expr << " returned " << rc << std::endl; std::exit(2); } } while (false)

static std::vector<uint32_t> read_words(const std::string& path, uint32_t count) {
  std::vector<uint32_t> words(count);
  std::ifstream file(path, std::ios::binary);
  if (!file.read(reinterpret_cast<char*>(words.data()), count * sizeof(uint32_t)) ||
      file.peek() != std::char_traits<char>::eof()) {
    std::cerr << "Invalid input: " << path << std::endl;
    std::exit(3);
  }
  return words;
}

static void write_words(const std::string& path, const std::vector<uint32_t>& words) {
  std::ofstream file(path, std::ios::binary);
  file.write(reinterpret_cast<const char*>(words.data()), words.size() * sizeof(uint32_t));
  file.close();
  if (!file) { std::cerr << "Cannot write " << path << std::endl; std::exit(3); }
}

int main(int argc, char** argv) {
  if (argc != 3) return 3;
  const std::string inputs = argv[1], outputs = argv[2];
  std::ifstream cases(inputs + "/cases.tsv");
  if (!cases) return 3;
  vx_device_h device = nullptr;
  vx_queue_h queue = nullptr;
  vx_module_h module = nullptr;
  vx_kernel_h kernel = nullptr;
  CHECK(vx_device_open(0, &device));
  vx_queue_info_t qi = {sizeof(qi), nullptr, VX_QUEUE_PRIORITY_NORMAL, 0};
  CHECK(vx_queue_create(device, &qi, &queue));
  CHECK(vx_module_load_file(device, "kernel.vxbin", &module));
  CHECK(vx_module_get_kernel(module, "main", &kernel));
  uint64_t nt = 0, nw = 0, nc = 0;
  CHECK(vx_device_query(device, VX_CAPS_NUM_THREADS, &nt));
  CHECK(vx_device_query(device, VX_CAPS_NUM_WARPS, &nw));
  CHECK(vx_device_query(device, VX_CAPS_NUM_CORES, &nc));
  std::cout << "CAPS threads=" << nt << " warps=" << nw << " cores=" << nc << std::endl;
  if (nt != VX_CFG_NUM_THREADS || nw != VX_CFG_NUM_WARPS ||
      nc != VX_CFG_NUM_CORES * VX_CFG_NUM_CLUSTERS) return 4;
  const uint32_t block_limit = VX_CFG_NUM_THREADS * VX_CFG_NUM_WARPS;

  // Keep the same allocations, module, device and queue across every launch.
  const uint32_t max_words = 1056, max_audit_words = 4112;
  vx_buffer_h buffers[4] = {};
  uint64_t addresses[4] = {};
  for (int j = 0; j < 4; ++j) {
    CHECK(vx_buffer_create(device, (j == 3 ? max_audit_words : max_words) * 4,
                           VX_MEM_READ_WRITE, &buffers[j]));
    CHECK(vx_buffer_address(buffers[j], &addresses[j]));
    std::cout << "BUFFER " << j << " address=" << addresses[j] << std::endl;
  }
  std::string id;
  uint32_t op, n, block, grid, alpha, pred, words, audit_words;
  unsigned count = 0;
  while (cases >> id >> op >> n >> block >> grid >> alpha >> pred >> words >> audit_words) {
    if (words > max_words || audit_words > max_audit_words || block == 0 || block > block_limit ||
        grid == 0 || uint64_t(block) * grid > 1024 || op > 2 || pred > 2 ||
        n > uint64_t(block) * grid || id.find_first_not_of("0123456789") != std::string::npos)
      return 3;
    const std::string names[4] = {"x", "y", "z", "audit"};
    std::vector<uint32_t> data[4];
    for (int j = 0; j < 4; ++j) {
      data[j] = read_words(inputs + "/" + id + "_" + names[j] + ".bin", j == 3 ? audit_words : words);
      CHECK(vx_enqueue_write(queue, buffers[j], 0, data[j].data(), data[j].size() * 4, 0, nullptr, nullptr));
    }
    boundary_args args = {addresses[0] + 32, addresses[1] + 32, addresses[2] + 32,
                          addresses[3] + 32, n, op, alpha, pred};
    vx_launch_info_t li = {};
    li.struct_size = sizeof(li);
    li.kernel = kernel;
    li.args_host = &args;
    li.args_size = sizeof(args);
    li.ndim = 1;
    li.grid_dim[0] = grid;
    li.block_dim[0] = block;
    vx_event_h launched = nullptr;
    CHECK(vx_enqueue_launch(queue, &li, 0, nullptr, &launched));
    CHECK(vx_event_wait_value(launched, 1, 60000000000ULL));
    CHECK(vx_event_release(launched));
    for (int j = 0; j < 4; ++j)
      CHECK(vx_enqueue_read(queue, data[j].data(), buffers[j], 0, data[j].size() * 4, 0, nullptr, nullptr));
    CHECK(vx_queue_finish(queue, 60000000000ULL));
    for (int j = 0; j < 4; ++j)
      write_words(outputs + "/" + id + "_" + names[j] + ".bin", data[j]);
    std::cout << "CAPTURED " << id << " n=" << n << " block=" << block << " grid=" << grid << std::endl;
    ++count;
  }
  if (!cases.eof() || count == 0) return 3;

  boundary_args args = {addresses[0] + 32, addresses[1] + 32, addresses[2] + 32,
                        addresses[3] + 32, 0, 0, 1, 1};
  vx_launch_info_t rejected = {};
  rejected.struct_size = sizeof(rejected);
  rejected.kernel = kernel;
  rejected.args_host = &args;
  rejected.args_size = sizeof(args);
  rejected.ndim = 1;
  rejected.grid_dim[0] = 1;
  for (auto block : {block_limit + 1, block_limit * 2}) {
    rejected.block_dim[0] = block;
    auto rc = vx_enqueue_launch(queue, &rejected, 0, nullptr, nullptr);
    std::cout << "BLOCK_REJECTION block=" << block << " actual=" << rc
              << " expected=" << VX_ERR_INVALID_VALUE << std::endl;
    if (rc != VX_ERR_INVALID_VALUE) return 5;
  }
  for (auto buffer : buffers) CHECK(vx_buffer_release(buffer));
  CHECK(vx_kernel_release(kernel));
  CHECK(vx_module_release(module));
  CHECK(vx_queue_release(queue));
  CHECK(vx_device_release(device));
  std::cout << "CAPTURE_COMPLETE " << count << std::endl;
  return 0;
}
