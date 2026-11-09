#ifndef AB_NATIVE_BOUNDARY_H
#define AB_NATIVE_BOUNDARY_H

#include <stddef.h>
#include <stdint.h>

// Private native test payload, not the project's PTX module ABI.
struct boundary_args {
  uint64_t x_addr, y_addr, z_addr, audit_addr;
  uint32_t n, operation, alpha, predicate;
};
static_assert(sizeof(boundary_args) == 48, "native test payload size");
static_assert(offsetof(boundary_args, n) == 32, "native test payload offset");

#endif
