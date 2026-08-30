#include <psp2/ctrl.h>
#include <psp2/io/fcntl.h>
#include <psp2/io/stat.h>
#include <psp2/kernel/processmgr.h>
#include <psp2/kernel/threadmgr.h>
#include <psp2/power.h>
#include <psp2/touch.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <vitaGL.h>

#include "audio/openal/al_audio_system.h"
#include "data_win.h"
#include "gl_legacy_renderer.h"
#include "overlay_file_system.h"
#include "runner.h"
#include "runner_gamepad.h"
#include "runner_keyboard.h"
#include "vita_settings.h"
#include "vm.h"

#define DATA_ROOT "ux0:data/undertale-yellow/"
#define SAVE_ROOT "ux0:data/undertale-yellow/save/"
#define GAME_PATH DATA_ROOT "data.win"
#define LOG_PATH DATA_ROOT "butterscotch.log"

int _newlib_heap_size_user = 256 * 1024 * 1024;
unsigned int sceUserMainThreadStackSize = 4 * 1024 * 1024;

/* Compatibility globals used by the Vita backend inherited from DeltaruneVita. */
int g_vitaActiveChapter = 0;
int g_vitaSpanishModActive = 0;
int g_vitaProbeLoggingEnabled = 1;
bool g_vitaModernGlActive = false;

typedef struct { uint32_t mask; int key; } KeyMap;
static const KeyMap KEY_MAP[] = {
    {SCE_CTRL_UP, VK_UP}, {SCE_CTRL_DOWN, VK_DOWN},
    {SCE_CTRL_LEFT, VK_LEFT}, {SCE_CTRL_RIGHT, VK_RIGHT},
    {SCE_CTRL_CROSS, 'Z'}, {SCE_CTRL_CIRCLE, 'X'},
    {SCE_CTRL_SQUARE, 'X'}, {SCE_CTRL_TRIANGLE, 'C'},
    {SCE_CTRL_START, VK_ENTER}
};

typedef struct {
    bool left, right, up, down;
    bool confirm, cancel, menu;
    float stick_x, stick_y;
} TouchInput;

static float absf_local(float value) { return value < 0.0f ? -value : value; }

static TouchInput read_touch(const VitaSettings *settings) {
    TouchInput result = {0};
    if (!settings->touchEnabled || settings->open || settings->adjustMode) return result;
    SceTouchData touch = {0};
    if (sceTouchPeek(SCE_TOUCH_PORT_FRONT, &touch, 1) <= 0) return result;
    for (uint32_t i = 0; i < touch.reportNum; ++i) {
        float x = (float)touch.report[i].x * (960.0f / 1920.0f);
        float y = (float)touch.report[i].y * (544.0f / 1088.0f);
        float dx = x - (float)settings->touchControlX[0];
        float dy = y - (float)settings->touchControlY[0];
        float stick_radius = 105.0f * (float)settings->touchControlScale[0] / 100.0f;
        if (dx * dx + dy * dy <= stick_radius * stick_radius) {
            result.stick_x = dx / (stick_radius * 0.62f);
            result.stick_y = dy / (stick_radius * 0.62f);
            if (result.stick_x < -1.0f) result.stick_x = -1.0f;
            if (result.stick_x > 1.0f) result.stick_x = 1.0f;
            if (result.stick_y < -1.0f) result.stick_y = -1.0f;
            if (result.stick_y > 1.0f) result.stick_y = 1.0f;
            result.left |= result.stick_x < -0.28f;
            result.right |= result.stick_x > 0.28f;
            result.up |= result.stick_y < -0.28f;
            result.down |= result.stick_y > 0.28f;
            continue;
        }
        for (int button = 1; button < 4; ++button) {
            float bx = x - (float)settings->touchControlX[button];
            float by = y - (float)settings->touchControlY[button];
            float radius = 58.0f * (float)settings->touchControlScale[button] / 100.0f;
            if (bx * bx + by * by <= radius * radius) {
                if (button == 1) result.confirm = true;
                if (button == 2) result.cancel = true;
                if (button == 3) result.menu = true;
            }
        }
    }
    return result;
}

