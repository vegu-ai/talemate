const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

function bundledNpm(node = process.execPath, platform = process.platform) {
    const paths = platform === 'win32' ? path.win32 : path.posix;
    const directory = paths.dirname(node);
    return platform === 'win32'
        ? paths.join(directory, 'node_modules', 'npm', 'bin', 'npm-cli.js')
        : paths.resolve(directory, '..', 'lib', 'node_modules', 'npm', 'bin', 'npm-cli.js');
}

function pinnedVersion(root) {
    const manifest = JSON.parse(fs.readFileSync(path.join(root, 'talemate_frontend', 'package.json'), 'utf8'));
    const match = /^pnpm@(\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?)(?:\+sha\d+\.[0-9a-f]+)?$/.exec(manifest.packageManager);
    if (!match) throw new Error('Frontend packageManager must pin an exact pnpm version.');
    return match[1];
}

function installedBin(prefix, version) {
    const directory = path.join(prefix, 'node_modules', 'pnpm');
    try {
        const manifest = JSON.parse(fs.readFileSync(path.join(directory, 'package.json'), 'utf8'));
        if (manifest.version !== version || typeof manifest.bin?.pnpm !== 'string') return null;
        const bin = path.resolve(directory, manifest.bin.pnpm);
        return fs.existsSync(bin) ? bin : null;
    } catch {
        return null;
    }
}

function execute(bin, args, options) {
    // pnpm 12 installs a native executable; earlier releases declare a Node script.
    return /\.(?:cjs|mjs|js)$/.test(bin)
        ? spawnSync(process.execPath, [bin, ...args], options)
        : spawnSync(bin, args, options);
}

function versionMatches(bin, version, options) {
    if (!bin) return false;
    const result = execute(bin, ['--version'], { ...options, encoding: 'utf8', timeout: 30000 });
    return result.status === 0 && result.stdout.trim() === version;
}

function runPnpm(root, args, npm = bundledNpm()) {
    const version = pinnedVersion(root);
    const prefix = path.join(root, 'embedded_node', 'pnpm');
    const options = {
        cwd: path.join(root, 'talemate_frontend'),
        env: { ...process.env, PATH: `${path.dirname(process.execPath)}${path.delimiter}${process.env.PATH || ''}` },
    };
    let bin = installedBin(prefix, version);
    if (!versionMatches(bin, version, options)) {
        if (!fs.existsSync(npm)) throw new Error(`Bundled npm not found at ${npm}. Reinstall Node.js and try again.`);
        console.error(`Installing portable pnpm ${version}...`);
        fs.rmSync(prefix, { recursive: true, force: true });
        const result = spawnSync(process.execPath, [
            npm, 'install', '--prefix', prefix, '--global=false', '--no-save',
            '--package-lock=false', '--ignore-scripts=false', '--include=optional',
            '--no-audit', '--no-fund', `pnpm@${version}`,
        ], { ...options, stdio: 'inherit' });
        if (result.error || result.status !== 0) {
            throw new Error(`Portable pnpm installation failed: ${result.error?.message || `npm exited ${result.status}`}`);
        }
        bin = installedBin(prefix, version);
        if (!versionMatches(bin, version, options)) {
            throw new Error(`Portable pnpm ${version} could not be verified. Remove ${prefix} and retry.`);
        }
    }
    const result = execute(bin, args, { ...options, stdio: 'inherit' });
    if (result.error) throw result.error;
    return result.status ?? 1;
}

if (require.main === module) {
    try {
        process.exitCode = runPnpm(path.resolve(__dirname, '..'), process.argv.slice(2));
    } catch (error) {
        console.error(`ERROR: ${error.message}`);
        process.exitCode = 1;
    }
}

module.exports = { bundledNpm, runPnpm };
