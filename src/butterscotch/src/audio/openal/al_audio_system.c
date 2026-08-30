// On Windows, include windows.h first so its headers are processed before stb_vorbis
// defines single-letter macros (L, C, R) that conflict with winnt.h struct field names.
#ifdef _WIN32
#include <windows.h>
#endif

#include "stb_vorbis.c"
#include "al_audio_system.h"
#include "data_win.h"
#include "utils.h"
#include "wave.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "stb_ds.h"

#ifdef PLATFORM_VITA
#include <psp2/io/fcntl.h>
#include <psp2/io/stat.h>
static uint8_t vitaSfxFirstStart[4096];
static void vitaAudioLog(const char* phase, const char* requested, const char* resolved) {
    extern int g_vitaProbeLoggingEnabled;
    if (!g_vitaProbeLoggingEnabled) return;
    char line[640];
    int length = snprintf(line, sizeof(line), "AUDIO_STREAM=%s requested=%s resolved=%s\n",
                          phase, requested != nullptr ? requested : "-", resolved != nullptr ? resolved : "-");
    SceUID fd = sceIoOpen("ux0:data/undertale-yellow/butterscotch.log",
                          SCE_O_WRONLY | SCE_O_CREAT | SCE_O_APPEND, 0666);
    if (fd >= 0) {
        sceIoWrite(fd, line, (SceSize) length);
        sceIoClose(fd);
    }
}
#endif

// ===[ Helpers ]===

static bool alSourceIsPlaying(ALuint source) {
    ALint state;
    alGetSourcei(source, AL_SOURCE_STATE, &state);
    return state == AL_PLAYING;
}

static bool alSourceHasStopped(ALuint source) {
    ALint state;
    alGetSourcei(source, AL_SOURCE_STATE, &state);
    return state == AL_STOPPED;
}

static bool alSourceIsLooping(ALuint source) {
    ALint state;
    alGetSourcei(source, AL_LOOPING, &state);
    return state != AL_FALSE;
}

// Source - https://stackoverflow.com/a/7995655
// Posted by Karl
// Retrieved 2026-05-05, License - CC BY-SA 3.0
static void alGetSourceLengthSec(ALuint buffer, float* out) {
    ALint sizeInBytes;
    ALint channels;
    ALint bits;

    alGetBufferi(buffer, AL_SIZE, &sizeInBytes);
    alGetBufferi(buffer, AL_CHANNELS, &channels);
    alGetBufferi(buffer, AL_BITS, &bits);

    int lengthInSamples = sizeInBytes * 8 / (channels * bits);
    ALint frequency;

    alGetBufferi(buffer, AL_FREQUENCY, &frequency);

    *out = (float)lengthInSamples / (float)frequency;
}

// Tears down whatever AL state is attached to a slot and marks it inactive.
static void releaseInstance(SoundInstance* inst) {
    if (!inst->active)
        return;

    alSourceStop(inst->alSource);

    if (inst->streaming) {
        // Drain anything still queued so the buffer names are detachable.
        ALint queued = 0;
        alGetSourcei(inst->alSource, AL_BUFFERS_QUEUED, &queued);
        repeat(queued, i) {
            ALuint b;
            alSourceUnqueueBuffers(inst->alSource, 1, &b);
        }
        alDeleteBuffers(AL_STREAM_BUFFER_COUNT, inst->streamBuffers);
        if (inst->vorbis != nullptr) {
            stb_vorbis_close((stb_vorbis*) inst->vorbis);
            inst->vorbis = nullptr;
        }
        free(inst->streamCompressedData);
        inst->streamCompressedData = nullptr;
        inst->streamCompressedSize = 0;
        free(inst->decodeScratch);
        inst->decodeScratch = nullptr;
        inst->streaming = false;
    } else {
        if (!inst->sharedBuffer) alDeleteBuffers(1, &inst->alBuffer);
    }

    // Sources are expensive to create/delete on Vita. Keep the slot's source
    // alive and detach its old buffer so the next sound can reuse it.
    alSourcei(inst->alSource, AL_BUFFER, 0);

    inst->active = false;
    inst->sharedBuffer = false;
    inst->pausedByDisabled = false;
    inst->pausedByTransition = false;
}

static ALuint findCachedSfxBuffer(AlAudioSystem* ma, int32_t soundIndex) {
    repeat(MAX_SFX_BUFFER_CACHE, i)
        if (ma->sfxBufferCache[i].active && ma->sfxBufferCache[i].soundIndex == soundIndex)
            return ma->sfxBufferCache[i].buffer;
    return 0;
}

static bool cacheSfxBuffer(AlAudioSystem* ma, int32_t soundIndex, ALuint buffer) {
    repeat(MAX_SFX_BUFFER_CACHE, i) {
        if (!ma->sfxBufferCache[i].active) {
            ma->sfxBufferCache[i].active = true;
            ma->sfxBufferCache[i].soundIndex = soundIndex;
            ma->sfxBufferCache[i].buffer = buffer;
            return true;
        }
    }
    return false;
}

static void maGroupLoad(AudioSystem* audio, int32_t groupIndex);
static stb_vorbis* openStreamingVorbis(const char* path, SoundInstance* inst, int* error);

// Decode the next chunk from inst->vorbis into inst->decodeScratch and upload it to "buf".
// Wraps around on EOF if inst->loop is set.
// Returns false when no more samples are available (decoder exhausted and not looping, or read failed).
static bool streamFillBuffer(SoundInstance* inst, ALuint buf) {
    stb_vorbis* v = (stb_vorbis*) inst->vorbis;
    int samples = stb_vorbis_get_samples_short_interleaved(v, inst->streamChannels, inst->decodeScratch, AL_STREAM_BUFFER_SAMPLES * inst->streamChannels);
    if (0 >= samples) {
        if (!inst->loop) return false;
        stb_vorbis_seek_start(v);
        samples = stb_vorbis_get_samples_short_interleaved(v, inst->streamChannels, inst->decodeScratch, AL_STREAM_BUFFER_SAMPLES * inst->streamChannels);
        if (0 >= samples) return false;
    }
    alBufferData(buf, inst->streamFormat, inst->decodeScratch, samples * inst->streamChannels * (ALsizei) sizeof(int16_t), inst->streamSampleRate);
    return true;
}

static SoundInstance* findFreeSlot(AlAudioSystem* ma) {
    // First pass: find an inactive slot
    repeat(MAX_SOUND_INSTANCES, i) {
        if (!ma->instances[i].active) {
            return &ma->instances[i];
        }
    }

    // Second pass: evict the lowest-priority ended sound.
    // Streaming instances and music instances are excluded from eviction to keep background music alive across SFX bursts.
    SoundInstance* best = nullptr;
    repeat(MAX_SOUND_INSTANCES, i) {
        SoundInstance* inst = &ma->instances[i];
        if (inst->streaming || inst->music)
            continue;

        if (!alSourceIsPlaying(inst->alSource)) {
            if (best == nullptr || best->priority > inst->priority) {
                best = inst;
            }
        }
    }

    if (best != nullptr) {
        releaseInstance(best);
        return best;
    }

    // Third pass: evict lowest-priority active non-music SFX if all slots are occupied
    repeat(MAX_SOUND_INSTANCES, i) {
        SoundInstance* inst = &ma->instances[i];
        if (inst->streaming || inst->music)
            continue;

        if (best == nullptr || best->priority > inst->priority) {
            best = inst;
        }
    }

    if (best != nullptr) {
        releaseInstance(best);
    }

    return best;
}

static SoundInstance* findInstanceById(AlAudioSystem* ma, int32_t instanceId) {
    int32_t slotIndex = instanceId - SOUND_INSTANCE_ID_BASE;
    if (0 > slotIndex || slotIndex >= MAX_SOUND_INSTANCES) return nullptr;
    SoundInstance* inst = &ma->instances[slotIndex];
    if (!inst->active || inst->instanceId != instanceId) return nullptr;
    return inst;
}

static char* resolveSharedMusicPath(FileSystem* fs, const char* filename) {
    const char* relative = filename;
    // GML may pass a path already expanded by the overlay (including ux0: and
    // a mod directory). The shared music library is flat, so recover the final
    // filename before trying deltarunevita/music.
    const char* lastSlash = strrchr(relative, '/');
    const char* lastBackslash = strrchr(relative, '\\');
    if (lastBackslash != nullptr && (lastSlash == nullptr || lastBackslash > lastSlash)) lastSlash = lastBackslash;
    if (lastSlash != nullptr && (strstr(relative, "ux0:") == relative || strstr(relative, "mods/") != nullptr)) {
        relative = lastSlash + 1;
    }
    while (strncmp(relative, "../", 3) == 0 || strncmp(relative, "./", 2) == 0) {
        relative += relative[1] == '.' ? 3 : 2;
    }
    if (strncmp(relative, "mus/", 4) == 0) relative += 4;
    else if (strncmp(relative, "music/", 6) == 0) relative += 6;

    char shared[560];
    snprintf(shared, sizeof(shared), "mus/%s", relative);
    char* resolved = fs->vtable->resolvePath(fs, shared);
    if (resolved != nullptr && fs->vtable->fileExists(fs, resolved)) return resolved;
    free(resolved);

    snprintf(shared, sizeof(shared), "snd/%s", relative);
    resolved = fs->vtable->resolvePath(fs, shared);
    if (resolved != nullptr && fs->vtable->fileExists(fs, resolved)) return resolved;
    free(resolved);

#ifdef PLATFORM_VITA
    char vitaYellowPath[640];
    SceIoStat vitaYellowStat;
    snprintf(vitaYellowPath, sizeof(vitaYellowPath), "ux0:data/undertale-yellow/mus/%s", relative);
    if (sceIoGetstat(vitaYellowPath, &vitaYellowStat) >= 0) return safeStrdup(vitaYellowPath);
    snprintf(vitaYellowPath, sizeof(vitaYellowPath), "ux0:data/undertale-yellow/snd/%s", relative);
    if (sceIoGetstat(vitaYellowPath, &vitaYellowStat) >= 0) return safeStrdup(vitaYellowPath);
#endif

    return nullptr;
}

