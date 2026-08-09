# talemate_frontend

This project uses [pnpm](https://pnpm.io/). You do not need to install it
yourself — it is provisioned automatically via
[Corepack](https://nodejs.org/api/corepack.html), which ships with Node.js. The
pinned pnpm version lives in the `packageManager` field of `package.json`.

Run `corepack enable` once to put `pnpm` on your `PATH`, or prefix the commands
below with `corepack ` (e.g. `corepack pnpm install`).

## Project setup
```
pnpm install
```

### Compiles and hot-reloads for development
```
pnpm serve
```

### Compiles and minifies for production
```
pnpm build
```

### Runs the unit tests
```
pnpm test
```

Watch mode:
```
pnpm test:watch
```

The suites live in `tests/unit/*.spec.js` and run in the `node` environment —
there is no DOM. Run both commands from `talemate_frontend`.

### Customize configuration
See [Configuration Reference](https://vite.dev/config/).
