// Minimal d3d9 cursor-position fix for the 3913 client.
//
// The client positions its Direct3D hardware cursor in the scaled virtual
// desktop coordinate space (desktopScale = 0.5 for 200% UI).  That makes the
// cursor move at half speed / in 2px steps compared with the desktop.
//
// This proxy loads the real d3d9.dll, hooks IDirect3D9::CreateDevice and
// replaces IDirect3DDevice9::SetCursorPosition with a version that uses the
// real OS cursor position (client coordinates).  UI hit-testing is untouched;
// only the hardware cursor is placed at the raw pixel position.

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <d3d9.h>
#include <stdio.h>
#include <stdarg.h>
#include <string.h>
#include <share.h>

#pragma comment(lib, "d3d9.lib")
#pragma comment(lib, "user32.lib")

static HMODULE g_self = NULL;
static HMODULE g_real = NULL;
static IDirect3D9* (WINAPI* g_realCreate9)(UINT) = NULL;
static FILE* g_log = NULL;
static CRITICAL_SECTION g_cs;
static HWND g_hwnd = NULL;
static int g_logCount = 0;
static int g_enabled = 1;

static void** g_d3d9Vtbl = NULL;
static void** g_devVtbl = NULL;

typedef HRESULT (WINAPI* PFN_CreateDevice)(IDirect3D9*, UINT, D3DDEVTYPE, HWND, DWORD,
                                           D3DPRESENT_PARAMETERS*, IDirect3DDevice9**);
typedef HRESULT (WINAPI* PFN_SetCursorPosition)(IDirect3DDevice9*, UINT, UINT, DWORD);

static PFN_CreateDevice g_origCreateDevice = NULL;
static PFN_SetCursorPosition g_origSetCursorPosition = NULL;

static void logf_(const char* fmt, ...)
{
    if (!g_log) return;
    EnterCriticalSection(&g_cs);
    va_list ap;
    va_start(ap, fmt);
    vfprintf(g_log, fmt, ap);
    va_end(ap);
    fputc('\n', g_log);
    fflush(g_log);
    LeaveCriticalSection(&g_cs);
}

static void log_init(void)
{
    wchar_t path[MAX_PATH];
    GetModuleFileNameW(g_self, path, MAX_PATH);
    wchar_t* slash = wcsrchr(path, L'\\');
    if (slash) slash[1] = 0;
    wcscat_s(path, MAX_PATH, L"cursor_fix.log");
    g_log = _wfsopen(path, L"a", _SH_DENYNO);
}

static void read_ini(void)
{
    wchar_t path[MAX_PATH];
    GetModuleFileNameW(g_self, path, MAX_PATH);
    wchar_t* slash = wcsrchr(path, L'\\');
    if (slash) slash[1] = 0;
    wcscat_s(path, MAX_PATH, L"cursor_fix.ini");
    g_enabled = GetPrivateProfileIntW(L"cursor_fix", L"enabled", 1, path);
    logf_("config: enabled=%d", g_enabled);
}

static HRESULT WINAPI Hook_SetCursorPosition(IDirect3DDevice9* self, UINT X, UINT Y, DWORD Flags)
{
    POINT p;
    p.x = (LONG)X;
    p.y = (LONG)Y;
    if (g_hwnd) {
        GetCursorPos(&p);
        ScreenToClient(g_hwnd, &p);
        RECT cr = {0};
        GetClientRect(g_hwnd, &cr);
        if (p.x < 0) p.x = 0;
        if (p.y < 0) p.y = 0;
        if (p.x >= cr.right) p.x = cr.right - 1;
        if (p.y >= cr.bottom) p.y = cr.bottom - 1;
    }
    if (g_logCount < 40) {
        logf_("SetCursorPosition game=(%u,%u) raw=(%ld,%ld) flags=0x%08lx", X, Y, p.x, p.y, Flags);
        g_logCount++;
    }
    return g_origSetCursorPosition(self, (UINT)p.x, (UINT)p.y, Flags);
}