// Helper: resolve external audio file path from Sound entry
static char* resolveExternalPath(AlAudioSystem* ma, Sound* sound) {
    const char* file = sound->file;
    if (file == nullptr || file[0] == '\0') return nullptr;

    // Check only the basename. Paths such as "../mus/field_of_hopes" contain
    // dots in "../" but still need the .ogg suffix.
    const char* basename = strrchr(file, '/');
    basename = basename != nullptr ? basename + 1 : file;
    bool hasExtension = (strchr(basename, '.') != nullptr);

    char filename[512];
    if (hasExtension) {
        snprintf(filename, sizeof(filename), "%s", file);
    } else {
        snprintf(filename, sizeof(filename), "%s.ogg", file);
    }

    char* resolved = ma->fileSystem->vtable->resolvePath(ma->fileSystem, filename);
    if (resolved != nullptr && ma->fileSystem->vtable->fileExists(ma->fileSystem, resolved)) return resolved;
    free(resolved);

    const char* leaf = strrchr(filename, '/');
    const char* backslash = strrchr(filename, '\\');
    if (backslash != nullptr && (leaf == nullptr || backslash > leaf)) leaf = backslash;
    leaf = leaf != nullptr ? leaf + 1 : filename;

    if (leaf[0] != '\0') {
        const char* prefixes[] = {"mus/", "snd/", ""};
        for (uint32_t i = 0; i < sizeof(prefixes) / sizeof(prefixes[0]); ++i) {
            char candidate[560];
            snprintf(candidate, sizeof(candidate), "%s%s", prefixes[i], leaf);
            resolved = ma->fileSystem->vtable->resolvePath(ma->fileSystem, candidate);
            if (resolved != nullptr && ma->fileSystem->vtable->fileExists(ma->fileSystem, resolved)) {
                return resolved;
            }
            free(resolved);
        }
    }

#ifdef PLATFORM_VITA
    char vitaCandidate[640];
    SceIoStat vitaStat;
    snprintf(vitaCandidate, sizeof(vitaCandidate), "ux0:data/undertale-yellow/snd/%s", leaf);
    if (sceIoGetstat(vitaCandidate, &vitaStat) >= 0) return safeStrdup(vitaCandidate);
    snprintf(vitaCandidate, sizeof(vitaCandidate), "ux0:data/undertale-yellow/mus/%s", leaf);
    if (sceIoGetstat(vitaCandidate, &vitaStat) >= 0) return safeStrdup(vitaCandidate);
#endif

    return resolveSharedMusicPath(ma->fileSystem, filename);
}

static float instanceCategoryGain(AlAudioSystem* ma, SoundInstance* inst) {
    return inst->music ? ma->musicGain : ma->sfxGain;
}

// ===[ Vtable Implementations ]===

static void maInit(AudioSystem* audio, DataWin* dataWin, FileSystem* fileSystem) {
    AlAudioSystem* ma = (AlAudioSystem*) audio;
    arrput(ma->base.audioGroups, dataWin);
    ma->fileSystem = fileSystem;

#ifdef PLATFORM_VITA
    fprintf(stderr, "OPENAL_INIT=device_begin\n");
#endif
    ma->alDevice = alcOpenDevice(nullptr);
    if (ma->alDevice == nullptr) {
        fprintf(stderr, "Audio: Failed to open OpenAL device (error %d)\n", alGetError());
#ifdef PLATFORM_VITA
        fprintf(stderr, "OPENAL_INIT=device_failed\n");
#endif
        return;
    }
#ifdef PLATFORM_VITA
    fprintf(stderr, "OPENAL_INIT=device_complete context_begin\n");
#endif
    ma->alContext = alcCreateContext(ma->alDevice, nullptr);
    if (ma->alContext == nullptr) {
        fprintf(stderr, "Audio: Failed to create OpenAL context (error %d)\n", alGetError());
        alcCloseDevice(ma->alDevice);
        ma->alDevice = nullptr;
#ifdef PLATFORM_VITA
        fprintf(stderr, "OPENAL_INIT=context_failed\n");
#endif
        return;
    }
    if (!alcMakeContextCurrent(ma->alContext)) {
        fprintf(stderr, "Audio: Failed to activate OpenAL context (error %d)\n", alGetError());
        alcDestroyContext(ma->alContext);
        alcCloseDevice(ma->alDevice);
        ma->alContext = nullptr;
        ma->alDevice = nullptr;
#ifdef PLATFORM_VITA
        fprintf(stderr, "OPENAL_INIT=context_activate_failed\n");
#endif
        return;
    }
#ifdef PLATFORM_VITA
    fprintf(stderr, "OPENAL_INIT=context_complete\n");
#endif

    memset(ma->instances, 0, sizeof(ma->instances));
    ma->musicGain = 1.0f;
    ma->sfxGain = 1.0f;
    ma->nextInstanceCounter = 0;

    fprintf(stderr, "Audio: OpenAL engine initialized\n");

#ifdef PLATFORM_VITA
    memset(vitaSfxFirstStart, 0, sizeof(vitaSfxFirstStart));
    // Chapter data may request group-1 effects before its GML loader reaches
    // audio_group_load(). Load only the AUDO index/file lazily here; PCM is
    // still decoded on first use, so this removes the missing-first-SFX race
    // without preloading several MiB of decoded samples.
    maGroupLoad(audio, 1);
#endif
}

static void maDestroy(AudioSystem* audio) {
    AlAudioSystem* ma = (AlAudioSystem*) audio;

    // Uninit all active sound instances
    repeat(MAX_SOUND_INSTANCES, i) {
        releaseInstance(&ma->instances[i]);
        if (ma->instances[i].alSource != 0)
            alDeleteSources(1, &ma->instances[i].alSource);
    }

    // Free stream entries
    repeat(MAX_AUDIO_STREAMS, i) {
        if (ma->streams[i].active) {
            free(ma->streams[i].filePath);
        }
    }

    // Free loaded audio groups. The main data.win is owned by the caller, so skip index 0.
    if (arrlen(ma->base.audioGroups) > 1) {
        for (int32_t i = 1; i < (int32_t) arrlen(ma->base.audioGroups); i++) {
            DataWin_free(ma->base.audioGroups[i]);
        }
    }
    arrfree(ma->base.audioGroups);

    alcMakeContextCurrent(nullptr);
    alcDestroyContext(ma->alContext);
    alcCloseDevice(ma->alDevice);
    free(ma);
}

