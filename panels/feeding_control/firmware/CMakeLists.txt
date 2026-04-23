cmake_minimum_required(VERSION 3.22)

include($ENV{IDF_PATH}/tools/cmake/project.cmake)

# Trim the build to the minimum set of components.
idf_build_set_property(MINIMAL_BUILD ON)

# Pull in the shared platform component from the monorepo's platform/ tree.
list(APPEND EXTRA_COMPONENT_DIRS
    "${CMAKE_CURRENT_LIST_DIR}/../../../platform/firmware/components")

project(thread_panel_feeding_control)
