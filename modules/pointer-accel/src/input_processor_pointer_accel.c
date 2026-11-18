/*
 * Pointer acceleration in the firmware, so macOS acceleration can be turned
 * off and the pointer feels the same over USB and BLE (macOS accelerates each
 * report by its own size, and BLE packs several sensor readings per report).
 *
 * Speed is the length of each (X, Y) sensor step over the time since the
 * previous step, so diagonals accelerate like straight lines, smoothed over a
 * few steps. The PMW3610 driver reports X then Y (with sync) for every
 * reading. Both axes of one reading get the same gain, the one worked out
 * from the readings before it, so a step's direction is never bent.
 */

#define DT_DRV_COMPAT zmk_input_processor_pointer_accel

#include <stdlib.h>

#include <zephyr/device.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zephyr/dt-bindings/input/input-event-codes.h>

#include <drivers/input_processor.h>

#include "pointer_accel_curve.h"

LOG_MODULE_REGISTER(pointer_accel, CONFIG_ZMK_LOG_LEVEL);

/* A gap longer than this starts a new movement from rest. */
#define IDLE_RESET_US 100000
/* Shortest step time used for speed, so a burst can't divide by ~0. */
#define MIN_STEP_US 1000

struct pointer_accel_config {
    int32_t low_factor;
    int32_t high_factor;
    uint32_t speed_low;
    uint32_t speed_high;
    /* weight of the newest step in the speed average, out of 1000 */
    uint32_t smoothing;
};

struct pointer_accel_data {
    int32_t pending_x;   /* raw X of the reading whose Y hasn't arrived */
    int32_t factor;      /* gain for the current reading */
    uint32_t speed;      /* smoothed counts per second */
    int64_t last_us;     /* time of the previous complete reading */
    int32_t rem_x, rem_y; /* thousandths left over per axis */
};

static int32_t apply(int32_t raw, int32_t factor, int32_t *rem) {
    int32_t total = raw * factor + *rem;
    int32_t out = total / POINTER_ACCEL_ONE;
    *rem = total - out * POINTER_ACCEL_ONE;
    return out;
}

static int pointer_accel_handle_event(const struct device *dev, struct input_event *event,
                                      uint32_t param1, uint32_t param2,
                                      struct zmk_input_processor_state *state) {
    const struct pointer_accel_config *cfg = dev->config;
    struct pointer_accel_data *data = dev->data;

    if (event->type != INPUT_EV_REL) {
        return ZMK_INPUT_PROC_CONTINUE;
    }

    if (event->code == INPUT_REL_X) {
        /* After a pause, start slow rather than with the last flick's gain. */
        if (k_ticks_to_us_floor64(k_uptime_ticks()) - data->last_us > IDLE_RESET_US) {
            data->factor = cfg->low_factor;
        }
        data->pending_x = event->value;
        event->value = apply(event->value, data->factor, &data->rem_x);
        return ZMK_INPUT_PROC_CONTINUE;
    }
    if (event->code != INPUT_REL_Y) {
        return ZMK_INPUT_PROC_CONTINUE;
    }

    int32_t raw_y = event->value;
    event->value = apply(raw_y, data->factor, &data->rem_y);

    /* Reading complete: update speed and the gain for the next one. */
    int64_t now = k_ticks_to_us_floor64(k_uptime_ticks());
    int64_t dt = now - data->last_us;
    uint32_t step = pointer_accel_isqrt((uint32_t)(data->pending_x * data->pending_x + raw_y * raw_y));
    data->pending_x = 0;
    data->last_us = now;

    if (dt > IDLE_RESET_US) {
        /* From rest: no average to carry over, and the long gap says nothing
         * about this step's speed. */
        data->speed = 0;
        data->rem_x = 0;
        data->rem_y = 0;
    } else {
        if (dt < MIN_STEP_US) {
            dt = MIN_STEP_US;
        }
        uint32_t inst = (uint32_t)((int64_t)step * 1000000 / dt);
        data->speed = (uint32_t)(((uint64_t)data->speed * (1000 - cfg->smoothing) +
                                  (uint64_t)inst * cfg->smoothing) / 1000);
    }

    data->factor = pointer_accel_factor(data->speed, cfg->speed_low, cfg->speed_high,
                                        cfg->low_factor, cfg->high_factor);
    return ZMK_INPUT_PROC_CONTINUE;
}

static const struct zmk_input_processor_driver_api pointer_accel_driver_api = {
    .handle_event = pointer_accel_handle_event,
};

#define POINTER_ACCEL_INST(n)                                                                      \
    BUILD_ASSERT(DT_INST_PROP(n, speed_high) > DT_INST_PROP(n, speed_low),                         \
                 "speed-high must be above speed-low");                                            \
    BUILD_ASSERT(DT_INST_PROP(n, smoothing) >= 1 && DT_INST_PROP(n, smoothing) <= 1000,            \
                 "smoothing is 1..1000");                                                          \
    static const struct pointer_accel_config pointer_accel_config_##n = {                          \
        .low_factor = DT_INST_PROP(n, low_factor),                                                 \
        .high_factor = DT_INST_PROP(n, high_factor),                                               \
        .speed_low = DT_INST_PROP(n, speed_low),                                                   \
        .speed_high = DT_INST_PROP(n, speed_high),                                                 \
        .smoothing = DT_INST_PROP(n, smoothing),                                                   \
    };                                                                                             \
    static struct pointer_accel_data pointer_accel_data_##n = {                                    \
        .factor = DT_INST_PROP(n, low_factor),                                                     \
    };                                                                                             \
    DEVICE_DT_INST_DEFINE(n, NULL, NULL, &pointer_accel_data_##n, &pointer_accel_config_##n,       \
                          POST_KERNEL, CONFIG_KERNEL_INIT_PRIORITY_DEFAULT,                        \
                          &pointer_accel_driver_api);

DT_INST_FOREACH_STATUS_OKAY(POINTER_ACCEL_INST)
