# ui — the patch panel

Plain TypeScript and the DOM — no UI framework — bundled by Vite, served by
`server.py` straight out of `dist/`. It talks to the engine over `fetch` (REST) and `EventSource` (live
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
  main.ts             builds the four top-level views, then starts the stores
  types.ts            the engine's wire format (mirrors engine/signals.py + graph.py)
  lib/
    api.ts            one typed function per REST endpoint
    ports.ts          port-id arithmetic, compatibility rules, value formatting
    dom.ts            h() / svg() element builders, setChildren(), classes()
  state/              singletons; each has subscribe()
    patchbay.ts       modules, graph, armed jack, selected cable, and every mutation
    live.ts           the /events stream, split into a raw frame + a status slice
    jacks.ts          jack id -> DOM nodes, for meters, cables and jack classes
    toast.ts          transient messages
  components/         topBar · presetBar · statusBar · patchArea · moduleCard ·
                      cables · meters · addModule · inspector · paramField · hint
```

## How the views work

There is no framework and no virtual DOM. Each view is a function that builds
its elements once, subscribes to the stores it needs, and patches only what
changed:

- **`patchbay`** state is immutable. Every change produces a new state object
  in which unchanged fields keep their identity, and subscribers get
  `(state, prev)`. A view compares the fields it cares about with `!==` and
  does nothing when they are equal.
- **`live.onStatus`** fires only when link / panic / rounded rate / preset /
  module revision actually change. The ~30 frames/s go to `live.subscribe`.
- Lists are **keyed by id** where rebuilding would hurt: module cards (a
  camera preview keeps its stream) and cables. The inspector is built once per
  selected cable. While that cable stays selected, refreshes update values in
  place, so a field you are tabbing through keeps its focus.
- Listeners are the DOM's own events. `onChange` in `h()` is the native
  `change` event, which fires once a value is committed (blur, Enter, stepper),
  so a number field doesn't send a PUT for every digit typed.

Two paths run every frame and write attributes directly:

- **Meters** (`meters.ts`): each frame touches two leaf nodes per jack, a
  `textContent` and a `style.width`.
- **Cables** (`cables.ts`): the path `d` is measured from the live DOM and
  recomputed only when something could have moved. Stroke width, opacity and
  dash offset are animated per frame from signal activity.

The engine stays the single source of truth: every mutation is a REST call
followed by a re-read of `/api/graph`.
