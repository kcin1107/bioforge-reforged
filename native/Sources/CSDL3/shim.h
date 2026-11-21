// SDL3 for Swift. SDL_main.h is left out on purpose: the shell has its own main.swift. Swift can't import SDL's flag macros, so the ones used are repeated here.
#include <SDL3/SDL.h>

static const SDL_InitFlags BF_INIT_SHELL = SDL_INIT_VIDEO | SDL_INIT_AUDIO | SDL_INIT_GAMEPAD;
static const SDL_WindowFlags BF_WINDOW_RESIZABLE = SDL_WINDOW_RESIZABLE;
static const SDL_WindowFlags BF_WINDOW_HIGH_PIXEL_DENSITY = SDL_WINDOW_HIGH_PIXEL_DENSITY;
static const SDL_WindowFlags BF_WINDOW_HIDDEN = SDL_WINDOW_HIDDEN;
static const SDL_MessageBoxFlags BF_MESSAGEBOX_WARNING = SDL_MESSAGEBOX_WARNING;
static const SDL_MessageBoxFlags BF_MESSAGEBOX_INFORMATION = SDL_MESSAGEBOX_INFORMATION;
static const SDL_MessageBoxButtonFlags BF_BUTTON_RETURNKEY_DEFAULT = SDL_MESSAGEBOX_BUTTON_RETURNKEY_DEFAULT;
static const SDL_MessageBoxButtonFlags BF_BUTTON_ESCAPEKEY_DEFAULT = SDL_MESSAGEBOX_BUTTON_ESCAPEKEY_DEFAULT;
static const SDL_Keymod BF_KMOD_GUI = SDL_KMOD_LGUI | SDL_KMOD_RGUI;
static const SDL_Keymod BF_KMOD_ALT = SDL_KMOD_LALT | SDL_KMOD_RALT;
static const SDL_Keymod BF_KMOD_LSHIFT = SDL_KMOD_LSHIFT;
static const SDL_Keymod BF_KMOD_RSHIFT = SDL_KMOD_RSHIFT;
static const SDL_Keymod BF_KMOD_LCTRL = SDL_KMOD_LCTRL;
static const SDL_Keymod BF_KMOD_RCTRL = SDL_KMOD_RCTRL;
static const SDL_Keymod BF_KMOD_LALT = SDL_KMOD_LALT;
static const SDL_Keymod BF_KMOD_RALT = SDL_KMOD_RALT;
static const SDL_Keymod BF_KMOD_LGUI = SDL_KMOD_LGUI;
static const SDL_Keymod BF_KMOD_RGUI = SDL_KMOD_RGUI;