static void maUpdate(AudioSystem* audio, float deltaTime) {
    AlAudioSystem* ma = (AlAudioSystem*) audio;
    if (ma->disabled) return;

#ifdef PLATFORM_VITA
    // Increase refill allowance so background music streams never starve while SFX is playing
    int vitaStreamRefillsRemaining = deltaTime >= 0.05f ? 4 : 2;
#endif

    repeat(MAX_SOUND_INSTANCES, i) {
        SoundInstance* inst = &ma->instances[i];
        if (!inst->active) continue;

        // Handle gain fading (for cases where we do manual fading)
        if (inst->fadeTimeRemaining > 0.0f) {
            inst->fadeTimeRemaining -= deltaTime;
            if (0.0f >= inst->fadeTimeRemaining) {
                inst->fadeTimeRemaining = 0.0f;
                inst->currentGain = inst->targetGain;
            } else {
                float t = 1.0f - (inst->fadeTimeRemaining / inst->fadeTotalTime);
                inst->currentGain = inst->startGain + (inst->targetGain - inst->startGain) * t;
            }
            alSourcef(inst->alSource, AL_GAIN, inst->currentGain * instanceCategoryGain(ma, inst));
        }

        if (inst->streaming) {
            // Recycle any buffers AL has finished with: count their samples toward the play position, then refill from the decoder and re-queue at the tail.
            ALint processed = 0;
            alGetSourcei(inst->alSource, AL_BUFFERS_PROCESSED, &processed);
            ALint queuedBeforeRecovery = 0;
            alGetSourcei(inst->alSource, AL_BUFFERS_QUEUED, &queuedBeforeRecovery);
            // When a long room transition drains the entire queue, OpenAL
            // leaves all consumed buffers attached to the stopped source.
            // Calling alSourcePlay at that point can replay those old buffers
            // before reaching newly decoded audio. Drain/refill every processed
            // buffer during recovery so playback resumes at the decoder's
            // current position instead of repeating the previous passage.
            bool recoveringUnderrun = !inst->streamEnded &&
                                       alSourceHasStopped(inst->alSource) &&
                                       processed > 0 &&
                                       processed == queuedBeforeRecovery;
            int refillBudget = 1;
#ifdef PLATFORM_VITA
            if (!recoveringUnderrun && !inst->music && vitaStreamRefillsRemaining <= 0)
                refillBudget = 0;
#endif
            int decodedThisFrame = 0;

            if (recoveringUnderrun) {
                // A stopped stream reports the entire attached queue as
                // processed. Never restart it with only part of that queue
                // replaced: the still-attached processed buffers are replayed
                // first and the listener hears the cutscene jump backwards.
                // Detach every consumed buffer, rebuild a short clean queue,
                // then let the normal one-buffer-per-frame path grow it again.
                ALuint recoveredBuffers[AL_STREAM_BUFFER_COUNT];
                int recoveredCount = 0;
                while (processed > 0 && recoveredCount < AL_STREAM_BUFFER_COUNT) {
                    ALuint buf = 0;
                    alSourceUnqueueBuffers(inst->alSource, 1, &buf);
                    processed--;

                    ALint sizeBytes = 0, bits = 0, channels = 0;
                    alGetBufferi(buf, AL_SIZE, &sizeBytes);
                    alGetBufferi(buf, AL_BITS, &bits);
                    alGetBufferi(buf, AL_CHANNELS, &channels);
                    if (bits > 0 && channels > 0) {
                        inst->playedSamples += (uint64_t) (sizeBytes * 8 / (bits * channels));
                    }
                    recoveredBuffers[recoveredCount++] = buf;
                }

                // A fully drained queued source remains at the end marker on
                // Vita's OpenAL implementation. Merely attaching fresh buffers
                // and calling alSourcePlay can leave it stopped, making this
                // expensive recovery run again on every frame. Explicitly
                // rewind and detach the empty queue before rebuilding it.
                alSourceRewind(inst->alSource);
                alSourcei(inst->alSource, AL_BUFFER, 0);

                // Preserve every generated buffer name. Usually all target
                // buffers were queued, but startup underruns can happen while
                // the queue is still growing.
                ALuint orderedBuffers[AL_STREAM_BUFFER_COUNT];
                int orderedCount = 0;
                for (int r = 0; r < recoveredCount; r++)
                    orderedBuffers[orderedCount++] = recoveredBuffers[r];
                for (int old = 0; old < inst->streamBufferTarget; old++) {
                    ALuint candidate = inst->streamBuffers[old];
                    bool alreadyPresent = false;
                    for (int n = 0; n < orderedCount; n++) {
                        if (orderedBuffers[n] == candidate) {
                            alreadyPresent = true;
                            break;
                        }
                    }
                    if (!alreadyPresent && orderedCount < AL_STREAM_BUFFER_COUNT)
                        orderedBuffers[orderedCount++] = candidate;
                }
                for (int n = 0; n < orderedCount; n++)
                    inst->streamBuffers[n] = orderedBuffers[n];

                inst->streamPrimedCount = 0;
                // Refill only a short lead synchronously. Eight 2048-sample
                // alBufferData calls cost about 400 ms in the captured Chapter
                // 2 cutscene. Two blocks restart safely; the normal per-frame
                // path grows the queue back to its transition-safe target.
                int recoveryPrime = inst->music ? 2 : 1;
                if (recoveryPrime > inst->streamBufferTarget)
                    recoveryPrime = inst->streamBufferTarget;
                while (!inst->streamEnded &&
                       inst->streamPrimedCount < recoveryPrime) {
                    ALuint buf = inst->streamBuffers[inst->streamPrimedCount];
                    if (!streamFillBuffer(inst, buf)) {
                        inst->streamEnded = true;
                        break;
                    }
                    alSourceQueueBuffers(inst->alSource, 1, &buf);
                    inst->streamPrimedCount++;
                    decodedThisFrame++;
                }
            }

            while (processed > 0 && decodedThisFrame < refillBudget) {
                ALuint buf;
                alSourceUnqueueBuffers(inst->alSource, 1, &buf);
                processed--;

                ALint sizeBytes = 0, bits = 0, channels = 0;
                alGetBufferi(buf, AL_SIZE, &sizeBytes);
                alGetBufferi(buf, AL_BITS, &bits);
                alGetBufferi(buf, AL_CHANNELS, &channels);
                if (bits > 0 && channels > 0) {
                    inst->playedSamples += (uint64_t) (sizeBytes * 8 / (bits * channels));
                }

                if (!inst->streamEnded) {
                    if (streamFillBuffer(inst, buf)) {
                        alSourceQueueBuffers(inst->alSource, 1, &buf);
                        decodedThisFrame++;
#ifdef PLATFORM_VITA
                        if (!recoveringUnderrun && vitaStreamRefillsRemaining > 0)
                            vitaStreamRefillsRemaining--;
#endif
                    } else {
                        inst->streamEnded = true;
                    }
                }
            }

            if (!inst->streamEnded && decodedThisFrame == 0 &&
                inst->streamPrimedCount < inst->streamBufferTarget
#ifdef PLATFORM_VITA
                && vitaStreamRefillsRemaining > 0
#endif
                ) {
                ALuint buf = inst->streamBuffers[inst->streamPrimedCount];
                if (streamFillBuffer(inst, buf)) {
                    alSourceQueueBuffers(inst->alSource, 1, &buf);
                    inst->streamPrimedCount++;
#ifdef PLATFORM_VITA
                    vitaStreamRefillsRemaining--;
#endif
                } else {
                    inst->streamEnded = true;
                }
            }

            // Reap once the queue has fully drained on a non-looping track.
            ALint queued = 0;
            alGetSourcei(inst->alSource, AL_BUFFERS_QUEUED, &queued);
            if (inst->streamEnded && queued == 0) {
                releaseInstance(inst);
                continue;
            }

            // Underrun recovery: AL goes to AL_STOPPED if the queue runs dry.
            // Kick it back on as soon as we have buffers queued again.
            // A stream created during a room transition is intentionally
            // queued but stopped until the destination has been presented.
            // Treating that state as an underrun started the new room music
            // behind the black frame; a long texture upload then drained it,
            // producing the audible start/stop/restart sequence.
            if (!inst->pausedByTransition && !inst->pausedByDisabled &&
                !ma->disabled && alSourceHasStopped(inst->alSource) && queued > 0) {
                alSourcePlay(inst->alSource);
#ifdef PLATFORM_VITA
                if (recoveringUnderrun) {
                    char soundId[32];
                    snprintf(soundId, sizeof(soundId), "%d", inst->soundIndex);
                    vitaAudioLog("underrun_recovered", soundId,
                                 "clean_queue_rebuilt");
                }
#endif
            }
            continue;
        }

        // Clean up ended non-looping sounds (ma_sound_at_end avoids reaping still-loading async sounds)
        if (alSourceHasStopped(inst->alSource) && !alSourceIsLooping(inst->alSource)) {
            releaseInstance(inst);
        }
    }
}

