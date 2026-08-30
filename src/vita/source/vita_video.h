#pragma once

#include <stdbool.h>

#define VITA_VIDEO_STATUS_NONE 0
#define VITA_VIDEO_STATUS_PREPARING 1
#define VITA_VIDEO_STATUS_PLAYING 2
#define VITA_VIDEO_STATUS_PAUSED 3
#define VITA_VIDEO_SURFACE_ID (-700001)

int VitaVideo_open(const char *path);
bool VitaVideo_updateFrame(void);
void VitaVideo_draw(float x, float y, float width, float height);
float VitaVideo_getWidth(void);
float VitaVideo_getHeight(void);
void VitaVideo_close(void);
void VitaVideo_pause(void);
void VitaVideo_resume(void);
int VitaVideo_getStatus(void);
float VitaVideo_getDuration(void);
float VitaVideo_getPosition(void);
void VitaVideo_setLooping(bool enabled);
void VitaVideo_setVolume(float volume);
