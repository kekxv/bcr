/*
  Simple DirectMedia Layer
  Copyright (C) 1997-2026 Sam Lantinga <slouken@libsdl.org>

  This software is provided 'as-is', without any express or implied
  warranty.  In no event will the authors be held liable for any damages
  arising from the use of this software.

  Permission is granted to anyone to use this software for any purpose,
  including commercial applications, and to alter it and redistribute it
  freely, subject to the following restrictions:

  1. The origin of this software must not be misrepresented; you must not
     claim that you wrote the original software. If you use this software
     in a product, an acknowledgment in the product documentation would be
     appreciated but is not required.
  2. Altered source versions must be plainly marked as such, and must not be
     misrepresented as being the original software.
  3. This notice may not be removed or altered from any source distribution.
*/

#ifndef SDL_build_config_linux_h_
#define SDL_build_config_linux_h_
#define SDL_build_config_h_

#include <SDL3/SDL_platform_defines.h>

/**
 *  \file SDL_build_config_linux.h
 *
 *  This is the configuration for Linux builds using Bazel.
 *  The actual feature enables are controlled via Bazel build flags.
 */

/* C library headers */
#define HAVE_STDARG_H 1
#define HAVE_STDDEF_H 1
#define HAVE_STDINT_H 1
#define HAVE_STDIO_H 1
#define HAVE_STDLIB_H 1
#define HAVE_STRING_H 1
#define HAVE_STRINGS_H 1
#define HAVE_WCHAR_H 1
#define HAVE_INTTYPES_H 1
#define HAVE_LIMITS_H 1
#define HAVE_MATH_H 1
#define HAVE_ALLOCA_H 1
#define HAVE_CTYPE_H 1
#define HAVE_FLOAT_H 1
#define HAVE_SIGNAL_H 1
#define HAVE_SYS_TYPES_H 1
#define HAVE_LIBC 1

/* C library functions */
#define HAVE_MALLOC 1
#define HAVE_CALLOC 1
#define HAVE_REALLOC 1
#define HAVE_FREE 1
#define HAVE_GETENV 1
#define HAVE_SETENV 1
#define HAVE_PUTENV 1
#define HAVE_UNSETENV 1
#define HAVE_ABS 1
#define HAVE_MEMSET 1
#define HAVE_MEMCPY 1
#define HAVE_MEMMOVE 1
#define HAVE_MEMCMP 1
#define HAVE_STRLEN 1
#define HAVE_STRCHR 1
#define HAVE_STRRCHR 1
#define HAVE_STRSTR 1
#define HAVE_STRTOL 1
#define HAVE_STRTOUL 1
#define HAVE_STRTOLL 1
#define HAVE_STRTOULL 1
#define HAVE_STRTOD 1
#define HAVE_ATOI 1
#define HAVE_ATOF 1
#define HAVE_STRCMP 1
#define HAVE_STRNCMP 1
#define HAVE_VSSCANF 1
#define HAVE_VSNPRINTF 1

/* Unix-specific functions */
#define HAVE_DLOPEN 1
#define HAVE_GCC_ATOMICS 1
#define HAVE_NANOSLEEP 1
#define HAVE_CLOCK_GETTIME 1
#define HAVE_MPROTECT 1
#define HAVE_POLL 1

/* Thread support */
#define SDL_THREAD_PTHREAD 1
#define SDL_THREAD_PTHREAD_RECURSIVE_MUTEX 1

/* Timer support */
#define SDL_TIMER_UNIX 1

/* Time support */
#define SDL_TIME_UNIX 1

/* Shared object loading */
#define SDL_LOADSO_DLOPEN 1

/* Filesystem */
#define SDL_FILESYSTEM_UNIX 1
#define SDL_FSOPS_POSIX 1

/* Process support */
#define SDL_PROCESS_POSIX 1

/* Audio drivers */
#define SDL_AUDIO_DRIVER_DISK 1
#define SDL_AUDIO_DRIVER_DUMMY 1

/* Video drivers */
#define SDL_VIDEO_DRIVER_DUMMY 1
#define SDL_VIDEO_DRIVER_OFFSCREEN 1
#define SDL_VIDEO_OPENGL_ES2 1
#define SDL_VIDEO_OPENGL_EGL 1
#define SDL_VIDEO_RENDER_OGL_ES2 1

/* Input drivers */
#define HAVE_LINUX_INPUT_H 1
#define SDL_INPUT_LINUXEV 1
#define SDL_JOYSTICK_LINUX 1
#define SDL_JOYSTICK_VIRTUAL 1
#define SDL_HAPTIC_LINUX 1

/* Power */
#define SDL_POWER_LINUX 1

/* Sensor */
#define SDL_SENSOR_DUMMY 1

/* Camera */
#define SDL_CAMERA_DRIVER_DUMMY 1

/* Dialog */
#define SDL_DIALOG_DUMMY 1

/* Tray */
#define SDL_TRAY_DUMMY 1

#endif /* SDL_build_config_linux_h_ */
