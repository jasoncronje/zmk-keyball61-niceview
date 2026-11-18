/*
 * Pointer acceleration curve, kept free of Zephyr so a host test can build it.
 * Factors are in thousandths (1000 = 1.0x), speeds in sensor counts per second.
 */
#pragma once

#include <stdint.h>

#define POINTER_ACCEL_ONE 1000

/* Gain for a given speed: low-factor up to speed-low, high-factor from
 * speed-high, smoothstep (3t^2 - 2t^3) in between so the ramp has no corners. */
static inline int32_t pointer_accel_factor(uint32_t speed, uint32_t speed_low, uint32_t speed_high,
                                           int32_t low_factor, int32_t high_factor) {
    if (speed <= speed_low) {
        return low_factor;
    }
    if (speed >= speed_high || speed_high <= speed_low) {
        return high_factor;
    }
    /* t in thousandths */
    int64_t t = (int64_t)(speed - speed_low) * POINTER_ACCEL_ONE / (speed_high - speed_low);
    int64_t s = t * t * (3 * POINTER_ACCEL_ONE - 2 * t) / ((int64_t)POINTER_ACCEL_ONE * POINTER_ACCEL_ONE);
    return low_factor + (int32_t)((int64_t)(high_factor - low_factor) * s / POINTER_ACCEL_ONE);
}

/* Integer square root, for the length of a (dx, dy) step. */
static inline uint32_t pointer_accel_isqrt(uint32_t v) {
    uint32_t r = 0, bit = 1u << 30;
    while (bit > v) {
        bit >>= 2;
    }
    while (bit) {
        if (v >= r + bit) {
            v -= r + bit;
            r = (r >> 1) + bit;
        } else {
            r >>= 1;
        }
        bit >>= 2;
    }
    return r;
}
