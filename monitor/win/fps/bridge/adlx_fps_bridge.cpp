// Optional C ABI bridge around AMD ADLX. Build only when the ADLX SDK is available.
#include "ADLXHelper.h"
#include "IPerformanceMonitoring.h"

#include <mutex>

using namespace adlx;

namespace {
ADLXHelper helper;
IADLXPerformanceMonitoringServicesPtr services;
std::mutex lock;
bool initialized = false;
}

#define FPS_EXPORT extern "C" __declspec(dllexport)

FPS_EXPORT int adlx_fps_initialize(void) {
    std::lock_guard<std::mutex> guard(lock);
    if (initialized) return 0;
    if (ADLX_FAILED(helper.Initialize())) return 1;
    if (ADLX_FAILED(helper.GetSystemServices()->GetPerformanceMonitoringServices(&services))) {
        helper.Terminate();
        return 2;
    }
    initialized = true;
    return 0;
}

FPS_EXPORT int adlx_fps_current(int* fps) {
    if (fps == nullptr) return 3;
    std::lock_guard<std::mutex> guard(lock);
    if (!initialized || services == nullptr) return 4;
    IADLXFPSPtr current;
    if (ADLX_FAILED(services->GetCurrentFPS(&current)) || current == nullptr) return 5;
    adlx_int value = 0;
    if (ADLX_FAILED(current->FPS(&value))) return 6;
    *fps = static_cast<int>(value);
    return 0;
}

FPS_EXPORT void adlx_fps_shutdown(void) {
    std::lock_guard<std::mutex> guard(lock);
    if (!initialized) return;
    services = nullptr;
    helper.Terminate();
    initialized = false;
}
