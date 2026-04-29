// UART-driven OTA receiver. Pi-side cuts a release, install-pi.sh lands a
// new firmware.bin in /opt/panel/current/, panel-flash on the Pi streams
// it to us over the existing UART link at 921600 baud.
//
// Wire protocol (line-mode JSON at 115200 unless noted):
//
//     Pi → C6: {"type":"ota_begin","size":N,"sha256":"...",...}
//     C6 → Pi: {"type":"ota_ready"}                      [we switch to 921600 + raw]
//                  └─ Pi reads, also switches to 921600.
//     Pi → C6: <exactly N raw bytes of firmware>         [921600, raw mode]
//                  └─ After N bytes, both sides switch back to 115200 + line.
//     C6 → Pi: {"type":"ota_result","status":"ok"|"error","detail":"..."}
//     [on success, C6 reboots into the new partition.]
//
// No interleaving during the raw transfer — JSON envelopes can't be
// distinguished from arbitrary firmware bytes, so we just count to N and
// flip back to line mode. Progress UI is the Pi's job (it knows how many
// bytes it's sent).
//
// Self-validation + rollback is unchanged from V1's HTTP-OTA path: panel_net
// already calls esp_ota_mark_app_valid_cancel_rollback() after MQTT
// reconnects on the new boot. If the new image fails to reconnect, the
// bootloader reverts on the next reset.

#include "panel_ota_uart.h"
#include "panel_lidar.h"
#include "panel_net.h"
#include "panel_uart.h"

#include <inttypes.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "esp_log.h"
#include "esp_ota_ops.h"
#include "esp_partition.h"
#include "esp_system.h"
#include "freertos/FreeRTOS.h"
#include "freertos/stream_buffer.h"
#include "freertos/task.h"
#include "psa/crypto.h"

static const char *TAG = "panel_ota_uart";

// Steady-state baud (must match panel_platform_config.h::PANEL_UART_BAUD).
// We could read it back via uart_get_baudrate but hard-coding matches the
// one place it's set so failure modes are easier to spot.
#define OTA_BAUD_STEADY     115200
#define OTA_BAUD_TRANSFER   921600

// Stream buffer between rx_task (producer) and ota_task (consumer). 64 KB
// holds ~700 ms of bytes at 921600 baud — covers worst-case esp_ota_write
// stalls (sector erase + write can spike to 100+ ms) plus any other tasks
// briefly preempting the drain. RAM is cheap on the C6 (512 KB SRAM); this
// is allocated only for the OTA window and freed afterward.
#define OTA_STREAM_BUF_BYTES (64 * 1024)
// Drain in 4 KB chunks to align with the flash sector size.
#define OTA_DRAIN_CHUNK      4096

// Per-chunk timeout — if no bytes arrive for this long, abort.
#define OTA_RX_TIMEOUT_MS    5000

typedef struct {
    size_t expected_size;
    size_t received_bytes;
    char   expected_sha256[65]; // 64 hex chars + null
    StreamBufferHandle_t stream;
    esp_ota_handle_t ota_handle;
    const esp_partition_t *partition;
    psa_hash_operation_t   sha_op;
    TaskHandle_t worker;
} ota_state_t;

static volatile bool s_active = false;
static ota_state_t  *s_state  = NULL;

bool panel_ota_uart_is_active(void)
{
    return s_active;
}

static void send_result(const char *status, const char *detail)
{
    char buf[192];
    int n;
    if (detail && *detail)
    {
        n = snprintf(buf, sizeof(buf),
                     "{\"type\":\"ota_result\",\"status\":\"%s\",\"detail\":\"%s\"}",
                     status, detail);
    }
    else
    {
        n = snprintf(buf, sizeof(buf),
                     "{\"type\":\"ota_result\",\"status\":\"%s\"}",
                     status);
    }
    if (n > 0 && n < (int)sizeof(buf))
    {
        (void)panel_uart_send_line(buf, n);
    }
}

