cmake_minimum_required(VERSION 3.14)

if(NOT DEFINED ENV{VITASDK})
  message(FATAL_ERROR "VITASDK nao definido")
endif()

set(CMAKE_TOOLCHAIN_FILE "$ENV{VITASDK}/share/vita.toolchain.cmake" CACHE PATH "Vita toolchain")
project(undertale_yellow_vita C CXX)
include("$ENV{VITASDK}/share/vita.cmake" REQUIRED)
set(VITA_MKSFOEX_FLAGS "-d ATTRIBUTE2=12")

set(CMAKE_C_STANDARD 99)
set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS} -O2 -Wall -Wextra")
set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -mfloat-abi=softfp")

file(GLOB BUTTERSCOTCH_SOURCES ../butterscotch/src/*.c)
file(GLOB RENDERER_SOURCES
  ../butterscotch/src/gl/*.c
  ../butterscotch/src/gl_common/*.c
  ../butterscotch/src/gl_legacy/*.c
  ../butterscotch/src/image/*.c
)

add_executable(${PROJECT_NAME}
  source/main.c
  source/vita_compat.c
  source/vita_settings.c
  ${BUTTERSCOTCH_SOURCES}
  ${RENDERER_SOURCES}
  ../butterscotch/src/audio/openal/al_audio_system.c
  ../butterscotch/src/audio/openal/wave.c
  ../butterscotch/src/android/stb_impl.c
  ../butterscotch/vendor/md5/md5.c
  ../butterscotch/vendor/sha1/sha1.c
  ../butterscotch/vendor/base64/base64.c
  ../butterscotch/vendor/bzip2/bz_internal_error.c
  ../butterscotch/vendor/bzip2/bzlib.c
  ../butterscotch/vendor/bzip2/crctable.c
  ../butterscotch/vendor/bzip2/decompress.c
  ../butterscotch/vendor/bzip2/huffman.c
  ../butterscotch/vendor/bzip2/randtable.c
)

set_target_properties(${PROJECT_NAME} PROPERTIES LINKER_LANGUAGE CXX)
file(GLOB UI_ASSET_SOURCES "${CMAKE_SOURCE_DIR}/../../data/assets/UI/*.png")
set(UI_ASSET_VPK_FILES)
foreach(UI_ASSET_SOURCE ${UI_ASSET_SOURCES})
  get_filename_component(UI_ASSET_NAME "${UI_ASSET_SOURCE}" NAME)
  list(APPEND UI_ASSET_VPK_FILES "${UI_ASSET_SOURCE}" "assets/ui/${UI_ASSET_NAME}")
endforeach()
file(GLOB SOUND_ASSET_SOURCES "${CMAKE_SOURCE_DIR}/../../data/assets/sounds/*.*")
set(SOUND_ASSET_VPK_FILES)
foreach(SOUND_ASSET_SOURCE ${SOUND_ASSET_SOURCES})
  get_filename_component(SOUND_ASSET_NAME "${SOUND_ASSET_SOURCE}" NAME)
  list(APPEND SOUND_ASSET_VPK_FILES "${SOUND_ASSET_SOURCE}" "assets/sounds/${SOUND_ASSET_NAME}")
endforeach()
target_include_directories(${PROJECT_NAME} PRIVATE
  ../butterscotch/src
  ../butterscotch/src/audio/openal
  ../butterscotch/src/gl_common
  ../butterscotch/src/gl
  ../butterscotch/src/gl_legacy
  ../butterscotch/src/image
  ../butterscotch/vendor/stb/ds
  ../butterscotch/vendor/stb/image
  ../butterscotch/vendor/stb/image_write
  ../butterscotch/vendor/stb/vorbis
  ../butterscotch/vendor/bzip2
  ../butterscotch/vendor/md5
  ../butterscotch/vendor/sha1
  ../butterscotch/vendor/base64
)

target_compile_definitions(${PROJECT_NAME} PRIVATE
  ENABLE_WAD17 ENABLE_LEGACY_GL PLATFORM_VITA USE_OPENAL
  BUTTERSCOTCH_COMMIT_HASH="undertale-yellow-vita"
  BUTTERSCOTCH_COMMIT_DATE="2026-08-29"
)

target_link_libraries(${PROJECT_NAME}
  ${CMAKE_SOURCE_DIR}/../../third_party/vitaGL-nosplash/libvitaGL.a
  vitashark SceShaccCgExt taihen_stub SceShaccCg_stub
  SceAppMgr_stub SceCommonDialog_stub SceCtrl_stub SceDisplay_stub
  SceGxm_stub SceKernelDmacMgr_stub ScePower_stub SceRtc_stub
  SceSysmem_stub SceTouch_stub kubridge_stub mathneon
  openal pthread SceAudio_stub SceAudioIn_stub z m
)

vita_create_self(eboot.bin ${PROJECT_NAME} UNSAFE)
vita_create_vpk(UndertaleYellow.vpk UTYV00001 eboot.bin
  VERSION 00.02
  NAME "Undertale Yellow"
  FILE
    ${CMAKE_SOURCE_DIR}/../../data/assets/LiveArea/icon0.png sce_sys/icon0.png
    ${CMAKE_SOURCE_DIR}/../../data/assets/LiveArea/pic0.png sce_sys/pic0.png
    ${CMAKE_SOURCE_DIR}/../../data/assets/LiveArea/startup.png sce_sys/livearea/contents/startup.png
    ${CMAKE_SOURCE_DIR}/../../data/assets/LiveArea/bg0.png sce_sys/livearea/contents/bg0.png
    ${CMAKE_SOURCE_DIR}/../../data/assets/LiveArea/template.xml sce_sys/livearea/contents/template.xml
    ${CMAKE_SOURCE_DIR}/../../data/assets/Wolff.png assets/Wolff.png
    ${UI_ASSET_VPK_FILES}
    ${SOUND_ASSET_VPK_FILES}
)