static void log_line(const char *text) {
    SceUID fd = sceIoOpen(LOG_PATH, SCE_O_WRONLY | SCE_O_CREAT | SCE_O_APPEND, 0666);
    if (fd >= 0) {
        sceIoWrite(fd, text, strlen(text));
        sceIoWrite(fd, "\n", 1);
        sceIoClose(fd);
    }
}

static void progress(const char *chunk, int index, int total, DataWin *dw, void *user) {
    (void)dw; (void)user;
    char line[96];
    snprintf(line, sizeof(line), "LOAD chunk=%.4s %d/%d", chunk, index + 1, total);
    log_line(line);
}

static void set_key(RunnerKeyboardState *keyboard, int key, bool down, bool *previous) {
    if (down && !*previous) RunnerKeyboard_onKeyDown(keyboard, key);
    else if (!down && *previous) RunnerKeyboard_onKeyUp(keyboard, key);
    *previous = down;
}

static DataWinParserOptions parser_options(void) {
    DataWinParserOptions options = {0};
    options.parseGen8 = true; options.parseOptn = true; options.parseLang = true;
    options.parseExtn = true; options.parseSond = true; options.parseAgrp = true;
    options.parseSprt = true; options.parseBgnd = true; options.parsePath = true;
    options.parseScpt = true; options.parseGlob = true; options.parseShdr = true;
    options.parseFont = true; options.parseTmln = true; options.parseObjt = true;
    options.parseRoom = true; options.parseTpag = true; options.parseCode = true;
    options.parseVari = true; options.parseFunc = true; options.parseStrg = true;
    options.parseTxtr = true; options.parseAudo = true;
    options.skipLoadingPreciseMasksForNonPreciseSprites = true;
    options.lazyLoadRooms = true;
    options.lazyLoadTextures = true;
    options.loadType = DATAWINLOADTYPE_LOAD_PER_CHUNK;
    options.progressCallback = progress;
    return options;
}