// rx_task callback while raw mode is active. Push bytes into the stream
// buffer; ota_task drains them. Bytes beyond `expected_size` are ignored
// (Pi shouldn't send any, but be defensive).
static void on_raw_chunk(const uint8_t *data, size_t len, void *user)
{
    ota_state_t *st = (ota_state_t *)user;
    if (!st || !st->stream)
    {
        return;
    }
    size_t remaining = st->expected_size - st->received_bytes;
    size_t to_take = (len > remaining) ? remaining : len;
    if (to_take == 0)
    {
        return;
    }
    size_t sent = xStreamBufferSend(st->stream, data, to_take, 0);
    st->received_bytes += sent;
    if (sent < to_take)
    {
        // Stream buffer full — should be rare with 16 KB buffer, but log it.
        // The bytes we couldn't accept are LOST (Pi can't replay), which
        // means the sha256 will mismatch and the OTA will fail cleanly.
        ESP_LOGW(TAG, "stream buffer overflow, dropped %u bytes",
                 (unsigned)(to_take - sent));
    }
}

static void cleanup_and_release(ota_state_t *st)
{
    // Switch UART back to steady state regardless of outcome.
    panel_uart_clear_raw_mode();
    panel_uart_set_baud(OTA_BAUD_STEADY);
    if (st)
    {
        if (st->stream)
        {
            vStreamBufferDelete(st->stream);
        }
        // psa_hash_abort is safe to call on a finished/aborted op (no-op).
        (void)psa_hash_abort(&st->sha_op);
        free(st);
    }
    s_state  = NULL;
    s_active = false;
    // Resume MQTT + LiDAR regardless of outcome. On the success path the
    // C6 is about to esp_restart() so these are brief no-ops; on failure
    // paths we want both back so HA still talks to us and the kiosk gets
    // distance/strength updates. Idempotent if either was never paused
    // (early-failure paths in handle_begin).
    panel_net_resume();
    panel_lidar_resume();
}

static void hex_encode(const uint8_t *bytes, size_t len, char *out)
{
    static const char hex[] = "0123456789abcdef";
    for (size_t i = 0; i < len; i++)
    {
        out[i * 2 + 0] = hex[(bytes[i] >> 4) & 0xF];
        out[i * 2 + 1] = hex[bytes[i] & 0xF];
    }
    out[len * 2] = '\0';
}

static void ota_task(void *arg)
{
    ota_state_t *st = (ota_state_t *)arg;

    // Ack the begin envelope. ota_ready is its own envelope (not "result")
    // because results are reserved for the final outcome. After the Pi sees
    // this it knows to switch its baud to OTA_BAUD_TRANSFER.
    const char *ready = "{\"type\":\"ota_ready\"}";
    (void)panel_uart_send_line(ready, strlen(ready));

    // Tiny grace period for the Pi to register the line + flip its baud
    // before we change ours. 50 ms is generous for any USB-serial path.
    vTaskDelay(pdMS_TO_TICKS(50));

    panel_uart_set_baud(OTA_BAUD_TRANSFER);
    panel_uart_set_raw_mode(on_raw_chunk, st);

    // Drain loop: read from stream buffer in 4 KB chunks, esp_ota_write +
    // sha256_update each chunk, until we've written `expected_size` bytes.
    uint8_t *drain = malloc(OTA_DRAIN_CHUNK);
    if (!drain)
    {
        ESP_LOGE(TAG, "drain buffer alloc failed");
        cleanup_and_release(st);
        send_result("error", "drain alloc failed");
        vTaskDelete(NULL);
        return;
    }

    size_t written = 0;
    bool   failed = false;
    const char *fail_detail = NULL;

    while (written < st->expected_size && !failed)
    {
        size_t n = xStreamBufferReceive(st->stream, drain, OTA_DRAIN_CHUNK,
                                        pdMS_TO_TICKS(OTA_RX_TIMEOUT_MS));
        if (n == 0)
        {
            // Timed out waiting for bytes from Pi — abort.
            ESP_LOGE(TAG, "rx timeout after %u/%u bytes",
                     (unsigned)written, (unsigned)st->expected_size);
            failed = true;
            fail_detail = "rx timeout";
            break;
        }
        esp_err_t err = esp_ota_write(st->ota_handle, drain, n);
        if (err != ESP_OK)
        {
            ESP_LOGE(TAG, "esp_ota_write failed at %u: %s",
                     (unsigned)written, esp_err_to_name(err));
            failed = true;
            fail_detail = "ota write failed";
            break;
        }
        psa_status_t ps = psa_hash_update(&st->sha_op, drain, n);
        if (ps != PSA_SUCCESS)
        {
            ESP_LOGE(TAG, "psa_hash_update failed: %d", (int)ps);
            failed = true;
            fail_detail = "sha256 update failed";
            break;
        }
        written += n;
    }

    free(drain);

    // Switch UART back to steady-state regardless of outcome — we're done
    // with raw mode and need line mode for the result envelope (and so the
    // bridge can talk to us again).
    panel_uart_clear_raw_mode();
    panel_uart_set_baud(OTA_BAUD_STEADY);

    if (failed)
    {
        esp_ota_abort(st->ota_handle);
        send_result("error", fail_detail);
        cleanup_and_release(st);
        vTaskDelete(NULL);
        return;
    }

    // Verify sha256.
    uint8_t actual[32];
    size_t  actual_len = 0;
    char    actual_hex[65];
    psa_status_t ps = psa_hash_finish(&st->sha_op, actual, sizeof(actual), &actual_len);
    if (ps != PSA_SUCCESS || actual_len != 32)
    {
        ESP_LOGE(TAG, "psa_hash_finish failed: %d (len %u)",
                 (int)ps, (unsigned)actual_len);
        esp_ota_abort(st->ota_handle);
        send_result("error", "sha256 finish failed");
        cleanup_and_release(st);
        vTaskDelete(NULL);
        return;
    }
    hex_encode(actual, sizeof(actual), actual_hex);
    if (strcmp(actual_hex, st->expected_sha256) != 0)
    {
        ESP_LOGE(TAG, "sha256 mismatch:\n  expected %s\n  got      %s",
                 st->expected_sha256, actual_hex);
        esp_ota_abort(st->ota_handle);
        send_result("error", "sha256 mismatch");
        cleanup_and_release(st);
        vTaskDelete(NULL);
        return;
    }

    // Finalize.
    esp_err_t err = esp_ota_end(st->ota_handle);
    if (err != ESP_OK)
    {
        ESP_LOGE(TAG, "esp_ota_end failed: %s", esp_err_to_name(err));
        send_result("error", "esp_ota_end failed");
        cleanup_and_release(st);
        vTaskDelete(NULL);
        return;
    }

    err = esp_ota_set_boot_partition(st->partition);
    if (err != ESP_OK)
    {
        ESP_LOGE(TAG, "esp_ota_set_boot_partition failed: %s", esp_err_to_name(err));
        send_result("error", "set_boot_partition failed");
        cleanup_and_release(st);
        vTaskDelete(NULL);
        return;
    }

    send_result("ok", NULL);

    ESP_LOGI(TAG, "OTA complete (%u bytes, sha256 ok). Rebooting in 1s...",
             (unsigned)written);
    cleanup_and_release(st);

    // Brief delay so the result envelope drains over UART before reboot.
    vTaskDelay(pdMS_TO_TICKS(1000));
    esp_restart();
}

