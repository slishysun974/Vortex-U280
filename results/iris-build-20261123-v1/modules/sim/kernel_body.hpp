// Generated semantic body; no device loader, launch or memory sandbox.
#pragma once
#include <stdint.h>
struct PtxThread { uint32_t thread_id, block_size, block_id, grid_size; };
static inline uint32_t ptx_read32(const uint8_t* p) {
  return uint32_t(p[0]) | (uint32_t(p[1]) << 8) | (uint32_t(p[2]) << 16) | (uint32_t(p[3]) << 24);
}
static inline uint64_t ptx_read64(const uint8_t* p) {
  return uint64_t(ptx_read32(p)) | (uint64_t(ptx_read32(p + 4)) << 32);
}
template<class Memory>
static inline void ptx_body([[maybe_unused]] const uint8_t* payload, [[maybe_unused]] const PtxThread& thread, [[maybe_unused]] Memory& memory) {
  [[maybe_unused]] uint64_t v0;
  [[maybe_unused]] uint64_t v1;
  [[maybe_unused]] uint64_t v2;
  [[maybe_unused]] uint64_t v3;
  [[maybe_unused]] uint32_t v4;
  [[maybe_unused]] uint32_t v5;
  [[maybe_unused]] uint32_t v6;
  [[maybe_unused]] uint32_t v7;
  [[maybe_unused]] uint32_t v8;
  [[maybe_unused]] uint32_t v9;
  [[maybe_unused]] uint32_t v10;
  [[maybe_unused]] uint32_t v11;
  [[maybe_unused]] uint32_t v12;
  [[maybe_unused]] uint32_t v13;
  [[maybe_unused]] uint32_t v14;
  [[maybe_unused]] uint32_t v15;
  [[maybe_unused]] uint32_t v16;
  [[maybe_unused]] uint32_t v17;
  [[maybe_unused]] uint32_t v18;
  [[maybe_unused]] uint32_t v19;
  [[maybe_unused]] uint32_t v20;
  [[maybe_unused]] uint32_t v21;
  [[maybe_unused]] uint32_t v22;
  [[maybe_unused]] bool v23;
  [[maybe_unused]] bool v24;
  [[maybe_unused]] bool v25;
  v0 = ptx_read64(payload + 0);
  v1 = ptx_read64(payload + 8);
  v2 = ptx_read64(payload + 16);
  v8 = ptx_read32(payload + 24);
  v4 = thread.block_id;
  v5 = thread.block_size;
  v6 = thread.thread_id;
  v7 = uint32_t(v4 * v5);
  v7 = uint32_t(v7 + v6);
  v23 = (v7 < v8);
  v3 = (uint64_t(v7) * uint64_t(UINT32_C(16)));
  v0 = uint64_t(v0 + v3);
  v2 = uint64_t(v2 + v3);
  v9 = UINT32_C(0);
  if (v23) { v9 = memory.load32((v0 + UINT64_C(0))); }
  v9 = uint32_t(v9 * UINT32_C(35));
  v10 = UINT32_C(0);
  if (v23) { v10 = memory.load32((v0 + UINT64_C(4))); }
  v10 = uint32_t(v10 * UINT32_C(35));
  v11 = UINT32_C(0);
  if (v23) { v11 = memory.load32((v0 + UINT64_C(8))); }
  v11 = uint32_t(v11 * UINT32_C(35));
  v12 = UINT32_C(0);
  if (v23) { v12 = memory.load32((v0 + UINT64_C(12))); }
  v12 = uint32_t(v12 * UINT32_C(35));
  v16 = UINT32_C(0);
  v13 = UINT32_C(0);
  if (v23) { v16 = memory.load32((v1 + UINT64_C(0))); }
  v24 = (v9 >= v16);
  v17 = uint32_t(v9 - v16);
  v18 = uint32_t(v16 - v9);
  v19 = (v24 ? v17 : v18);
  v20 = uint32_t(v19 * v19);
  v13 = uint32_t(v13 + v20);
  if (v23) { v16 = memory.load32((v1 + UINT64_C(4))); }
  v24 = (v10 >= v16);
  v17 = uint32_t(v10 - v16);
  v18 = uint32_t(v16 - v10);
  v19 = (v24 ? v17 : v18);
  v20 = uint32_t(v19 * v19);
  v13 = uint32_t(v13 + v20);
  if (v23) { v16 = memory.load32((v1 + UINT64_C(8))); }
  v24 = (v11 >= v16);
  v17 = uint32_t(v11 - v16);
  v18 = uint32_t(v16 - v11);
  v19 = (v24 ? v17 : v18);
  v20 = uint32_t(v19 * v19);
  v13 = uint32_t(v13 + v20);
  if (v23) { v16 = memory.load32((v1 + UINT64_C(12))); }
  v24 = (v12 >= v16);
  v17 = uint32_t(v12 - v16);
  v18 = uint32_t(v16 - v12);
  v19 = (v24 ? v17 : v18);
  v20 = uint32_t(v19 * v19);
  v13 = uint32_t(v13 + v20);
  v14 = UINT32_C(0);
  if (v23) { v16 = memory.load32((v1 + UINT64_C(16))); }
  v24 = (v9 >= v16);
  v17 = uint32_t(v9 - v16);
  v18 = uint32_t(v16 - v9);
  v19 = (v24 ? v17 : v18);
  v20 = uint32_t(v19 * v19);
  v14 = uint32_t(v14 + v20);
  if (v23) { v16 = memory.load32((v1 + UINT64_C(20))); }
  v24 = (v10 >= v16);
  v17 = uint32_t(v10 - v16);
  v18 = uint32_t(v16 - v10);
  v19 = (v24 ? v17 : v18);
  v20 = uint32_t(v19 * v19);
  v14 = uint32_t(v14 + v20);
  if (v23) { v16 = memory.load32((v1 + UINT64_C(24))); }
  v24 = (v11 >= v16);
  v17 = uint32_t(v11 - v16);
  v18 = uint32_t(v16 - v11);
  v19 = (v24 ? v17 : v18);
  v20 = uint32_t(v19 * v19);
  v14 = uint32_t(v14 + v20);
  if (v23) { v16 = memory.load32((v1 + UINT64_C(28))); }
  v24 = (v12 >= v16);
  v17 = uint32_t(v12 - v16);
  v18 = uint32_t(v16 - v12);
  v19 = (v24 ? v17 : v18);
  v20 = uint32_t(v19 * v19);
  v14 = uint32_t(v14 + v20);
  v15 = UINT32_C(0);
  if (v23) { v16 = memory.load32((v1 + UINT64_C(32))); }
  v24 = (v9 >= v16);
  v17 = uint32_t(v9 - v16);
  v18 = uint32_t(v16 - v9);
  v19 = (v24 ? v17 : v18);
  v20 = uint32_t(v19 * v19);
  v15 = uint32_t(v15 + v20);
  if (v23) { v16 = memory.load32((v1 + UINT64_C(36))); }
  v24 = (v10 >= v16);
  v17 = uint32_t(v10 - v16);
  v18 = uint32_t(v16 - v10);
  v19 = (v24 ? v17 : v18);
  v20 = uint32_t(v19 * v19);
  v15 = uint32_t(v15 + v20);
  if (v23) { v16 = memory.load32((v1 + UINT64_C(40))); }
  v24 = (v11 >= v16);
  v17 = uint32_t(v11 - v16);
  v18 = uint32_t(v16 - v11);
  v19 = (v24 ? v17 : v18);
  v20 = uint32_t(v19 * v19);
  v15 = uint32_t(v15 + v20);
  if (v23) { v16 = memory.load32((v1 + UINT64_C(44))); }
  v24 = (v12 >= v16);
  v17 = uint32_t(v12 - v16);
  v18 = uint32_t(v16 - v12);
  v19 = (v24 ? v17 : v18);
  v20 = uint32_t(v19 * v19);
  v15 = uint32_t(v15 + v20);
  v22 = UINT32_C(0);
  v25 = (v14 < v13);
  v21 = (v25 ? v14 : v13);
  v22 = (v25 ? UINT32_C(1) : v22);
  v25 = (v15 < v21);
  v22 = (v25 ? UINT32_C(2) : v22);
  if (v23) { memory.store32((v2 + UINT64_C(0)), v13); }
  if (v23) { memory.store32((v2 + UINT64_C(4)), v14); }
  if (v23) { memory.store32((v2 + UINT64_C(8)), v15); }
  if (v23) { memory.store32((v2 + UINT64_C(12)), v22); }
  return;
}
