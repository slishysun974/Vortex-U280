// Generated semantic body; no device loader, launch or memory sandbox.
#pragma once
#include <stdint.h>
struct PtxThread { uint32_t thread_id, block_size, block_id, grid_size; };
static inline uint32_t ptx_read32(const uint8_t* p) {
  uint32_t value;
  __builtin_memcpy(&value, __builtin_assume_aligned(p, 4), sizeof(value));
  return value;
}
static inline uint64_t ptx_read64(const uint8_t* p) {
  uint64_t value;
  __builtin_memcpy(&value, __builtin_assume_aligned(p, 8), sizeof(value));
  return value;
}
template<class Memory>
static inline void ptx_body([[maybe_unused]] const uint8_t* payload, [[maybe_unused]] const PtxThread& thread, [[maybe_unused]] Memory& memory) {
  [[maybe_unused]] bool v0;
  [[maybe_unused]] uint32_t v1;
  [[maybe_unused]] uint32_t v2;
  [[maybe_unused]] uint32_t v3;
  [[maybe_unused]] uint32_t v4;
  [[maybe_unused]] uint32_t v5;
  [[maybe_unused]] uint64_t v6;
  [[maybe_unused]] uint64_t v7;
  [[maybe_unused]] uint64_t v8;
  [[maybe_unused]] uint64_t v9;
  [[maybe_unused]] uint64_t v10;
  v6 = ptx_read64(payload + 0);
  v7 = ptx_read64(payload + 8);
  v1 = ptx_read32(payload + 16);
  v2 = thread.block_id;
  v3 = thread.block_size;
  v2 = uint32_t(v2 * v3);
  v3 = thread.thread_id;
  v2 = uint32_t(v2 + v3);
  v0 = (v2 < v1);
  v8 = (uint64_t(v2) * uint64_t(UINT32_C(4)));
  (void)0; /* identity */
  (void)0; /* identity */
  v9 = uint64_t(v6 + v8);
  v10 = uint64_t(v7 + v8);
  if (v0) {
    v4 = memory.load32((v9 + UINT64_C(0)));
    memory.store32((v10 + UINT64_C(0)), v4);
  }
  return;
}
