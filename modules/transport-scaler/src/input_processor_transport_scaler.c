/*
 * Transport scaler: zmk,input-processor-scaler with one fraction for USB and
 * another for BLE, picked from the output selected when each event arrives.
 * Lets the sensor run at a higher CPI and scale down to a different effective
 * CPI per output.
 */

#define DT_DRV_COMPAT zmk_input_processor_transport_scaler

#include <zephyr/device.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>

#include <drivers/input_processor.h>

#include <zmk/endpoints.h>

LOG_MODULE_REGISTER(transport_scaler, CONFIG_ZMK_LOG_LEVEL);

struct transport_scaler_config {
    uint8_t type;
    uint16_t usb_mul, usb_div;
    uint16_t ble_mul, ble_div;
    size_t codes_len;
    uint16_t codes[];
};

static int transport_scaler_handle_event(const struct device *dev, struct input_event *event,
                                         uint32_t param1, uint32_t param2,
                                         struct zmk_input_processor_state *state) {
    const struct transport_scaler_config *cfg = dev->config;

    if (event->type != cfg->type) {
        return ZMK_INPUT_PROC_CONTINUE;
    }

    bool match = false;
    for (size_t i = 0; i < cfg->codes_len; i++) {
        if (cfg->codes[i] == event->code) {
            match = true;
            break;
        }
    }
    if (!match) {
        return ZMK_INPUT_PROC_CONTINUE;
    }

    bool usb = zmk_endpoints_selected().transport == ZMK_TRANSPORT_USB;
    int32_t mul = usb ? cfg->usb_mul : cfg->ble_mul;
    int32_t div = usb ? cfg->usb_div : cfg->ble_div;

    // 32-bit so a fast flick at high CPI can't overflow before the divide
    int32_t value = (int32_t)event->value * mul;
    if (state && state->remainder) {
        value += *state->remainder;
    }

    int32_t scaled = value / div;
    if (state && state->remainder) {
        *state->remainder = value - scaled * div;
    }

    event->value = scaled;
    return ZMK_INPUT_PROC_CONTINUE;
}

static const struct zmk_input_processor_driver_api transport_scaler_driver_api = {
    .handle_event = transport_scaler_handle_event,
};

#define TRANSPORT_SCALER_INST(n)                                                                   \
    BUILD_ASSERT(DT_INST_PROP_LEN(n, usb_scale) == 2, "usb-scale is <multiplier divisor>");        \
    BUILD_ASSERT(DT_INST_PROP_LEN(n, ble_scale) == 2, "ble-scale is <multiplier divisor>");        \
    static const struct transport_scaler_config transport_scaler_config_##n = {                    \
        .type = DT_INST_PROP(n, type),                                                             \
        .usb_mul = DT_INST_PROP_BY_IDX(n, usb_scale, 0),                                           \
        .usb_div = DT_INST_PROP_BY_IDX(n, usb_scale, 1),                                           \
        .ble_mul = DT_INST_PROP_BY_IDX(n, ble_scale, 0),                                           \
        .ble_div = DT_INST_PROP_BY_IDX(n, ble_scale, 1),                                           \
        .codes_len = DT_INST_PROP_LEN(n, codes),                                                   \
        .codes = DT_INST_PROP(n, codes),                                                           \
    };                                                                                             \
    DEVICE_DT_INST_DEFINE(n, NULL, NULL, NULL, &transport_scaler_config_##n, POST_KERNEL,          \
                          CONFIG_KERNEL_INIT_PRIORITY_DEFAULT, &transport_scaler_driver_api);

DT_INST_FOREACH_STATUS_OKAY(TRANSPORT_SCALER_INST)