static int32_t maPlaySound(AudioSystem* audio, int32_t soundIndex, int32_t priority, bool loop) {
    AlAudioSystem* ma = (AlAudioSystem*) audio;
    // Do not log every audio_play_sound request on Vita. Dialogue writers and
    // battle alarms legitimately request the same short SFX many times in one
    // second. vitaAudioLog opens/appends/closes the probe file, so recording
    // this pre-validation notification caused thousands of synchronous memory
    // card writes (18k in one Chapter 1 session), 50-400 ms alarm stalls and
    // music underruns. The useful resolved/started/failure records below remain.
    if (ma->disabled) return -1;

    // Check if this is a stream index (created by audio_create_stream)
    bool isStream = (soundIndex >= AUDIO_STREAM_INDEX_BASE);
    Sound* sound = nullptr;
    char* streamPath = nullptr;

    if (isStream) {
        int32_t streamSlot = soundIndex - AUDIO_STREAM_INDEX_BASE;
        if (0 > streamSlot || streamSlot >= MAX_AUDIO_STREAMS || !ma->streams[streamSlot].active) {
            fprintf(stderr, "Audio: Invalid stream index %d\n", soundIndex);
            return -1;
        }
        streamPath = ma->streams[streamSlot].filePath;
    } else {
        DataWin* dw = ma->base.audioGroups[0]; // Audio Group 0 should always be data.win
        if (0 > soundIndex || (uint32_t) soundIndex >= dw->sond.count) {
            fprintf(stderr, "Audio: Invalid sound index %d\n", soundIndex);
            return -1;
        }
        sound = &dw->sond.sounds[soundIndex];
    }

    SoundInstance* slot = findFreeSlot(ma);
    if (slot == nullptr) {
        fprintf(stderr, "Audio: No free sound slots for sound %d\n", soundIndex);
        return -1;
    }

    int32_t slotIndex = (int32_t) (slot - ma->instances);

    slot->streaming = false;
    slot->vorbis = nullptr;
    slot->streamCompressedData = nullptr;
    slot->streamCompressedSize = 0;
    slot->decodeScratch = nullptr;
    slot->streamEnded = false;
    slot->playedSamples = 0;
    slot->music = isStream;
    if (sound != nullptr) {
        const char* categoryName = sound->file != nullptr ? sound->file : sound->name;
        slot->music = categoryName != nullptr && strncmp(categoryName, "snd_", 4) != 0 &&
                      strncmp(categoryName, "AUDIO_INTRONOISE", 16) != 0;
    }
    if (isStream) {
        // Streaming path: open the decoder, queue a few small buffers, and let maUpdate() top them up.
        // This avoids the multi-hundred-millisecond hang of decoding a whole song into PCM on the main thread.
        int err = 0;
        stb_vorbis* v = openStreamingVorbis(streamPath, slot, &err);
        if (v == nullptr) {
            fprintf(stderr, "Audio: Failed to open stream '%s' (stb_vorbis err %d)\n", streamPath, err);
            return -1;
        }
        stb_vorbis_info info = stb_vorbis_get_info(v);

        slot->streaming = true;
        slot->loop = loop;
        slot->vorbis = v;
        slot->streamChannels = info.channels;
        slot->streamSampleRate = (int) info.sample_rate;
        slot->streamFormat = (info.channels == 2) ? AL_FORMAT_STEREO16 : AL_FORMAT_MONO16;
        slot->streamLengthSeconds = stb_vorbis_stream_length_in_seconds(v);
#ifdef PLATFORM_VITA
        // Keep roughly three seconds of decoded music queued. Chapter 1 room
        // construction can block the main thread for more than two seconds;
        // the former 16-buffer (~0.74 s) queue drained during that gap and AL
        // resumed by repeating the tail of the previous passage. Recovery is
        // still capped in maUpdate(), so a drained queue never decodes all 64
        // blocks synchronously in one frame.
        slot->streamBufferTarget = 64;
#else
        slot->streamBufferTarget = AL_STREAM_BUFFER_COUNT;
#endif
        slot->decodeScratch = (int16_t *)safeMalloc(AL_STREAM_BUFFER_SAMPLES * info.channels * sizeof(int16_t));

        if (slot->alSource == 0) alGenSources(1, &slot->alSource);
        alGenBuffers(AL_STREAM_BUFFER_COUNT, slot->streamBuffers);

        int primed = 0;
        // Two blocks are enough to start cleanly while avoiding a noticeable
        // main-thread pause the first time a song is opened. The update loop
        // grows the queue to its full transition-safe target afterwards.
        // One block is enough to start on Vita. Priming two synchronously made
        // the first snd_loop/snd_play in complex Chapter 3 rooms hitch; the
        // regular update path fills the remaining transition-safe queue.
#ifdef PLATFORM_VITA
        // A single 2048-sample block lasts only about 46 ms at 44.1 kHz.
        // Room construction can block the main thread for 250-750 ms, causing
        // a newly-started music stream to underrun before maUpdate can grow
        // its queue. Prime music with a small transition-safe lead while
        // keeping non-music streams cheap to start.
        // A stream created by Room Start cannot be topped up while room
        // construction owns the main thread. Restore the v0.66 transition
        // margin (roughly one second) before releasing that source.
        // Boot cutscenes can present a first frame and immediately spend
        // 600-900 ms uploading the next atlas set. Eight blocks only cover
        // ~0.37 s at 44.1 kHz, so the opening music drained and restarted
        // repeatedly while the text was being written. Decode this lead while
        // the loading screen is still visible; the remaining queue continues
        // growing incrementally during gameplay.
        const int initialStreamBuffers = slot->music ? 32 : 1;
#else
        const int initialStreamBuffers = 2;
#endif
        for (int i = 0; initialStreamBuffers > i; i++) {
            if (!streamFillBuffer(slot, slot->streamBuffers[i])) break;
            alSourceQueueBuffers(slot->alSource, 1, &slot->streamBuffers[i]);
            primed++;
        }

        if (primed == 0) {
            // Empty file or decode failure: tear everything down cleanly.
            alDeleteSources(1, &slot->alSource);
            alDeleteBuffers(AL_STREAM_BUFFER_COUNT, slot->streamBuffers);
            stb_vorbis_close(v);
            free(slot->streamCompressedData);
            slot->streamCompressedData = nullptr;
            slot->streamCompressedSize = 0;
            free(slot->decodeScratch);
    slot->streaming = false;
    slot->sharedBuffer = false;
            slot->vorbis = nullptr;
            slot->decodeScratch = nullptr;
            return -1;
        }
        slot->streamPrimedCount = primed;
    } else {
        if (slot->alSource == 0) alGenSources(1, &slot->alSource);
        ALuint cachedSfx = !slot->music ? findCachedSfxBuffer(ma, soundIndex) : 0;
        if (cachedSfx != 0) {
            slot->alBuffer = cachedSfx;
            slot->sharedBuffer = true;
            alSourcei(slot->alSource, AL_BUFFER, slot->alBuffer);
        } else {
        alGenBuffers(1, &slot->alBuffer);
        bool isRegular = (sound->flags & AUDIO_ENTRY_FLAG_REGULAR) == AUDIO_ENTRY_FLAG_REGULAR;
        bool isEmbedded = (sound->flags & AUDIO_ENTRY_FLAG_IS_EMBEDDED) != 0;
        bool isCompressed = (sound->flags & AUDIO_ENTRY_FLAG_IS_COMPRESSED) != 0;
        bool inAudo = !isRegular || isEmbedded || isCompressed;

        if (inAudo) {
           // Some chapter data starts an effect before its GML loader has
           // completed audio_group_load(1). The translated data happened to
           // hide this race through different initialization timing, while
           // the official English data silently lost the first effects.
           // Resolve the owned audio group on demand before reading AUDO.
           if (sound->audioGroup > 0 &&
               (uint32_t)sound->audioGroup >= arrlen(ma->base.audioGroups))
               maGroupLoad(&ma->base, sound->audioGroup);
           if (sound->audioGroup < 0 ||
               (uint32_t)sound->audioGroup >= arrlen(ma->base.audioGroups) ||
               ma->base.audioGroups[sound->audioGroup] == nullptr) {
#ifdef PLATFORM_VITA
               char groupId[24];
               snprintf(groupId, sizeof(groupId), "%d", sound->audioGroup);
               vitaAudioLog("embedded_group_missing", sound->name, groupId);
#endif
               fprintf(stderr, "Audio: Missing audio group %d for sound '%s'\n",
                       sound->audioGroup, sound->name);
               return -1;
           }
           // Embedded audio: decode from AUDO chunk memory
            if (0 > sound->audioFile || (uint32_t) sound->audioFile >= ma->base.audioGroups[sound->audioGroup]->audo.count) {
#ifdef PLATFORM_VITA
                vitaAudioLog("embedded_index_invalid", sound->name, nullptr);
#endif
                fprintf(stderr, "Audio: Invalid audio file index %d for sound '%s'\n", sound->audioFile, sound->name);
                return -1;
            }

            DataWin* audioDw = ma->base.audioGroups[sound->audioGroup];
            AudioEntry* entry = &audioDw->audo.entries[sound->audioFile];
            uint8_t* transientData = nullptr;
            const uint8_t* audioData = entry->data;
            if (audioData == nullptr && entry->dataSize > 0 && audioDw->lazyLoadFile != nullptr) {
                transientData = (uint8_t*)safeMalloc(entry->dataSize);
                long previous = ftell(audioDw->lazyLoadFile);
                fseek(audioDw->lazyLoadFile, (long)entry->dataOffset, SEEK_SET);
                size_t got = fread(transientData, 1, entry->dataSize, audioDw->lazyLoadFile);
                fseek(audioDw->lazyLoadFile, previous, SEEK_SET);
                if (got != entry->dataSize) {
                    free(transientData);
#ifdef PLATFORM_VITA
                    vitaAudioLog("embedded_lazy_read_failed", sound->name, nullptr);
#endif
                    fprintf(stderr, "Audio: Failed lazy read for sound '%s'\n", sound->name);
                    return -1;
                }
                audioData = transientData;
            }
            if (audioData == nullptr) {
#ifdef PLATFORM_VITA
                vitaAudioLog("embedded_data_missing", sound->name, nullptr);
#endif
                fprintf(stderr, "Audio: Missing AUDO data for sound '%s'\n", sound->name);
                return -1;
            }
            if (entry->dataSize >= 4 && memcmp(audioData, "OggS", 4) == 0) {
                int channels = 0, sampleRate = 0;
                short* pcm = nullptr;
                int samples = stb_vorbis_decode_memory(audioData, (int)entry->dataSize, &channels, &sampleRate, &pcm);
                if (0 >= samples || pcm == nullptr) {
                    free(transientData);
#ifdef PLATFORM_VITA
                    vitaAudioLog("embedded_ogg_decode_failed", sound->name, nullptr);
#endif
                    fprintf(stderr, "Audio: Failed embedded OGG decode for sound '%s'\n", sound->name);
                    return -1;
                }
                alBufferData(slot->alBuffer, channels == 2 ? AL_FORMAT_STEREO16 : AL_FORMAT_MONO16,
                             pcm, samples * channels * (int)sizeof(short), sampleRate);
                free(pcm);
            } else {
                WAVFile wav = WAV_ParseFileData(audioData, entry->dataSize);
                if (wav.data == nullptr || wav.data_length == 0 ||
                    wav.header.sample_rate == 0 ||
                    (wav.header.number_of_channels != 1 && wav.header.number_of_channels != 2)) {
                    free(transientData);
                    alDeleteBuffers(1, &slot->alBuffer);
#ifdef PLATFORM_VITA
                    vitaAudioLog("embedded_wav_invalid", sound->name, nullptr);
#endif
                    fprintf(stderr, "Audio: Invalid embedded WAV for sound '%s'\n",
                            sound->name != nullptr ? sound->name : "<unnamed>");
                    return -1;
                }
                uint32_t format;
                if (wav.header.number_of_channels == 1)
                    format = wav.header.bits_per_sample == 8 ? AL_FORMAT_MONO8 : AL_FORMAT_MONO16;
                else
                    format = wav.header.bits_per_sample == 8 ? AL_FORMAT_STEREO8 : AL_FORMAT_STEREO16;
                alBufferData(slot->alBuffer, format, wav.data, wav.data_length, wav.header.sample_rate);
                if (wav.data != nullptr) free(wav.data);
            }
            alSourcei(slot->alSource, AL_BUFFER, slot->alBuffer);
            if (!slot->music && cacheSfxBuffer(ma, soundIndex, slot->alBuffer))
                slot->sharedBuffer = true;
            free(transientData);
        } else {
            // External OGG music is streamed on Vita. Decoding an entire track on the
            // main thread caused long stalls at room transitions and consumed a large
            // temporary PCM buffer.
            char* path = resolveExternalPath(ma, sound);
            if (path == nullptr) {
#ifdef PLATFORM_VITA
                vitaAudioLog("external_resolve_failed", sound->file, nullptr);
#endif
                fprintf(stderr, "Audio: Could not resolve path for sound '%s'\n", sound->name);
                return -1;
            }
#ifdef PLATFORM_VITA
            vitaAudioLog("external_resolved", sound->file, path);
#endif
            if (!slot->music) {
                int channels = 0, sampleRate = 0;
                short* pcm = nullptr;
                int samples = stb_vorbis_decode_filename(path, &channels, &sampleRate, &pcm);
                if (samples <= 0 || pcm == nullptr) {
                    alDeleteBuffers(1, &slot->alBuffer);
                    alDeleteSources(1, &slot->alSource);
                    free(path);
                    return -1;
                }
                alBufferData(slot->alBuffer, channels == 2 ? AL_FORMAT_STEREO16 : AL_FORMAT_MONO16,
                             pcm, samples * channels * (int)sizeof(short), sampleRate);
                free(pcm);
                alSourcei(slot->alSource, AL_BUFFER, slot->alBuffer);
                if (cacheSfxBuffer(ma, soundIndex, slot->alBuffer)) slot->sharedBuffer = true;
                free(path);
            } else {
            int err = 0;
            stb_vorbis* v = openStreamingVorbis(path, slot, &err);
            if (v == nullptr) {
#ifdef PLATFORM_VITA
                vitaAudioLog("external_decode_failed", sound->file, path);
#endif
                alDeleteBuffers(1, &slot->alBuffer);
                alDeleteSources(1, &slot->alSource);
                free(path);
                return -1;
            }
            stb_vorbis_info info = stb_vorbis_get_info(v);
            alDeleteBuffers(1, &slot->alBuffer);
            slot->streaming = true;
            slot->loop = loop;
            slot->vorbis = v;
            slot->streamChannels = info.channels;
            slot->streamSampleRate = (int)info.sample_rate;
            slot->streamFormat = info.channels == 2 ? AL_FORMAT_STEREO16 : AL_FORMAT_MONO16;
            slot->streamLengthSeconds = stb_vorbis_stream_length_in_seconds(v);
#ifdef PLATFORM_VITA
            slot->streamBufferTarget = slot->music ? 64 : 3;
#else
            slot->streamBufferTarget = slot->music ? AL_STREAM_BUFFER_COUNT : 3;
#endif
            slot->decodeScratch = (int16_t*)safeMalloc(AL_STREAM_BUFFER_SAMPLES * info.channels * sizeof(int16_t));
            alGenBuffers(AL_STREAM_BUFFER_COUNT, slot->streamBuffers);
            int primed = 0;
#ifdef PLATFORM_VITA
            const int initialStreamBuffers = slot->music ?
                (ma->transitionHold ? 16 : 8) : 1;
#else
            const int initialStreamBuffers = slot->music ? 2 : 1;
#endif
            for (int i = 0; i < initialStreamBuffers; ++i) {
                if (!streamFillBuffer(slot, slot->streamBuffers[i])) break;
                alSourceQueueBuffers(slot->alSource, 1, &slot->streamBuffers[i]);
                primed++;
            }
            if (primed == 0) {
                alDeleteSources(1, &slot->alSource);
                alDeleteBuffers(AL_STREAM_BUFFER_COUNT, slot->streamBuffers);
                stb_vorbis_close(v);
                free(slot->streamCompressedData);
                slot->streamCompressedData = nullptr;
                slot->streamCompressedSize = 0;
                free(slot->decodeScratch);
                slot->streaming = false;
                slot->vorbis = nullptr;
                slot->decodeScratch = nullptr;
                free(path);
                return -1;
            }
            slot->streamPrimedCount = primed;
            free(path);
            }
        }
        }
    }

    // Apply properties
    float volume = isStream ? 1.0f : sound->volume;
    // Streamed OGG music still carries the GameMaker sound-resource pitch.
    // Forcing every stream to 1.0 made assets authored below 1.0 play faster
    // than the original game (notably some Chapter 2 Spamton tracks).
    float pitch = sound != nullptr && sound->pitch != 0.0f ? sound->pitch : 1.0f;
    if (slot->streaming || slot->music) {
        fprintf(stderr, "Audio: playback start name=%s streaming=%d rate=%d pitch=%.4f file=%s\n",
                sound != nullptr && sound->name != nullptr ? sound->name : "<unnamed>",
                slot->streaming ? 1 : 0,
                slot->streaming ? slot->streamSampleRate : 0, pitch,
                streamPath != nullptr ? streamPath :
                    (sound != nullptr && sound->file != nullptr ? sound->file : "<null>"));
    }
    alSourcef(slot->alSource, AL_GAIN, volume * instanceCategoryGain(ma, slot));
    // OpenAL sources are intentionally reused. Always overwrite AL_PITCH,
    // including the neutral 1.0 value, otherwise a battle track can inherit
    // the accelerated pitch left by the previous sound in this slot.
    alSourcef(slot->alSource, AL_PITCH, pitch != 0.0f ? pitch : 1.0f);
    // Sources are reused. A streaming source must explicitly clear AL_LOOPING:
    // otherwise it can inherit AL_TRUE from the previous non-streaming sound
    // in this slot. OpenAL then loops one queue buffer while our decoder also
    // manages the stream loop, eventually leaving the source stopped with its
    // whole queue processed and triggering an expensive recovery every frame.
    // Streaming looping is handled solely by streamFillBuffer().
    alSourcei(slot->alSource, AL_LOOPING,
              slot->streaming ? AL_FALSE : (loop ? AL_TRUE : AL_FALSE));

    // Set up instance tracking
    slot->active = true;
    slot->soundIndex = soundIndex;
    slot->instanceId = SOUND_INSTANCE_ID_BASE + slotIndex;
    slot->currentGain = volume;
    slot->targetGain = volume;
    slot->fadeTimeRemaining = 0.0f;
    slot->fadeTotalTime = 0.0f;
    slot->startGain = volume;
    slot->priority = priority;
    slot->pausedByDisabled = ma->disabled;
    slot->pausedByTransition = ma->transitionHold;

    // Track unique IDs for disambiguation
    ma->nextInstanceCounter++;

    // Room Start can create music while the renderer is still allocating and
    // uploading its destination atlas set. Starting the Vita playback thread
    // in that allocation peak consistently produced a kernel data abort while
    // loading Chapter 5's room_town_south. Keep the fully primed source queued
    // and start it after the destination has actually reached the display.
    if (!ma->transitionHold && !ma->disabled)
        alSourcePlay(slot->alSource);

#ifdef PLATFORM_VITA
    if (!isStream && !slot->music && soundIndex >= 0 && soundIndex < 4096 &&
        !vitaSfxFirstStart[soundIndex]) {
        vitaSfxFirstStart[soundIndex] = 1;
        char detail[64];
        snprintf(detail, sizeof(detail), "group=%d file=%d", sound->audioGroup, sound->audioFile);
        vitaAudioLog(ma->transitionHold ? "sfx_queued" : "sfx_started", sound->name, detail);
    }
    if (slot->streaming) {
        const char* requested = isStream ? streamPath : (sound != nullptr ? sound->file : nullptr);
        vitaAudioLog(ma->transitionHold ? "queued_transition_hold" : "play_started",
                     requested, slot->music ? "music" : "sfx");
    }
#endif

    return slot->instanceId;
}

