// CPU semantic audit of generated code. This is not a Vortex backend.
#include <cstdint>
#include <fstream>
#include <iostream>
#include <iterator>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>
#include "kernel_body.hpp"

static std::vector<uint8_t> read_file(const std::string& path) {
  std::ifstream in(path, std::ios::binary);
  if (!in) throw std::runtime_error("cannot read " + path);
  return std::vector<uint8_t>(std::istreambuf_iterator<char>(in), {});
}
static void write_file(const std::string& path, const std::vector<uint8_t>& bytes) {
  std::ofstream out(path, std::ios::binary);
  out.write(reinterpret_cast<const char*>(bytes.data()), bytes.size());
  if (!out) throw std::runtime_error("cannot write " + path);
}
struct Memory {
  static constexpr uint64_t base = UINT64_C(0x123400000000);
  std::vector<uint8_t> arrays[3];
  uint32_t n, bid = 0, tid = 0;
  uint64_t loads = 0, stores = 0;
  std::string id;
  std::ostream& trace;
  Memory(uint32_t length, const std::string& name, std::ostream& output): n(length), id(name), trace(output) {}
  uint8_t* address(uint64_t addr, bool write) {
    for (unsigned k = 0; k < 3; ++k) {
      const uint64_t first = base + k * UINT64_C(0x100000) + 32;
      if (addr >= first && addr - first < uint64_t(n) * 4 && (addr & 3) == 0) {
        if (write && k != 2) throw std::runtime_error("unexpected write to input");
        auto offset = addr - (first - 32);
        if (offset + 4 > arrays[k].size()) throw std::runtime_error("capture buffer too short");
        return arrays[k].data() + offset;
      }
    }
    throw std::runtime_error("out-of-range or unaligned active memory access");
  }
  uint32_t load32(uint64_t addr) {
    auto* p = address(addr, false);
    uint32_t value = uint32_t(p[0]) | (uint32_t(p[1]) << 8) | (uint32_t(p[2]) << 16) | (uint32_t(p[3]) << 24);
    ++loads;
    trace << id << '\t' << bid << '\t' << tid << "\tload\t" << addr << '\t' << value << '\n';
    return value;
  }
  void store32(uint64_t addr, uint32_t value) {
    auto* p = address(addr, true);
    for (unsigned j = 0; j < 4; ++j) p[j] = uint8_t(value >> (8 * j));
    ++stores;
    trace << id << '\t' << bid << '\t' << tid << "\tstore\t" << addr << '\t' << value << '\n';
  }
};
int main(int argc, char** argv) {
  try {
    if (argc != 4) throw std::runtime_error("usage: audit cases.tsv inputs actual");
    std::ifstream table(argv[1]);
    if (!table) throw std::runtime_error("missing case table");
    const std::string input = argv[2], output = argv[3];
    std::ofstream trace(output + "/trace.tsv"), counts(output + "/counts.tsv");
    if (!trace || !counts) throw std::runtime_error("cannot create audit logs");
    std::string id;
    uint32_t n, block, grid, size;
    unsigned cases = 0;
    while (table >> id >> n >> block >> grid >> size) {
      Memory memory(n, id, trace);
      for (unsigned i = 0; i < 3; ++i) {
        memory.arrays[i] = read_file(input + "/" + id + "_" + "xyz"[i] + ".bin");
        if (memory.arrays[i].size() != size * 4) throw std::runtime_error("input size mismatch");
      }
      auto payload = read_file(input + "/" + id + "_params.bin");
      uint64_t invocations = 0;
      for (uint32_t bid = 0; bid < grid; ++bid) {
        for (uint32_t tid = 0; tid < block; ++tid) {
          memory.bid = bid;
          memory.tid = tid;
          ptx_body(payload.data(), PtxThread{tid, block, bid, grid}, memory);
          ++invocations;
        }
      }
      for (unsigned i = 0; i < 3; ++i)
        write_file(output + "/" + id + "_" + "xyz"[i] + ".bin", memory.arrays[i]);
      counts << id << '\t' << invocations << '\t' << memory.loads << '\t' << memory.stores << '\n';
      ++cases;
    }
    if (!table.eof() || !trace || !counts) throw std::runtime_error("table or audit I/O failure");
    std::cout << "HOST_SEMANTICS_COMPLETE " << cases << '\n';
    return 0;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
