find_package(PkgConfig)
if(${PkgConfig_FOUND})
  pkg_check_modules(PC_CUDNN QUIET CUDNN)
endif()

if("${CUDNN_ROOT_DIR}" STREQUAL "" AND NOT "$ENV{CUDNN_ROOT_DIR}" STREQUAL "")
  set(CUDNN_ROOT_DIR $ENV{CUDNN_ROOT_DIR})
endif()

if(MGE_CUDA_USE_STATIC AND NOT MGE_WITH_CUDNN_SHARED)
  find_library(
    CUDNN_LIBRARY
    NAMES libcudnn_static.a cudnn.lib
    PATHS ${ALTER_LD_LIBRARY_PATHS} ${CUDNN_ROOT_DIR} ${PC_CUDNN_LIBRARY_DIRS}
          ${CMAKE_INSTALL_PREFIX}
    HINTS ${ALTER_LIBRARY_PATHS}
    PATH_SUFFIXES lib lib64
    DOC "CUDNN library.")
else()
  find_library(
    CUDNN_LIBRARY
    NAMES libcudnn.so libcudnn.dylib cudnn64.dll
    PATHS ${ALTER_LD_LIBRARY_PATHS} ${CUDNN_ROOT_DIR} ${PC_CUDNN_LIBRARY_DIRS}
          ${CMAKE_INSTALL_PREFIX}
    HINTS ${ALTER_LIBRARY_PATHS}
    PATH_SUFFIXES lib lib64
    DOC "CUDNN library.")
endif()

if(CUDNN_LIBRARY STREQUAL "CUDNN_LIBRARY-NOTFOUND")
  message(
    FATAL_ERROR
      "Can not find CuDNN Library, please refer to scripts/cmake-build/BUILD_README.md to init CUDNN env"
  )
endif()

get_filename_component(__found_cudnn_root ${CUDNN_LIBRARY}/../.. REALPATH)
find_path(
  CUDNN_INCLUDE_DIR
  NAMES cudnn.h
  HINTS $ENV{PC_CUDNN_INCLUDE_DIRS} ${CUDNN_ROOT_DIR} ${CUDA_TOOLKIT_INCLUDE}
        ${__found_cudnn_root}
  PATH_SUFFIXES include
  DOC "Path to CUDNN include directory.")

if(CUDNN_INCLUDE_DIR STREQUAL "CUDNN_INCLUDE_DIR-NOTFOUND")
  message(
    FATAL_ERROR
      "Can not find CuDNN INCLUDE, please refer to scripts/cmake-build/BUILD_README.md to init CUDNN env"
  )
endif()

if(EXISTS ${CUDNN_INCLUDE_DIR}/cudnn_version.h)
  file(READ ${CUDNN_INCLUDE_DIR}/cudnn_version.h CUDNN_VERSION_FILE_CONTENTS)
else()
  file(READ ${CUDNN_INCLUDE_DIR}/cudnn.h CUDNN_VERSION_FILE_CONTENTS)
endif()

string(REGEX MATCH "define CUDNN_MAJOR * +([0-9]+)" CUDNN_MAJOR_VERSION
             "${CUDNN_VERSION_FILE_CONTENTS}")
string(REGEX REPLACE "define CUDNN_MAJOR * +([0-9]+)" "\\1" CUDNN_MAJOR_VERSION
                     "${CUDNN_MAJOR_VERSION}")
string(REGEX MATCH "define CUDNN_MINOR * +([0-9]+)" CUDNN_MINOR_VERSION
             "${CUDNN_VERSION_FILE_CONTENTS}")
string(REGEX REPLACE "define CUDNN_MINOR * +([0-9]+)" "\\1" CUDNN_MINOR_VERSION
                     "${CUDNN_MINOR_VERSION}")
string(REGEX MATCH "define CUDNN_PATCHLEVEL * +([0-9]+)" CUDNN_PATCH_VERSION
             "${CUDNN_VERSION_FILE_CONTENTS}")
string(REGEX REPLACE "define CUDNN_PATCHLEVEL * +([0-9]+)" "\\1" CUDNN_PATCH_VERSION
                     "${CUDNN_PATCH_VERSION}")
set(CUDNN_VERSION ${CUDNN_MAJOR_VERSION}.${CUDNN_MINOR_VERSION}.${CUDNN_PATCH_VERSION})

if(MGE_CUDA_USE_STATIC)
  add_library(libcudnn STATIC IMPORTED)
else()
  add_library(libcudnn SHARED IMPORTED)
endif()

set_target_properties(
  libcudnn PROPERTIES IMPORTED_LOCATION ${CUDNN_LIBRARY} INTERFACE_INCLUDE_DIRECTORIES
                                                         ${CUDNN_INCLUDE_DIR})

message(STATUS "Found CuDNN: ${__found_cudnn_root} (found version: ${CUDNN_VERSION})")