static void maStopSound(AudioSystem* audio, int32_t soundOrInstance) {
    AlAudioSystem* ma = (AlAudioSystem*) audio;

    if (soundOrInstance >= SOUND_INSTANCE_ID_BASE) {
        // Stop specific instance
        SoundInstance* inst = findInstanceById(ma, soundOrInstance);
        if (inst != nullptr) releaseInstance(inst);
    } else {
        // Stop all instances of this sound resource
        repeat(MAX_SOUND_INSTANCES, i) {
            SoundInstance* inst = &ma->instances[i];
            if (inst->active && inst->soundIndex == soundOrInstance) {
                releaseInstance(inst);
            }
        }
    }
}

static void maStopAll(AudioSystem* audio) {
    AlAudioSystem* ma = (AlAudioSystem*) audio;

    repeat(MAX_SOUND_INSTANCES, i) {
        releaseInstance(&ma->instances[i]);
    }
}

static bool maIsPlaying(AudioSystem* audio, int32_t soundOrInstance) {
    AlAudioSystem* ma = (AlAudioSystem*) audio;

    if (soundOrInstance >= SOUND_INSTANCE_ID_BASE) {
        SoundInstance* inst = findInstanceById(ma, soundOrInstance);
        if (inst == nullptr)
            return false;

        // Streaming sources can flip to AL_STOPPED for a frame during underrun, so trust the active flag instead (cleared by maUpdate when fully drained).
        if (inst->streaming)
            return inst->active;

        return alSourceIsPlaying(inst->alSource);
    } else {
        // Check if any instance of this sound resource is playing
        repeat(MAX_SOUND_INSTANCES, i) {
            SoundInstance* inst = &ma->instances[i];
            if (!inst->active || inst->soundIndex != soundOrInstance) continue;
            if (inst->streaming) return true;
            if (alSourceIsPlaying(inst->alSource)) return true;
        }
        return false;
    }
}

static void maPauseSound(AudioSystem* audio, int32_t soundOrInstance) {
    AlAudioSystem* ma = (AlAudioSystem*) audio;

    if (soundOrInstance >= SOUND_INSTANCE_ID_BASE) {
        SoundInstance* inst = findInstanceById(ma, soundOrInstance);
        if (inst != nullptr) {
            alSourcePause(inst->alSource);
        }
    } else {
        repeat(MAX_SOUND_INSTANCES, i) {
            SoundInstance* inst = &ma->instances[i];
            if (inst->active && inst->soundIndex == soundOrInstance) {
                alSourcePause(inst->alSource);
            }
        }
    }
}

static void resumeInstanceIfReady(SoundInstance* inst) {
    ALint state = 0;
    alGetSourcei(inst->alSource, AL_SOURCE_STATE, &state);
    if (state == AL_PAUSED) {
        alSourcePlay(inst->alSource);
        return;
    }
    // A streaming seek must stop the source to detach its old queue. Treat a
    // stopped source with a freshly rebuilt queue as resumable, matching
    // GameMaker's audio_pause -> set_track_position -> audio_resume sequence.
    if (inst->streaming && state == AL_STOPPED) {
        ALint queued = 0;
        alGetSourcei(inst->alSource, AL_BUFFERS_QUEUED, &queued);
        if (queued > 0) alSourcePlay(inst->alSource);
    }
}