// ----- public API -----

void panel_ota_uart_init(void)
{
    s_state  = NULL;
    s_active = false;
    // PSA Crypto needs a one-shot init before any psa_* call. It's
    // idempotent on re-call, but esp_tls / WiFi / BLE may already have
    // initialized it; we don't care which side wins.
    psa_status_t ps = psa_crypto_init();
    if (ps != PSA_SUCCESS)
    {
        ESP_LOGW(TAG, "psa_crypto_init returned %d (likely already initialized)",
                 (int)ps);
    }
}

// Tiny JSON field extractor — find "key":VALUE in a flat object. Returns
// pointers into `json` for the start of VALUE and its length, or false.
// Handles only string and integer values; that's what our envelope uses.
static bool extract_field(const char *json, size_t json_len, const char *key,
                          const char **out_start, size_t *out_len, bool string)
{
    char needle[64];
    int nl = snprintf(needle, sizeof(needle), "\"%s\":%s", key, string ? "\"" : "");
    if (nl <= 0 || nl >= (int)sizeof(needle))
    {
        return false;
    }
    const char *p = strstr(json, needle);
    if (!p) return false;
    p += nl;
    if (string)
    {
        const char *end = strchr(p, '"');
        if (!end) return false;
        *out_start = p;
        *out_len = (size_t)(end - p);
    }
    else
    {
        const char *end = p;
        while (end < json + json_len && (*end >= '0' && *end <= '9')) end++;
        if (end == p) return false;
        *out_start = p;
        *out_len = (size_t)(end - p);
    }
    return true;
}