static void hook_device(IDirect3DDevice9* dev)
{
    if (!dev || g_devVtbl) return;
    g_devVtbl = *(void***)dev;
    DWORD oldProtect = 0;
    if (!VirtualProtect(g_devVtbl, sizeof(void*) * 12, PAGE_EXECUTE_READWRITE, &oldProtect)) {
        logf_("VirtualProtect(vtable) failed: %lu", GetLastError());
        return;
    }
    g_origSetCursorPosition = (PFN_SetCursorPosition)g_devVtbl[11];
    g_devVtbl[11] = (void*)Hook_SetCursorPosition;
    VirtualProtect(g_devVtbl, sizeof(void*) * 12, oldProtect, &oldProtect);
    logf_("hooked SetCursorPosition: %p -> %p", g_origSetCursorPosition, Hook_SetCursorPosition);
}

static HRESULT WINAPI Hook_CreateDevice(IDirect3D9* self, UINT Adapter, D3DDEVTYPE DeviceType,
                                        HWND hFocusWindow, DWORD BehaviorFlags,
                                        D3DPRESENT_PARAMETERS* pp, IDirect3DDevice9** ppDevice)
{
    HRESULT hr = g_origCreateDevice(self, Adapter, DeviceType, hFocusWindow, BehaviorFlags, pp, ppDevice);
    logf_("CreateDevice hr=0x%08lx hwnd=%p device=%p", hr, hFocusWindow, ppDevice ? *ppDevice : NULL);
    if (SUCCEEDED(hr) && ppDevice && *ppDevice) {
        g_hwnd = hFocusWindow;
        if (g_enabled) hook_device(*ppDevice);
    }
    return hr;
}

extern "C" IDirect3D9* WINAPI Direct3DCreate9(UINT SDKVersion)
{
    if (!g_realCreate9) {
        wchar_t sysdir[MAX_PATH];
        GetSystemDirectoryW(sysdir, MAX_PATH);
        wcscat_s(sysdir, MAX_PATH, L"\\d3d9.dll");
        g_real = LoadLibraryW(sysdir);
        if (!g_real) { logf_("cannot load real d3d9: %lu", GetLastError()); return NULL; }
        g_realCreate9 = (IDirect3D9* (WINAPI*)(UINT))GetProcAddress(g_real, "Direct3DCreate9");
        if (!g_realCreate9) { logf_("no Direct3DCreate9"); return NULL; }
    }
    IDirect3D9* d3d = g_realCreate9(SDKVersion);
    if (d3d && !g_d3d9Vtbl) {
        g_d3d9Vtbl = *(void***)d3d;
        DWORD oldProtect = 0;
        if (VirtualProtect(g_d3d9Vtbl, sizeof(void*) * 17, PAGE_EXECUTE_READWRITE, &oldProtect)) {
            g_origCreateDevice = (PFN_CreateDevice)g_d3d9Vtbl[16];
            g_d3d9Vtbl[16] = (void*)Hook_CreateDevice;
            VirtualProtect(g_d3d9Vtbl, sizeof(void*) * 17, oldProtect, &oldProtect);
            logf_("hooked CreateDevice: %p -> %p", g_origCreateDevice, Hook_CreateDevice);
        }
    }
    return d3d;
}

BOOL WINAPI DllMain(HINSTANCE hinst, DWORD reason, LPVOID)
{
    if (reason == DLL_PROCESS_ATTACH) {
        g_self = hinst;
        InitializeCriticalSection(&g_cs);
        DisableThreadLibraryCalls(hinst);
        log_init();
        read_ini();
        logf_("cursor fix loaded");
    } else if (reason == DLL_PROCESS_DETACH) {
        if (g_log) { fclose(g_log); g_log = NULL; }
        if (g_real) { FreeLibrary(g_real); g_real = NULL; }
        DeleteCriticalSection(&g_cs);
    }
    return TRUE;
}