// Vita memory-card reads can occasionally block for 30-40 ms. Keep only the
// compressed OGG for the active stream in normal RAM; PCM remains streamed in
// small OpenAL buffers, so this is a modest allocation without CDRAM cost.
static stb_vorbis* openStreamingVorbis(const char* path, SoundInstance* inst, int* error) {
#ifdef PLATFORM_VITA
    FILE* file = fopen(path, "rb");
    if (file == nullptr) return nullptr;
    if (fseek(file, 0, SEEK_END) != 0) { fclose(file); return nullptr; }
    long length = ftell(file);
    if (length <= 0 || fseek(file, 0, SEEK_SET) != 0) { fclose(file); return nullptr; }
    uint8_t* data = (uint8_t*)safeMalloc((size_t)length);
    if (data == nullptr) { fclose(file); return nullptr; }
    size_t read = fread(data, 1, (size_t)length, file);
    fclose(file);
    if (read != (size_t)length) { free(data); return nullptr; }
    stb_vorbis* vorbis = stb_vorbis_open_memory(data, (int)length, error, nullptr);
    if (vorbis == nullptr) { free(data); return nullptr; }
    inst->streamCompressedData = data;
    inst->streamCompressedSize = (size_t)length;
    return vorbis;
#else
    (void)inst;
    return stb_vorbis_open_filename(path, error, nullptr);
#endif
}

static void maResumeSound(AudioSystem* audio, int32_t soundOrInstance) {
    AlAudioSystem* ma = (AlAudioSystem*) audio;

    if (soundOrInstance >= SOUND_INSTANCE_ID_BASE) {
        SoundInstance* inst = findInstanceById(ma, soundOrInstance);
        if (inst != nullptr && !inst->pausedByDisabled && !inst->pausedByTransition) {
            resumeInstanceIfReady(inst);
        }
    } else {
        repeat(MAX_SOUND_INSTANCES, i) {
            SoundInstance* inst = &ma->instances[i];
            if (inst->active && inst->soundIndex == soundOrInstance &&
                !inst->pausedByDisabled && !inst->pausedByTransition) {
                resumeInstanceIfReady(inst);
            }
        }
    }
}

static void maPauseAll(AudioSystem* audio) {
    AlAudioSystem* ma = (AlAudioSystem*) audio;

    repeat(MAX_SOUND_INSTANCES, i) {
        SoundInstance* inst = &ma->instances[i];
        if (inst->active && alSourceIsPlaying(inst->alSource)) {
            alSourcePause(inst->alSource);
        }
    }
}

static void maResumeAll(AudioSystem* audio) {
    AlAudioSystem* ma = (AlAudioSystem*) audio;

    repeat(MAX_SOUND_INSTANCES, i) {
        SoundInstance* inst = &ma->instances[i];
        if (inst->active && !inst->pausedByDisabled && !inst->pausedByTransition) {
            resumeInstanceIfReady(inst);
        }
    }
}

static void alSuspend(AudioSystem* audio) {
    AlAudioSystem* ma = (AlAudioSystem*) audio;

    repeat(MAX_SOUND_INSTANCES, i) {
        SoundInstance* inst = &ma->instances[i];
        if (inst->active && alSourceIsPlaying(inst->alSource)) {
            alSourcePause(inst->alSource);
        }
    }
}

static void alResume(AudioSystem* audio) {
    AlAudioSystem* ma = (AlAudioSystem*) audio;

    repeat(MAX_SOUND_INSTANCES, i) {
        SoundInstance* inst = &ma->instances[i];
        if (!inst->active) continue;
        ALint state = 0;
        alGetSourcei(inst->alSource, AL_SOURCE_STATE, &state);
        if (state == AL_PAUSED) {
            alSourcePlay(inst->alSource);
        }
    }
}

static void maSetSoundGain(AudioSystem* audio, int32_t soundOrInstance, float gain, uint32_t timeMs) {
    AlAudioSystem* ma = (AlAudioSystem*) audio;

    if (soundOrInstance >= SOUND_INSTANCE_ID_BASE) {
        SoundInstance* inst = findInstanceById(ma, soundOrInstance);
        if (inst != nullptr) {
            if (timeMs == 0) {
                inst->currentGain = gain;
                inst->targetGain = gain;
                inst->fadeTimeRemaining = 0.0f;
                alSourcef(inst->alSource, AL_GAIN, gain * instanceCategoryGain(ma, inst));
            } else {
                inst->startGain = inst->currentGain;
                inst->targetGain = gain;
                inst->fadeTotalTime = (float) timeMs / 1000.0f;
                inst->fadeTimeRemaining = inst->fadeTotalTime;
            }
        }
    } else {
        repeat(MAX_SOUND_INSTANCES, i) {
            SoundInstance* inst = &ma->instances[i];
            if (inst->active && inst->soundIndex == soundOrInstance) {
                if (timeMs == 0) {
                    inst->currentGain = gain;
                    inst->targetGain = gain;
                    inst->fadeTimeRemaining = 0.0f;
                    alSourcef(inst->alSource, AL_GAIN, gain * instanceCategoryGain(ma, inst));
                } else {
                    inst->startGain = inst->currentGain;
                    inst->targetGain = gain;
                    inst->fadeTotalTime = (float) timeMs / 1000.0f;
                    inst->fadeTimeRemaining = inst->fadeTotalTime;
                }
            }
        }
    }
}

static float maGetSoundGain(AudioSystem* audio, int32_t soundOrInstance) {
    AlAudioSystem* ma = (AlAudioSystem*) audio;

    if (soundOrInstance >= SOUND_INSTANCE_ID_BASE) {
        SoundInstance* inst = findInstanceById(ma, soundOrInstance);
        if (inst != nullptr) return inst->currentGain;
    } else {
        repeat(MAX_SOUND_INSTANCES, i) {
            SoundInstance* inst = &ma->instances[i];
            if (inst->active && inst->soundIndex == soundOrInstance) {
                return inst->currentGain;
            }
        }
    }
    return 0.0f;
}

static void maSetSoundPitch(AudioSystem* audio, int32_t soundOrInstance, float pitch) {
    AlAudioSystem* ma = (AlAudioSystem*) audio;

    if (soundOrInstance >= SOUND_INSTANCE_ID_BASE) {
        SoundInstance* inst = findInstanceById(ma, soundOrInstance);
        if (inst != nullptr) {
            alSourcef(inst->alSource, AL_PITCH, pitch);
        }
    } else {
        repeat(MAX_SOUND_INSTANCES, i) {
            SoundInstance* inst = &ma->instances[i];
            if (inst->active && inst->soundIndex == soundOrInstance) {
                alSourcef(inst->alSource, AL_PITCH, pitch);
            }
        }
    }
}

static float maGetSoundPitch(AudioSystem* audio, int32_t soundOrInstance) {
    AlAudioSystem* ma = (AlAudioSystem*) audio;

    float pitch = 1.0f;
    if (soundOrInstance >= SOUND_INSTANCE_ID_BASE) {
        SoundInstance* inst = findInstanceById(ma, soundOrInstance);
        if (inst != nullptr) alGetSourcef(inst->alSource, AL_PITCH, &pitch);
    } else {
        repeat(MAX_SOUND_INSTANCES, i) {
            SoundInstance* inst = &ma->instances[i];
            if (inst->active && inst->soundIndex == soundOrInstance) {
                alGetSourcef(inst->alSource, AL_PITCH, &pitch);
            }
        }
    }
    return pitch;
}

// For streaming instances AL_SEC_OFFSET resets per buffer in the queue, so we combine the dequeued-sample tally with the offset into the currently-playing buffer to report a position over the whole track.
static float streamCursorSeconds(SoundInstance* inst) {
    if (0 >= inst->streamSampleRate)
        return 0.0f;
    
    ALint sampleOffset = 0;
    alGetSourcei(inst->alSource, AL_SAMPLE_OFFSET, &sampleOffset);
    uint64_t total = inst->playedSamples + (uint64_t) sampleOffset;
    return (float) total / (float) inst->streamSampleRate;
}

static float maGetTrackPosition(AudioSystem* audio, int32_t soundOrInstance) {
    AlAudioSystem* ma = (AlAudioSystem*) audio;

    if (soundOrInstance >= SOUND_INSTANCE_ID_BASE) {
        SoundInstance* inst = findInstanceById(ma, soundOrInstance);
        if (inst != nullptr) {
            if (inst->streaming) return streamCursorSeconds(inst);
            float cursor;
            alGetSourcef(inst->alSource, AL_SEC_OFFSET, &cursor);
            return cursor;
        }
    } else {
        repeat(MAX_SOUND_INSTANCES, i) {
            SoundInstance* inst = &ma->instances[i];
            if (inst->active && inst->soundIndex == soundOrInstance) {
                if (inst->streaming) return streamCursorSeconds(inst);
                float cursor;
                alGetSourcef(inst->alSource, AL_SEC_OFFSET, &cursor);
                return cursor;
            }
        }
    }
    return 0.0f;
}

