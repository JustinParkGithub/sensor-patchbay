# ui — the patch panel

React + TypeScript, bundled by Vite, served by `server.py` straight out of
`dist/`. It talks to the engine over `fetch` (REST) and `EventSource` (live
state) and loads nothing from the internet.

## Running it

`dist/` **is committed to git**, so the normal path needs no Node at all:

```bash
python run.py --mock --dry-run     # http://127.0.0.1:8420
```

To change the UI:

```bash
cd ui
npm install
npm run dev      # http://localhost:5173, proxies /api + /events to :8420
npm run build    # typecheck + rebuild dist/ — commit the result
```

`npm run dev` expects `python run.py` to already be up on port 8420; without it
the panel loads but every request fails. Always `npm run build` before
committing, or the served bundle won't match the source.

## Layout

```
src/
  types.ts            the engine's wire format (mirrors engine/signals.py + graph.py)
  lib/
    api.ts            one typed function per REST endpoint
    ports.ts          port-id arithmetic, compatibility rules, value formatting
  state/
    ToastProvider     transient messages
    LiveProvider      the /events stream, split into a raw frame + a status slice
    PatchbayProvider  modules, graph, armed jack, selected cable, and every mutation
    JackRegistry      jack id -> DOM nodes, for the two things that bypass React
  hooks/
    useMeters         paints jack readouts + bars from the live stream
    useAnimationFrame per-frame callback with a stable loop
    useCommitOnChange native `change` (not per-keystroke `input`) for number fields
  components/         TopBar · PatchArea · Cables · Jack · Inspector · …
```

## Why parts of this are imperative

The engine pushes ~30 frames/s and the cables animate at 60fps. Two paths
deliberately write the DOM instead of re-rendering:

- **Meters** (`useMeters`) — each frame touches two leaf nodes per jack. Going
  through React state would re-render the whole panel 30x/s for values that are
  already a single `textContent` and `style.width` write.
- **Cables** (`Cables.tsx`) — React owns the *set* of `<path>` elements, keyed
  by connection id. Their `d` is measured from the live DOM and recomputed only
  when something could have moved; stroke width/opacity/dash offset are
  animated per frame. Neither is a React prop, so renders and animation never
  fight over the same attribute.

Everything else — module layout, jack state classes, the inspector, presets —
is ordinary React state derived from the engine, which stays the single source
of truth: every mutation is a REST call followed by a re-read of `/api/graph`.
