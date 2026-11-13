# The patch panel

This is the patchbay's interface: the page you see in the app window or at
`http://127.0.0.1:8420`. It's built ahead of time and committed in `dist/`, so
you don't need any web tooling just to use sensor-patchbay.

## Changing it

You need Node.js. With the patchbay running (`python run.py`):

```bash
cd ui
npm install
npm run dev      # a live-reloading copy at http://localhost:5173
npm run build    # check types and rebuild dist/
```

Run `npm run build` before committing, or the app keeps serving the old panel.

The panel talks only to the patchbay on your own machine and loads nothing from
the internet. For how it's put together, start with `src/main.ts`.
