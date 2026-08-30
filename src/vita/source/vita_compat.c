#include "vita_video.h"

#include <stdbool.h>
#include <stdio.h>

/*
 * Minimal hooks required by the DeltaruneVita-derived backend. Undertale
 * Yellow does not currently use native borders or hardware video. Keeping
 * these hooks explicit makes future implementations replaceable in one file.
 */

extern int g_vitaProbeLoggingEnabled;

void VitaProbe_logLine(const char *text) {
    if (g_vitaProbeLoggingEnabled && text != NULL) puts(text);
}

void VitaProbe_rotateLog(void) {
    VitaProbe_logLine("PROBE_LOG=rotation_requested");
}

void VitaBorders_draw(int window_width, int window_height) {
    (void)window_width;
    (void)window_height;
}

int VitaBorders_coversScreen(void) {
    return 0;
}

int VitaBorders_filesAvailable(void) {
    return 0;
}

void VitaBorders_prepareRoomChange(const char *next_room_name) {
    (void)next_room_name;
}

int VitaVideo_open(const char *path) {
    (void)path;
    return -1;
}

bool VitaVideo_updateFrame(void) { return false; }
void VitaVideo_draw(float x, float y, float width, float height) {
    (void)x; (void)y; (void)width; (void)height;
}
float VitaVideo_getWidth(void) { return 0.0f; }
float VitaVideo_getHeight(void) { return 0.0f; }
void VitaVideo_close(void) {}
void VitaVideo_pause(void) {}
void VitaVideo_resume(void) {}
int VitaVideo_getStatus(void) { return VITA_VIDEO_STATUS_NONE; }
float VitaVideo_getDuration(void) { return 0.0f; }
float VitaVideo_getPosition(void) { return 0.0f; }
void VitaVideo_setLooping(bool enabled) { (void)enabled; }
void VitaVideo_setVolume(float volume) { (void)volume; }
