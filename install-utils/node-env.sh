# Shared helper for provisioning and activating a portable Node.js runtime.
# Requires bash (relies on BASH_SOURCE). Source it, then call:
#   install_embedded_node   - download + extract + activate (install.sh)
#   activate_embedded_node  - put it on PATH if present     (update.sh, start-frontend.sh)
#
# pnpm 11 (pinned via talemate_frontend/package.json "packageManager") needs
# Node.js >= 22.13. Rather than depend on whatever Node is on the system,
# install.sh downloads a portable Node into ./embedded_node and the update /
# start scripts reuse it. This mirrors what install.bat does on Windows.

# Pinned Node.js version for the portable runtime.
EMBEDDED_NODE_VERSION="22.22.3"

# Absolute path to ./embedded_node, resolved relative to this file so it works
# no matter what the caller's current working directory is.
EMBEDDED_NODE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/embedded_node"

# Map `uname -m` to the architecture string used by nodejs.org downloads.
_embedded_node_arch() {
    case "$(uname -m)" in
        x86_64 | amd64) echo "x64" ;;
        aarch64 | arm64) echo "arm64" ;;
        armv7l) echo "armv7l" ;;
        *) echo "" ;;
    esac
}

# Download $1 to $2 using whichever of curl/wget is available.
_embedded_node_download() {
    if command -v curl >/dev/null 2>&1; then
        curl -fL --progress-bar -o "$2" "$1"
    elif command -v wget >/dev/null 2>&1; then
        wget -q --show-progress -O "$2" "$1"
    else
        echo "Neither curl nor wget found; cannot download Node.js." >&2
        return 1
    fi
}

# Prepend the portable Node (if present) to PATH so node/npm/corepack resolve to it.
activate_embedded_node() {
    if [ -x "$EMBEDDED_NODE_DIR/bin/node" ]; then
        export PATH="$EMBEDDED_NODE_DIR/bin:$PATH"
    fi
}

# Download and extract the portable Node runtime, then activate it.
install_embedded_node() {
    local arch tarball url
    arch="$(_embedded_node_arch)"
    if [ -z "$arch" ]; then
        echo "Unsupported architecture '$(uname -m)' for portable Node.js."
        echo "Please install Node.js >= 22.13 manually and re-run."
        return 1
    fi

    tarball="node-v${EMBEDDED_NODE_VERSION}-linux-${arch}.tar.xz"
    url="https://nodejs.org/dist/v${EMBEDDED_NODE_VERSION}/${tarball}"

    echo "Downloading portable Node.js v${EMBEDDED_NODE_VERSION} (${arch})..."
    rm -rf "$EMBEDDED_NODE_DIR"
    mkdir -p "$EMBEDDED_NODE_DIR"

    if ! _embedded_node_download "$url" "/tmp/${tarball}"; then
        echo "Failed to download Node.js from ${url}"
        rm -rf "$EMBEDDED_NODE_DIR"
        return 1
    fi

    # --strip-components 1 drops the node-vX.Y.Z-linux-<arch>/ top-level directory.
    if ! tar -xf "/tmp/${tarball}" -C "$EMBEDDED_NODE_DIR" --strip-components 1; then
        echo "Failed to extract ${tarball} (is xz/xz-utils installed?)"
        rm -f "/tmp/${tarball}"
        rm -rf "$EMBEDDED_NODE_DIR"
        return 1
    fi
    rm -f "/tmp/${tarball}"

    activate_embedded_node
    echo "Using portable Node.js at ${EMBEDDED_NODE_DIR} ($(node -v))"
}