static void setInstanceTrackPosition(AlAudioSystem* ma, SoundInstance* inst, float positionSeconds) {
    if (inst->streaming && inst->vorbis != nullptr) {
        stb_vorbis* v = (stb_vorbis*)inst->vorbis;
        uint32_t sample = (uint32_t)(positionSeconds * (float)inst->streamSampleRate);
        ALint previousState = AL_STOPPED;
        alGetSourcei(inst->alSource, AL_SOURCE_STATE, &previousState);

        // OpenAL only permits processed buffers to be unqueued. room_legend
        // deliberately pauses legend.ogg, seeks to 19.656 s, then resumes it.
        // Merely pausing here left every unprocessed old buffer attached; the
        // failed unqueue calls were followed by queueing the same names again,
        // which made the opening passage restart over and over. Stopping marks
        // the complete queue processed so it can be detached legally.
        alSourceStop(inst->alSource);
        ALint queued = 0;
        alGetSourcei(inst->alSource, AL_BUFFERS_QUEUED, &queued);
        ALuint detached[AL_STREAM_BUFFER_COUNT];
        int detachedCount = 0;
        while (queued > 0) {
            ALuint buf = 0;
            alSourceUnqueueBuffers(inst->alSource, 1, &buf);
            queued--;
            if (buf != 0 && detachedCount < AL_STREAM_BUFFER_COUNT)
                detached[detachedCount++] = buf;
        }

        // Keep the buffer table aligned with the names OpenAL returned. This
        // also handles a seek while the transition-safe queue is still growing.
        for (int i = 0; i < detachedCount; i++)
            inst->streamBuffers[i] = detached[i];

        if (!stb_vorbis_seek(v, sample))
            stb_vorbis_seek_start(v);
        inst->playedSamples = sample;
        inst->streamEnded = false;

        // A short clean lead is enough here. maUpdate grows it to the normal
        // target incrementally instead of decoding several seconds in the
        // Draw event that requested the seek.
        int filled = 0;
        int seekPrime = inst->music ? 16 : 2;
        if (seekPrime > inst->streamBufferTarget) seekPrime = inst->streamBufferTarget;
        for (int i = 0; i < seekPrime; ++i) {
            ALuint buf = inst->streamBuffers[i];
            if (streamFillBuffer(inst, buf)) {
                alSourceQueueBuffers(inst->alSource, 1, &buf);
                filled++;
            } else {
                inst->streamEnded = true;
                break;
            }
        }
        inst->streamPrimedCount = filled;

        // Preserve GameMaker's pause semantics. room_legend explicitly calls
        // audio_resume_sound after seeking; starting it here would bypass the
        // timing gate in the cutscene.
        if (filled > 0 && previousState == AL_PLAYING &&
            !inst->pausedByTransition && !inst->pausedByDisabled && !ma->disabled) {
            alSourcePlay(inst->alSource);
        }
#ifdef PLATFORM_VITA
        char seekDetail[96];
        snprintf(seekDetail, sizeof(seekDetail), "position=%.3f state=%d buffers=%d",
                 positionSeconds, (int)previousState, filled);
        vitaAudioLog("track_seek_rebuilt", inst->music ? "music" : "sfx", seekDetail);
#endif
    } else {
        // Non-streaming fallback: use standard OpenAL offset
        alSourcef(inst->alSource, AL_SEC_OFFSET, positionSeconds);
    }
}

static void maSetTrackPosition(AudioSystem* audio, int32_t soundOrInstance, float positionSeconds) {
    AlAudioSystem* ma = (AlAudioSystem*) audio;

    if (soundOrInstance >= SOUND_INSTANCE_ID_BASE) {
        SoundInstance* inst = findInstanceById(ma, soundOrInstance);
        if (inst != nullptr) {
            setInstanceTrackPosition(ma, inst, positionSeconds);
        }
    } else {
        repeat(MAX_SOUND_INSTANCES, i) {
            SoundInstance* inst = &ma->instances[i];
            if (inst->active && inst->soundIndex == soundOrInstance) {
                setInstanceTrackPosition(ma, inst, positionSeconds);
            }
        }
    }
}

// Total length of a loaded sound. Works on both SOND index and active instance ids.
static float maGetSoundLength(AudioSystem* audio, int32_t soundOrInstance) {
    AlAudioSystem* ma = (AlAudioSystem*) audio;

    SoundInstance* match = nullptr;
    if (soundOrInstance >= SOUND_INSTANCE_ID_BASE) {
        match = findInstanceById(ma, soundOrInstance);
    } else {
        repeat(MAX_SOUND_INSTANCES, i) {
            SoundInstance* inst = &ma->instances[i];
            if (inst->active && inst->soundIndex == soundOrInstance) {
                match = inst;
                break;
            }
        }
    }
    if (match != nullptr) {
        if (match->streaming) return match->streamLengthSeconds;
        float seconds = 0.0f;
        alGetSourceLengthSec(match->alBuffer, &seconds);
        return seconds;
    }

    // No active instance: GMS audio_sound_length(soundIndex) must still return the asset's duration.
    if (soundOrInstance >= SOUND_INSTANCE_ID_BASE || soundOrInstance >= AUDIO_STREAM_INDEX_BASE)
        return 0.0f;

    DataWin* dw = ma->base.audioGroups[0];
    if (dw == nullptr || 0 > soundOrInstance || (uint32_t) soundOrInstance >= dw->sond.count)
        return 0.0f;

    Sound* sound = &dw->sond.sounds[soundOrInstance];

    bool isRegular = (sound->flags & AUDIO_ENTRY_FLAG_REGULAR) == AUDIO_ENTRY_FLAG_REGULAR;
    bool isEmbedded = (sound->flags & AUDIO_ENTRY_FLAG_IS_EMBEDDED) != 0;
    bool isCompressed = (sound->flags & AUDIO_ENTRY_FLAG_IS_COMPRESSED) != 0;
    bool inAudo = !isRegular || isEmbedded || isCompressed;
    if (inAudo) {
        if (0 > sound->audioFile || (uint32_t) sound->audioFile >= ma->base.audioGroups[sound->audioGroup]->audo.count) return 0.0f;
        DataWin* audioDw = ma->base.audioGroups[sound->audioGroup];
        AudioEntry* entry = &audioDw->audo.entries[sound->audioFile];
        uint8_t* transientData = nullptr;
        const uint8_t* audioData = entry->data;
        if (audioData == nullptr && entry->dataSize > 0 && audioDw->lazyLoadFile != nullptr) {
            transientData = (uint8_t*)safeMalloc(entry->dataSize);
            long previous = ftell(audioDw->lazyLoadFile);
            fseek(audioDw->lazyLoadFile, (long)entry->dataOffset, SEEK_SET);
            size_t got = fread(transientData, 1, entry->dataSize, audioDw->lazyLoadFile);
            fseek(audioDw->lazyLoadFile, previous, SEEK_SET);
            if (got != entry->dataSize) { free(transientData); return 0.0f; }
            audioData = transientData;
        }
        if (audioData == nullptr) return 0.0f;

        float seconds = 0.0f;
        if (entry->dataSize >= 4 && memcmp(audioData, "OggS", 4) == 0) {
            int err = 0;
            stb_vorbis* v = stb_vorbis_open_memory(audioData, (int)entry->dataSize, &err, nullptr);
            if (v != nullptr) {
                seconds = stb_vorbis_stream_length_in_seconds(v);
                stb_vorbis_close(v);
            }
        } else {
            WAVFile wav = WAV_ParseFileData(audioData, entry->dataSize);
            if (wav.header.byte_rate > 0) seconds = (float)wav.header.data_size / (float)wav.header.byte_rate;
            if (wav.data != nullptr) free(wav.data);
        }
        free(transientData);
        return seconds;
    }

    char* path = resolveExternalPath(ma, sound);
    if (path == nullptr) return 0.0f;
    int err = 0;
    stb_vorbis* v = stb_vorbis_open_filename(path, &err, nullptr);
    free(path);
    if (v == nullptr) return 0.0f;
    float seconds = stb_vorbis_stream_length_in_seconds(v);
    stb_vorbis_close(v);
    return seconds;
}

static void maSetMasterGainForListener(AudioSystem* audio, float gain, int32_t id) {
    (void)audio;
    (void)id;
    alListenerf(AL_GAIN, gain);
}

static void maSetMasterGain(AudioSystem* audio, float gain) {
    (void)audio;
    alListenerf(AL_GAIN, gain);
}

static void maSetChannelCount(MAYBE_UNUSED AudioSystem* audio, MAYBE_UNUSED int32_t count) {
    // miniaudio handles channel management internally, this is a no-op
}

static void maGroupLoad(AudioSystem* audio, int32_t groupIndex) {
    if (groupIndex > 0) {
        if ((uint32_t)groupIndex < arrlen(audio->audioGroups) &&
            audio->audioGroups[groupIndex] != nullptr)
            return;
        int sz = snprintf(nullptr, 0, "audiogroup%d.dat", groupIndex);
        char *buf = (char *)safeMalloc(sz + 1);
        snprintf(buf, sz + 1, "audiogroup%d.dat", groupIndex);

        // The original runner does not care if the file doesn't exist (this may happen if someone uses "audio_group_load" on a non-existent group)
        FileSystem* fileSystem = ((AlAudioSystem*)audio)->fileSystem;
        char* resolvedPath = fileSystem->vtable->resolvePath(fileSystem, buf);
        if (resolvedPath == nullptr || !fileSystem->vtable->fileExists(fileSystem, resolvedPath)) {
#ifdef PLATFORM_VITA
            char groupId[24];
            snprintf(groupId, sizeof(groupId), "%d", groupIndex);
            vitaAudioLog("group_file_missing", groupId, resolvedPath);
#endif
            fprintf(stderr, "Audio: Wanted to load Audio Group %d, but Audio Group %d does not exist!\n", groupIndex, groupIndex);
            free(resolvedPath);
            free(buf);
            return;
        }

        DataWinParserOptions options = {0};
        options.parseAudo = true;
        options.lazyLoadAudio = true;
        DataWin *audioGroup = DataWin_parse(resolvedPath, options);
        arrput(audio->audioGroups, audioGroup);
#ifdef PLATFORM_VITA
        char groupId[24];
        snprintf(groupId, sizeof(groupId), "%d", groupIndex);
        vitaAudioLog(audioGroup != nullptr ? "group_loaded_lazy" : "group_parse_failed",
                     groupId, resolvedPath);
#endif
        free(resolvedPath);
        free(buf);
    }
}

static bool maGroupIsLoaded(MAYBE_UNUSED AudioSystem* audio, MAYBE_UNUSED int32_t groupIndex) {
    return (arrlen(audio->audioGroups) > groupIndex);
}

// ===[ Audio Streams ]===

