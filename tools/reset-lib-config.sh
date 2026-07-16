#! /usr/bin/env bash

# Library configs are sourced in one shell. Clear derived values before the
# next config so optional fields cannot leak from the previous library.
unset LIB_NAME LIPO_LIBS LIB_DEPENDS_BIN CMAKE_TARGETS_NAME
unset GIT_LOCAL_REPO REPO_DIR PATCH_DIR GIT_UPSTREAM GIT_COMMIT
unset GIT_REPO_VERSION GIT_WITH_SUBMODULE
unset PRE_COMPILE_TAG_ANDROID PRE_COMPILE_TAG_IOS
unset PRE_COMPILE_TAG_MACOS PRE_COMPILE_TAG_TVOS
