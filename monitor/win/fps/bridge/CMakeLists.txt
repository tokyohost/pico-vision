cmake_minimum_required(VERSION 3.20)
project(adlx_fps_bridge LANGUAGES CXX)

if(NOT DEFINED ADLX_SDK_ROOT)
    message(FATAL_ERROR "Pass -DADLX_SDK_ROOT=<path-to-ADLX-SDK>")
endif()

add_library(adlx_fps_bridge SHARED
    adlx_fps_bridge.cpp
    "${ADLX_SDK_ROOT}/ADLXHelper/Windows/Cpp/ADLXHelper.cpp"
)
target_compile_features(adlx_fps_bridge PRIVATE cxx_std_17)
target_include_directories(adlx_fps_bridge PRIVATE
    "${ADLX_SDK_ROOT}/ADLXHelper/Windows/Cpp"
    "${ADLX_SDK_ROOT}/Include"
)
set_target_properties(adlx_fps_bridge PROPERTIES
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_CURRENT_LIST_DIR}/../bin"
)
