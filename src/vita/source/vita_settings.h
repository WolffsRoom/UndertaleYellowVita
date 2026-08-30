#ifndef UNDERTALE_YELLOW_VITA_SETTINGS_H
#define UNDERTALE_YELLOW_VITA_SETTINGS_H

#include <stdbool.h>
#include <stdint.h>
#include <psp2/ctrl.h>

#include "audio_system.h"
#include "renderer.h"

extern int g_vitaPortOverlayFullScreen;

#define MAX_MODS 16
#define MOD_NAME_MAX 32

typedef struct {
    bool open;
    bool touchEnabled;
    char activeLanguage[32];
    char uiCategories[7][64];
    char uiLabels[7][8][64];
    char uiFooters[8][64];
    bool widescreenEnabled;
    int consoleBorderMode; // 0 = off, 1 = dynamic artwork, 2 = simple white frame
    bool betterBordersEnabled;
    bool adjustMode;
    bool restartOnClose;
    bool returnToChapterSelect;
    bool confirmChapterSelect;
    int musicVolume;
    int sfxVolume;
    int masterVolume;
    bool audioDisabled;
    bool devMode;
    bool showSettings;
    bool vsyncEnabled;
    int fpsTargetMode; // 0 = 30 FPS, 1 = 40 FPS, 2 = 60 FPS, 3 = Unlock
    // 0 none, 1 scanlines, 2 sharp bilinear, 3 CRT curvature,
    // 0 none, 1 scanlines, 2 sharp bilinear, 3 dithering, 4 VHS. All apply live.
    int screenFilterMode;
    int textureFormatProfile; // 0 = Otimizado (RGBA4444 + BC3 2048x2048), 1 = Nativo (RGBA4444), 2 = Low (BC3)
    bool pvrEnabled;
    bool bc3Enabled;
    bool modernGlEnabled;
    bool debugDevEnabled;
    bool debugDevChanged;
    bool debugCollisionMasks;
    bool devRoomNavEnabled;
    bool shortcutSkipDialogs;
    int graphicsQuality;
    int brightness;
    int pendingGraphicsQuality;
    bool pendingPvrEnabled;
    bool pendingBc3Enabled;
    bool pendingModernGlEnabled;
    int modIndex;
    int pendingModIndex;
    int pendingTextureFormatProfile;
    int pendingFpsTargetMode;
    int pendingScreenFilterMode;
    int modCount;
    char modNames[MAX_MODS][MOD_NAME_MAX];
    bool showRestartPrompt;
    int promptSelection; // 0 = Yes, 1 = No
    int displayOffsetX;
    int displayOffsetY;
    int displayZoom;
    float visualStickX;
    float visualStickY;
    bool visualConfirm;
    bool visualCancel;
    bool visualMenu;
    int category;
    int selected;
    int inputCooldown;
    int borderWarningFrames;
    bool controlEditMode;
    bool graphicsMenuOpen;
    bool trophiesMenuOpen;
    int trophiesSelected;
    int trophiesScroll;
    bool trophiesUnlockedFirst;
    int trophyDisplayOrder[30];
    bool trophiesUnlocked[30];
    bool trophiesEnabled;
    bool trophyStateInitialized;
    int trophyPollFrames;
    int trophyNotificationId;
    int trophyNotificationFrames;
    char trophyTitles[30][64];
    char trophyDescriptions[30][128];
    int graphicsMenuSelected;
    int selectedTouchControl;
    int touchControlX[4];
    int touchControlY[4];
    int touchControlScale[4];
    uint32_t previousButtons;
    bool pendingResetDefaults;
} VitaSettings;

extern int g_vitaGraphicsQuality;
extern int g_vitaPvrEnabled;
extern int g_vitaBc3OnlyEnabled;

void VitaSettings_load(VitaSettings* settings);
bool VitaSettings_forceLegacyRenderer(VitaSettings* settings);
void VitaSettings_applyAudio(VitaSettings* settings, AudioSystem* audio);
void VitaSettings_setSliderFromTouch(VitaSettings* settings, AudioSystem* audio,
                                     int logicalCategory, int item, float touchX);
bool VitaSettings_handleInput(VitaSettings* settings, const SceCtrlData* pad, AudioSystem* audio);
void VitaSettings_draw(VitaSettings* settings, Renderer* renderer);
void VitaSettings_updateTrophies(VitaSettings* settings);
uint32_t VitaSettings_syncGameTrophies(VitaSettings* settings, const bool unlocked[30]);
void VitaSettings_drawTrophyNotification(VitaSettings* settings, Renderer* renderer);
void VitaSettings_drawBrightness(VitaSettings* settings, Renderer* renderer);
void VitaSettings_drawTouchControls(VitaSettings* settings, Renderer* renderer);
void VitaSettings_drawCalibration(VitaSettings* settings, Renderer* renderer);
void VitaSettings_drawPortSplash(VitaSettings* settings, Renderer* renderer, float alpha);
void VitaSettings_drawDevOverlay(VitaSettings* settings, Renderer* renderer,
                                 const char* room, float fps, uint64_t stepUs,
                                 uint64_t audioUs, uint64_t renderUs,
                                 uint64_t gpuBytes, uint32_t evictions,
                                 uint32_t deferred, uint32_t ramHits,
                                 const char* devTargetRoom, int32_t devTargetIndex);
void VitaSettings_setTouchVisuals(VitaSettings* settings, float stickX, float stickY,
                                  bool confirm, bool cancel, bool menu);
void VitaSettings_setLauncherMode(bool launcherMode);
void VitaSettings_setActiveChapter(int chapter);
int VitaSettings_itemCount(int category);

extern int g_vitaScreenFilterMode;

#endif