int main(void) {
    setvbuf(stdout, NULL, _IONBF, 0);
    setvbuf(stderr, NULL, _IONBF, 0);
    sceIoMkdir(DATA_ROOT, 0777);
    sceIoMkdir(SAVE_ROOT, 0777);
    sceIoRemove(LOG_PATH);
    log_line("Undertale Yellow Vita base runner 00.02");

    SceIoStat game_stat;
    if (sceIoGetstat(GAME_PATH, &game_stat) < 0 || game_stat.st_size < 1024) {
        log_line("FATAL=data.win_missing");
        sceKernelExitProcess(1);
    }

    sceCtrlSetSamplingMode(SCE_CTRL_MODE_ANALOG);
    sceTouchSetSamplingState(SCE_TOUCH_PORT_FRONT, SCE_TOUCH_SAMPLING_STATE_START);
    scePowerSetArmClockFrequency(444);
    scePowerSetBusClockFrequency(222);
    scePowerSetGpuClockFrequency(222);
    scePowerSetGpuXbarClockFrequency(166);
    vglSetupRuntimeShaderCompiler(SHARK_OPT_SLOW, 0, 0, 0);
    vglInitExtended(0, 960, 544, 64 * 1024 * 1024, SCE_GXM_MULTISAMPLE_NONE);

    DataWin *data = DataWin_parse(GAME_PATH, parser_options());
    if (data == NULL) {
        log_line("FATAL=data.win_parse_failed");
        sceKernelExitProcess(2);
    }

    VMContext *vm = VM_create(data);
    OverlayFileSystem *files = OverlayFileSystem_create(DATA_ROOT, SAVE_ROOT);
    Renderer *renderer = GLLegacyRenderer_create();
    AudioSystem *audio = (AudioSystem *)AlAudioSystem_create();
    VitaSettings settings;
    VitaSettings_load(&settings);
    VitaSettings_setLauncherMode(false);
    VitaSettings_setActiveChapter(0);
    Runner *runner = Runner_create(data, vm, renderer, (FileSystem *)files, audio);
    VitaSettings_applyAudio(&settings, audio);
    char *game_args[] = {"eboot.bin", "-game", "data.win"};
    Runner_setGameArgs(runner, game_args, 3);
    runner->debugMode = false;
    Runner_initFirstRoom(runner);
    log_line("BOOT=first_room_ready");

    bool previous[sizeof(KEY_MAP) / sizeof(KEY_MAP[0])] = {0};
    bool gamepad_previous[16] = {0};
    uint64_t last_time = sceKernelGetProcessTimeWide();

    while (!runner->shouldExit) {
        RunnerKeyboard_beginFrame(runner->keyboard);
        RunnerGamepad_beginFrame(runner->gamepads);
        SceCtrlData pad = {0};
        sceCtrlPeekBufferPositive(0, &pad, 1);
        TouchInput touch = read_touch(&settings);
        int dx = (int)pad.lx - 128;
        int dy = (int)pad.ly - 128;
        bool restart_requested = VitaSettings_handleInput(&settings, &pad, audio);
        if (restart_requested) {
            log_line("SETTINGS=restart_requested");
            break;
        }
        if (!settings.open && !settings.adjustMode) {
            for (unsigned i = 0; i < sizeof(KEY_MAP) / sizeof(KEY_MAP[0]); ++i) {
                bool down = (pad.buttons & KEY_MAP[i].mask) != 0;
                if (KEY_MAP[i].key == 'Z') down |= touch.confirm;
                if (KEY_MAP[i].key == 'X') down |= touch.cancel;
                if (KEY_MAP[i].key == 'C') down |= touch.menu;
                if (KEY_MAP[i].key == VK_LEFT) down |= touch.left;
                if (KEY_MAP[i].key == VK_RIGHT) down |= touch.right;
                if (KEY_MAP[i].key == VK_UP) down |= touch.up;
                if (KEY_MAP[i].key == VK_DOWN) down |= touch.down;
                if (KEY_MAP[i].key == VK_LEFT) down |= dx < -48;
                if (KEY_MAP[i].key == VK_RIGHT) down |= dx > 48;
                if (KEY_MAP[i].key == VK_UP) down |= dy < -48;
                if (KEY_MAP[i].key == VK_DOWN) down |= dy > 48;
                set_key(runner->keyboard, KEY_MAP[i].key, down, &previous[i]);
            }
        }

        GamepadSlot *gp = &runner->gamepads->slots[0];
        gp->connected = true;
        gp->jid = 0;
        runner->gamepads->connectedCount = 1;
        if (gp->description[0] == '\0') {
            snprintf(gp->description, sizeof(gp->description), "PS Vita Controller");
            snprintf(gp->guid, sizeof(gp->guid), "PSVITA000000000000000000000001");
        }
        const int gp_buttons[] = {GP_FACE1, GP_FACE2, GP_FACE3, GP_FACE4,
            GP_SHOULDERL, GP_SHOULDERR, GP_SELECT, GP_START,
            GP_PADU, GP_PADD, GP_PADL, GP_PADR};
        const bool gp_down[] = {
            (pad.buttons & SCE_CTRL_CROSS) != 0 || touch.confirm,
            (pad.buttons & SCE_CTRL_CIRCLE) != 0 || touch.cancel,
            (pad.buttons & SCE_CTRL_SQUARE) != 0,
            (pad.buttons & SCE_CTRL_TRIANGLE) != 0 || touch.menu,
            (pad.buttons & SCE_CTRL_LTRIGGER) != 0,
            (pad.buttons & SCE_CTRL_RTRIGGER) != 0,
            (pad.buttons & SCE_CTRL_SELECT) != 0,
            (pad.buttons & SCE_CTRL_START) != 0,
            (pad.buttons & SCE_CTRL_UP) != 0 || touch.up,
            (pad.buttons & SCE_CTRL_DOWN) != 0 || touch.down,
            (pad.buttons & SCE_CTRL_LEFT) != 0 || touch.left,
            (pad.buttons & SCE_CTRL_RIGHT) != 0 || touch.right
        };
        for (unsigned i = 0; i < sizeof(gp_buttons) / sizeof(gp_buttons[0]); ++i)
            RunnerGamepad_setButton(runner->gamepads, 0, gp_buttons[i], gp_down[i], &gamepad_previous[i]);
        float physical_x = (float)dx / 128.0f, physical_y = (float)dy / 128.0f;
        float axis_x = absf_local(touch.stick_x) > absf_local(physical_x) ? touch.stick_x : physical_x;
        float axis_y = absf_local(touch.stick_y) > absf_local(physical_y) ? touch.stick_y : physical_y;
        RunnerGamepad_setAxis(runner->gamepads, 0, GP_AXIS_LH, axis_x);
        RunnerGamepad_setAxis(runner->gamepads, 0, GP_AXIS_LV, axis_y);
        VitaSettings_setTouchVisuals(&settings, touch.stick_x, touch.stick_y,
                                     touch.confirm, touch.cancel, touch.menu);

        static bool s_portSplashCompleted = false;
        static bool s_portSplashActive = false;
        if (!s_portSplashCompleted && runner->currentRoomIndex > 0) {
            s_portSplashActive = true;
        }

        if (s_portSplashActive) {
            static bool prevCross = true;
            bool cross = (pad.buttons & (SCE_CTRL_CROSS | SCE_CTRL_START)) != 0 || touch.confirm;
            if (cross && !prevCross) {
                s_portSplashActive = false;
                s_portSplashCompleted = true;
            }
            prevCross = cross;
        }

        uint64_t now = sceKernelGetProcessTimeWide();
        runner->deltaTime = (double)(now - last_time);
        last_time = now;
        if (!s_portSplashActive) {
            Runner_step(runner);
            runner->audioSystem->vtable->update(
                runner->audioSystem, (float)(runner->deltaTime / 1000000.0));
        }

        glClearColor(0, 0, 0, 1);
        glClear(GL_COLOR_BUFFER_BIT);
        int game_width = (int)data->gen8.defaultWindowWidth;
        int game_height = (int)data->gen8.defaultWindowHeight;
        Runner_drawPre(runner, 960, 544);
        if (s_portSplashActive) {
            VitaSettings_drawPortSplash(&settings, renderer, 1.0f);
        } else {
            Runner_beginFrame(runner, game_width, game_height, 960, 544, 960, 544);
            Runner_drawViews(runner, game_width, game_height, false);
            renderer->vtable->endFrameInit(renderer);
            Runner_drawPost(runner, 960, 544);
            renderer->vtable->endFrameEnd(renderer);
            Runner_drawGUI(runner, 960, 544, game_width, game_height);
            VitaSettings_drawTouchControls(&settings, renderer);
            VitaSettings_drawBrightness(&settings, renderer);
            VitaSettings_draw(&settings, renderer);
            VitaSettings_drawCalibration(&settings, renderer);
        }
        if (runner->pendingRoom == -1) vglSwapBuffers(GL_FALSE);
        if (!s_portSplashActive) {
            Runner_handlePendingRoomChange(runner);
        }

        int configured_speed[] = {30, 40, 60, 0};
        int speed = settings.fpsTargetMode >= 0 && settings.fpsTargetMode < 4
            ? configured_speed[settings.fpsTargetMode] : 30;
        if (speed == 0)
            speed = runner->currentRoom && runner->currentRoom->speed
                ? (int)runner->currentRoom->speed : 60;
        uint64_t frame_elapsed = sceKernelGetProcessTimeWide() - now;
        uint64_t frame_budget = (uint64_t)(1000000 / speed);
        if (frame_elapsed < frame_budget)
            sceKernelDelayThread((unsigned int)(frame_budget - frame_elapsed));
    }

    log_line("PROCESS=exit_clean");
    runner->audioSystem->vtable->destroy(runner->audioSystem);
    renderer->vtable->destroy(renderer);
    Runner_free(runner);
    OverlayFileSystem_destroy(files);
    VM_free(vm);
    DataWin_free(data);
    sceKernelExitProcess(0);
    return 0;
}