bool panel_ota_uart_handle_begin(const char *json, size_t len)
{
    if (s_active)
    {
        ESP_LOGW(TAG, "ota_begin received while OTA already in progress");
        send_result("error", "already in progress");
        return false;
    }

    // Parse size + sha256 from the envelope.
    const char *size_s; size_t size_n;
    const char *sha_s;  size_t sha_n;
    if (!extract_field(json, len, "size", &size_s, &size_n, false))
    {
        ESP_LOGW(TAG, "ota_begin missing size field");
        send_result("error", "begin missing size");
        return false;
    }
    if (!extract_field(json, len, "sha256", &sha_s, &sha_n, true))
    {
        ESP_LOGW(TAG, "ota_begin missing sha256 field");
        send_result("error", "begin missing sha256");
        return false;
    }
    if (sha_n != 64)
    {
        ESP_LOGW(TAG, "ota_begin sha256 wrong length (%u, want 64)", (unsigned)sha_n);
        send_result("error", "sha256 wrong length");
        return false;
    }

    // sscanf via %zu won't work across all toolchains; use strtoul.
    char size_buf[16];
    if (size_n >= sizeof(size_buf))
    {
        send_result("error", "size too large");
        return false;
    }
    memcpy(size_buf, size_s, size_n);
    size_buf[size_n] = '\0';
    unsigned long expected_size = strtoul(size_buf, NULL, 10);
    if (expected_size == 0 || expected_size > 8 * 1024 * 1024)
    {
        send_result("error", "implausible size");
        return false;
    }

    // Allocate state + buffers.
    ota_state_t *st = calloc(1, sizeof(*st));
    if (!st)
    {
        send_result("error", "state alloc failed");
        return false;
    }
    st->expected_size  = (size_t)expected_size;
    st->received_bytes = 0;
    memcpy(st->expected_sha256, sha_s, 64);
    st->expected_sha256[64] = '\0';
    // Lowercase the expected sha for comparison (our hex_encode emits lower).
    for (int i = 0; i < 64; i++)
    {
        if (st->expected_sha256[i] >= 'A' && st->expected_sha256[i] <= 'F')
        {
            st->expected_sha256[i] = (char)(st->expected_sha256[i] - 'A' + 'a');
        }
    }

    st->stream = xStreamBufferCreate(OTA_STREAM_BUF_BYTES, 1);
    if (!st->stream)
    {
        free(st);
        send_result("error", "stream alloc failed");
        return false;
    }

    st->sha_op = (psa_hash_operation_t)PSA_HASH_OPERATION_INIT;
    psa_status_t ps = psa_hash_setup(&st->sha_op, PSA_ALG_SHA_256);
    if (ps != PSA_SUCCESS)
    {
        ESP_LOGE(TAG, "psa_hash_setup failed: %d", (int)ps);
        vStreamBufferDelete(st->stream);
        free(st);
        send_result("error", "sha256 setup failed");
        return false;
    }

    st->partition = esp_ota_get_next_update_partition(NULL);
    if (!st->partition)
    {
        ESP_LOGE(TAG, "no OTA partition available");
        cleanup_and_release(st);
        send_result("error", "no ota partition");
        return false;
    }
    ESP_LOGI(TAG, "OTA target partition '%s' @ 0x%" PRIx32 " size 0x%" PRIx32,
             st->partition->label, st->partition->address, st->partition->size);

    esp_err_t err = esp_ota_begin(st->partition, st->expected_size, &st->ota_handle);
    if (err != ESP_OK)
    {
        ESP_LOGE(TAG, "esp_ota_begin failed: %s", esp_err_to_name(err));
        cleanup_and_release(st);
        send_result("error", "esp_ota_begin failed");
        return false;
    }

    s_state  = st;
    s_active = true;

    // Pause MQTT + LiDAR — esp-mqtt's reconnect attempts (TLS handshakes)
    // and the LiDAR's per-byte UART0 reads (~900 B/s) both compete with
    // the OTA stream for Thread bandwidth, CPU, and interrupt latency.
    // Both were observed contributing to UART1 RX driver overruns mid-
    // transfer. cleanup_and_release calls the matching resume() functions
    // on every exit path; on success the C6 reboots so the resumes are
    // brief no-ops before the restart.
    panel_net_pause();
    panel_lidar_pause();

    BaseType_t ok = xTaskCreate(ota_task, "panel_ota_uart",
                                6144, st, 9, &st->worker);
    if (ok != pdPASS)
    {
        ESP_LOGE(TAG, "failed to spawn ota worker task");
        esp_ota_abort(st->ota_handle);
        // cleanup_and_release calls panel_net_resume; no duplicate needed.
        cleanup_and_release(st);
        send_result("error", "task spawn failed");
        return false;
    }

    return true;
}