static int32_t maCreateStream(AudioSystem* audio, const char* filename) {
    AlAudioSystem* ma = (AlAudioSystem*) audio;

    // Find a free stream slot
    int32_t freeSlot = -1;
    repeat(MAX_AUDIO_STREAMS, i) {
        if (!ma->streams[i].active) {
            freeSlot = (int32_t) i;
            break;
        }
    }

    if (0 > freeSlot) {
        fprintf(stderr, "Audio: No free stream slots for '%s'\n", filename);
        return -1;
    }

    char* resolved = ma->fileSystem->vtable->resolvePath(ma->fileSystem, filename);
    if (resolved == nullptr || !ma->fileSystem->vtable->fileExists(ma->fileSystem, resolved)) {
        free(resolved);
        resolved = resolveSharedMusicPath(ma->fileSystem, filename);
    }
    if (resolved == nullptr) {
#ifdef PLATFORM_VITA
        vitaAudioLog("resolve_failed", filename, nullptr);
#endif
        fprintf(stderr, "Audio: Could not resolve path for stream '%s'\n", filename);
        return -1;
    }

    ma->streams[freeSlot].active = true;
    ma->streams[freeSlot].filePath = resolved;

    int32_t streamIndex = AUDIO_STREAM_INDEX_BASE + freeSlot;
#ifdef PLATFORM_VITA
    vitaAudioLog("resolved", filename, resolved);
#endif
    fprintf(stderr, "Audio: Created stream %d for '%s' -> '%s'\n", streamIndex, filename, resolved);
    return streamIndex;
}

static bool maDestroyStream(AudioSystem* audio, int32_t streamIndex) {
    AlAudioSystem* ma = (AlAudioSystem*) audio;

    int32_t slotIndex = streamIndex - AUDIO_STREAM_INDEX_BASE;
    if (0 > slotIndex || slotIndex >= MAX_AUDIO_STREAMS) {
        fprintf(stderr, "Audio: Invalid stream index %d for destroy\n", streamIndex);
        return false;
    }

    AudioStreamEntry* entry = &ma->streams[slotIndex];
    if (!entry->active) return false;

    // Stop all sound instances that were playing this stream
    repeat(MAX_SOUND_INSTANCES, i) {
        SoundInstance* inst = &ma->instances[i];
        if (inst->active && inst->soundIndex == streamIndex) {
            releaseInstance(inst);
        }
    }

    free(entry->filePath);
    entry->filePath = nullptr;
    entry->active = false;
    fprintf(stderr, "Audio: Destroyed stream %d\n", streamIndex);
    return true;
}

// ===[ Vtable ]===

static AudioSystemVtable AlAudioSystemVtable;

// ===[ Lifecycle ]===

AlAudioSystem* AlAudioSystem_create(void) {
    AlAudioSystem* ma = (AlAudioSystem *)safeCalloc(1, sizeof(AlAudioSystem));
    AlAudioSystemVtable.init = maInit;
    AlAudioSystemVtable.destroy = maDestroy;
    AlAudioSystemVtable.update = maUpdate;
    AlAudioSystemVtable.playSound = maPlaySound;
    AlAudioSystemVtable.stopSound = maStopSound;
    AlAudioSystemVtable.stopAll = maStopAll;
    AlAudioSystemVtable.isPlaying = maIsPlaying;
    AlAudioSystemVtable.pauseSound = maPauseSound;
    AlAudioSystemVtable.resumeSound = maResumeSound;
    AlAudioSystemVtable.pauseAll = maPauseAll;
    AlAudioSystemVtable.resumeAll = maResumeAll;
    AlAudioSystemVtable.suspend = alSuspend;
    AlAudioSystemVtable.resume = alResume;
    AlAudioSystemVtable.setSoundGain = maSetSoundGain;
    AlAudioSystemVtable.getSoundGain = maGetSoundGain;
    AlAudioSystemVtable.setSoundPitch = maSetSoundPitch;
    AlAudioSystemVtable.getSoundPitch = maGetSoundPitch;
    AlAudioSystemVtable.getTrackPosition = maGetTrackPosition;
    AlAudioSystemVtable.setTrackPosition = maSetTrackPosition;
    AlAudioSystemVtable.getSoundLength = maGetSoundLength;
    AlAudioSystemVtable.setMasterGain = maSetMasterGain;
    AlAudioSystemVtable.setMasterGainForListener = maSetMasterGainForListener;
    AlAudioSystemVtable.setChannelCount = maSetChannelCount;
    AlAudioSystemVtable.groupLoad = maGroupLoad;
    AlAudioSystemVtable.groupIsLoaded = maGroupIsLoaded;
    AlAudioSystemVtable.createStream = maCreateStream;
    AlAudioSystemVtable.destroyStream = maDestroyStream;
    ma->base.vtable = &AlAudioSystemVtable;
    return ma;
}

static bool shouldPreloadChapterSfx(const char* name) {
    if (name == nullptr) return false;
    static const char* const priority[] = {
        "snd_step1", "snd_step2", "snd_text", "snd_menumove",
        "snd_select", "snd_cantselect", "snd_pause", "snd_save",
        "snd_battleenter", "snd_damage", "snd_hurt1", "snd_hurtsmall",
        "snd_hit", "snd_swing", "snd_smallswing", "snd_heavyswing",
        "snd_criticalswing", "snd_graze", "snd_spare", "snd_spellcast",
        "snd_item", "snd_equip", "snd_power", "snd_levelup",
        "snd_rudebuster_hit", "snd_rudebuster_swing", "snd_bump",
        "snd_impact", "snd_grab", "snd_jump", "snd_wing", "snd_won"
    };
    for (uint32_t i = 0; i < sizeof(priority) / sizeof(priority[0]); ++i)
        if (strcmp(name, priority[i]) == 0) return true;
    return false;
}

uint32_t AlAudioSystem_preloadChapterSfx(AlAudioSystem* ma, bool preloadBuffers) {
    if (ma == nullptr || arrlen(ma->base.audioGroups) == 0) return 0;
    DataWin* dw = ma->base.audioGroups[0];
    float oldSfxGain = ma->sfxGain;
    ma->sfxGain = 0.0f;
    uint32_t prepared = 0;
    if (preloadBuffers) {
        for (uint32_t i = 0; i < dw->sond.count && prepared < MAX_SFX_BUFFER_CACHE; ++i) {
            Sound* sound = &dw->sond.sounds[i];
            if (!sound->present || !shouldPreloadChapterSfx(sound->name)) continue;
            int32_t instance = maPlaySound((AudioSystem*)ma, (int32_t)i, 0, false);
            if (instance >= SOUND_INSTANCE_ID_BASE) {
                maStopSound((AudioSystem*)ma, instance);
                if (findCachedSfxBuffer(ma, (int32_t)i) != 0) prepared++;
            }
        }
    }
    ma->sfxGain = oldSfxGain;
    // Reserve a practical gameplay pool while the loading screen is visible.
    // Extra concurrent slots remain lazy to avoid allocating all 128 sources.
    for (int i = 0; i < 32; ++i)
        if (ma->instances[i].alSource == 0) alGenSources(1, &ma->instances[i].alSource);
    return prepared;
}

void AlAudioSystem_setCategoryGains(AlAudioSystem* ma, float musicGain, float sfxGain) {
    if (ma == nullptr) return;
    ma->musicGain = musicGain;
    ma->sfxGain = sfxGain;
    repeat(MAX_SOUND_INSTANCES, i) {
        SoundInstance* inst = &ma->instances[i];
        // A room change may retire a source just before the Vita settings
        // overlay updates its sliders. Never submit a stale OpenAL handle to
        // the Vita mixer; its backend does not tolerate that race reliably.
        if (inst->active && inst->alSource != 0 && alIsSource(inst->alSource))
            alSourcef(inst->alSource, AL_GAIN, inst->currentGain * instanceCategoryGain(ma, inst));
    }
}

void AlAudioSystem_setDisabled(AlAudioSystem* ma, bool disabled) {
    if (ma == nullptr || ma->disabled == disabled) return;
    ma->disabled = disabled;
    repeat(MAX_SOUND_INSTANCES, i) {
        SoundInstance* inst = &ma->instances[i];
        if (!inst->active || inst->alSource == 0 || !alIsSource(inst->alSource)) continue;
        if (disabled) {
            inst->pausedByDisabled = alSourceIsPlaying(inst->alSource);
            if (inst->pausedByDisabled) alSourcePause(inst->alSource);
        } else {
            bool resume = inst->pausedByDisabled && !inst->pausedByTransition;
            inst->pausedByDisabled = false;
            if (resume) alSourcePlay(inst->alSource);
        }
    }
}

void AlAudioSystem_setTransitionHold(AlAudioSystem* ma, bool held) {
    if (ma == nullptr || ma->transitionHold == held) return;
    ma->transitionHold = held;
    repeat(MAX_SOUND_INSTANCES, i) {
        SoundInstance* inst = &ma->instances[i];
        if (!inst->active || inst->alSource == 0 || !alIsSource(inst->alSource)) continue;
        if (held) {
            inst->pausedByTransition = alSourceIsPlaying(inst->alSource);
            if (inst->pausedByTransition) alSourcePause(inst->alSource);
        } else {
            bool resume = inst->pausedByTransition && !inst->pausedByDisabled && !ma->disabled;
            inst->pausedByTransition = false;
            if (resume) {
                if (inst->streaming) {
                    ALint processed = 0;
                    alGetSourcei(inst->alSource, AL_BUFFERS_PROCESSED, &processed);
                    while (processed > 0) {
                        ALuint buf;
                        alSourceUnqueueBuffers(inst->alSource, 1, &buf);
                        processed--;
                        if (!inst->streamEnded) {
                            if (streamFillBuffer(inst, buf)) {
                                alSourceQueueBuffers(inst->alSource, 1, &buf);
                            } else {
                                inst->streamEnded = true;
                            }
                        }
                    }
                }
                ALint queued = 0;
                if (inst->streaming)
                    alGetSourcei(inst->alSource, AL_BUFFERS_QUEUED, &queued);
                if (!inst->streaming || queued > 0)
                    alSourcePlay(inst->alSource);
            }
        }
    }
}
